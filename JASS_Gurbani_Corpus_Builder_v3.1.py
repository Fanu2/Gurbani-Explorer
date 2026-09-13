from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)

APP_NAME = "JASS Gurbani Corpus Builder"
VERSION = "3.1"
DB_NAME = "gurbani.db"

# Conservative parser vocabulary. These are structural hints, not scholarly claims.
REF_PATTERNS = (
    r"https?://", r"www\.", r"\bsource\b", r"\breference\b",
    r"gurbanifiles", r"copyright", r"internet archive", r"wayback",
    r"skip to main content", r"sign up", r"log in", r"donate",
    r"upload", r"hamburger icon", r"software icon", r"images icon",
    r"video icon", r"audio icon", r"\.(?:com|org|net)\b",
)
ANG_PATTERNS = (
    r"^\s*(?:ang|ਅੰਗ)\s*[:#-]?\s*(\d{1,4})\s*$",
    r"^\s*(?:page|ਪੰਨਾ)\s*[:#-]?\s*(\d{1,4})\s*$",
)
RAAG_WORDS = (
    "ਸਿਰੀਰਾਗੁ","ਮਾਝ","ਗਉੜੀ","ਆਸਾ","ਗੂਜਰੀ","ਦੇਵਗੰਧਾਰੀ","ਬਿਹਾਗੜਾ",
    "ਵਡਹੰਸੁ","ਸੋਰਠਿ","ਧਨਾਸਰੀ","ਜੈਤਸਰੀ","ਟੋਡੀ","ਬੈਰਾੜੀ","ਤਿਲੰਗ",
    "ਸੂਹੀ","ਬਿਲਾਵਲੁ","ਗੋਂਡ","ਰਾਮਕਲੀ","ਨਟ ਨਾਰਾਇਨ","ਮਾਲੀ ਗਉੜਾ",
    "ਮਾਰੂ","ਤੁਖਾਰੀ","ਕੇਦਾਰਾ","ਭੈਰਉ","ਬਸੰਤੁ","ਸਾਰੰਗ","ਮਲਾਰ","ਕਾਨੜਾ",
    "ਕਲਿਆਨੁ","ਪ੍ਰਭਾਤੀ","ਜੈਜਾਵੰਤੀ",
)
GURU_WORDS = (
    "ਮਹਲਾ", "ਗੁਰੂ ਨਾਨਕ", "ਗੁਰੂ ਅੰਗਦ", "ਗੁਰੂ ਅਮਰ", "ਗੁਰੂ ਰਾਮ", "ਗੁਰੂ ਅਰਜਨ",
    "ਗੁਰੂ ਹਰਿਗੋਬਿੰਦ", "ਗੁਰੂ ਹਰਿਰਾਇ", "ਗੁਰੂ ਹਰਿਕ੍ਰਿਸ਼ਨ", "ਗੁਰੂ ਤੇਗ",
)
NUMBERING_RE = re.compile(r"^\s*[\(\[]?\s*[\d੦-੯]+\s*[\)\].:-]?\s*$")
STANZA_RE = re.compile(r"(?:॥\s*[\d੦-੯]+\s*॥|\|\|\s*[\d੦-੯]+\s*\|\|)")

KINDS = [
    "GURBANI", "ANG_MARKER", "RAAG_MARKER", "AUTHOR_MARKER", "STANZA_MARKER",
    "NUMBERING", "REFERENCE", "NOISE", "FRAGMENT", "OTHER", "DUPLICATE"
]

@dataclass
class Record:
    source_line: int
    text: str
    kind: str
    included: bool
    duplicate: bool = False
    ang: int | None = None
    raag: str = ""
    author: str = ""
    section: str = ""
    passage_id: str = ""
    stanza_no: int | None = None
    review_status: str = "AUTO"


def normalize_text(s: str) -> str:
    s = s.replace("\ufeff", "").replace("\u00a0", " ")
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def has_gurmukhi(s: str) -> bool:
    return any("\u0a00" <= c <= "\u0a7f" for c in s)


def gurmukhi_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum("\u0a00" <= c <= "\u0a7f" for c in letters) / len(letters)


def classify(text: str) -> str:
    low = text.casefold()
    if any(re.search(p, low) for p in REF_PATTERNS):
        return "REFERENCE"
    if any(re.match(p, text, re.I) for p in ANG_PATTERNS):
        return "ANG_MARKER"
    if NUMBERING_RE.match(text) and not has_gurmukhi(text):
        return "NUMBERING"
    if any(w in text for w in RAAG_WORDS):
        return "RAAG_MARKER"
    if any(w in text for w in GURU_WORDS) and len(text) < 180:
        return "AUTHOR_MARKER"
    if STANZA_RE.search(text):
        return "STANZA_MARKER"
    if has_gurmukhi(text):
        # Short Gurmukhi fragments are retained for review rather than discarded.
        if len(re.sub(r"\s+", "", text)) < 5:
            return "FRAGMENT"
        return "GURBANI"
    if re.search(r"[A-Za-z]{3,}", text):
        return "NOISE"
    return "OTHER"


def extract_ang(text: str) -> int | None:
    for p in ANG_PATTERNS:
        m = re.match(p, text, re.I)
        if m:
            return int(m.group(1))
    return None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Corpus:
    def __init__(self):
        self.records: list[Record] = []
        self.path: Path | None = None
        self.encoding = "UTF-8"
        self._seen: set[str] = set()
        self.raw_line_count = 0

    def import_file(self, path: str):
        p = Path(path)
        raw = p.read_bytes()
        self.encoding = "UTF-8"
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            self.encoding = "UTF-8 with replacement"
            text = raw.decode("utf-8", errors="replace")
        self.path = p
        self.records.clear()
        self._seen.clear()
        self.raw_line_count = len(text.splitlines())

        current_ang = None
        current_raag = ""
        current_author = ""
        current_section = ""
        passage_counter = 0
        stanza_counter = 0
        previous_source_line = 0

        for n, rawline in enumerate(text.splitlines(), 1):
            line = normalize_text(rawline)
            if not line:
                previous_source_line = n
                continue

            kind = classify(line)
            ang = extract_ang(line)
            if ang is not None:
                current_ang = ang
                current_section = line
            if kind == "RAAG_MARKER":
                current_raag = line
                current_section = line
            if kind == "AUTHOR_MARKER":
                current_author = line
                current_section = line

            # A passage is a contiguous source block of Gurbani lines. A gap or
            # structural marker starts a new passage. This is intentionally a
            # source-context grouping, not a claim about canonical shabad boundaries.
            if kind in ("GURBANI", "STANZA_MARKER"):
                if previous_source_line and n - previous_source_line > 1:
                    passage_counter += 1
                elif not passage_counter:
                    passage_counter = 1
                if kind == "STANZA_MARKER":
                    stanza_counter += 1
                passage_id = f"ANG-{current_ang:04d}-P{passage_counter:05d}" if current_ang else f"P{passage_counter:05d}"
            else:
                passage_id = ""
                if kind in ("ANG_MARKER", "RAAG_MARKER", "AUTHOR_MARKER"):
                    # Next Gurbani record continues under the current context.
                    pass

            duplicate = digest(line) in self._seen
            self._seen.add(digest(line))
            included = kind in ("GURBANI", "STANZA_MARKER")
            review_status = "AUTO"
            if kind in ("FRAGMENT", "OTHER", "NOISE"):
                review_status = "REVIEW"
            self.records.append(Record(
                n, line, kind, included, duplicate, current_ang, current_raag,
                current_author, current_section, passage_id,
                stanza_counter if stanza_counter else None, review_status
            ))
            previous_source_line = n

        # Duplicate rows are retained for audit, but excluded from clean corpus.
        for r in self.records:
            if r.duplicate and r.kind in ("GURBANI", "STANZA_MARKER"):
                r.included = False
                r.kind = "DUPLICATE"
                r.review_status = "AUTO"

    @property
    def stats(self):
        counts = {}
        for r in self.records:
            counts[r.kind] = counts.get(r.kind, 0) + 1
        return counts

    def clean_gurbani(self):
        return [r for r in self.records if r.included and r.kind in ("GURBANI", "STANZA_MARKER")]

    def passages(self):
        groups = {}
        for r in self.clean_gurbani():
            groups.setdefault(r.passage_id, []).append(r)
        return groups


def build_db(corpus: Corpus, destination: str) -> int:
    con = sqlite3.connect(destination)
    cur = con.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;
    DROP TABLE IF EXISTS gurbani_fts;
    DROP TABLE IF EXISTS lines;
    DROP TABLE IF EXISTS passages;
    DROP TABLE IF EXISTS source_records;
    DROP TABLE IF EXISTS corpus_meta;

    CREATE TABLE corpus_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE passages (
        id TEXT PRIMARY KEY,
        ang INTEGER,
        raag TEXT,
        author TEXT,
        section TEXT,
        text TEXT NOT NULL,
        line_count INTEGER NOT NULL
    );
    CREATE TABLE lines (
        id INTEGER PRIMARY KEY,
        passage_id TEXT NOT NULL,
        source_line INTEGER NOT NULL,
        ang INTEGER,
        raag TEXT,
        author TEXT,
        stanza_no INTEGER,
        text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        text_hash TEXT NOT NULL UNIQUE,
        FOREIGN KEY(passage_id) REFERENCES passages(id)
    );
    CREATE TABLE source_records (
        id INTEGER PRIMARY KEY,
        source_line INTEGER NOT NULL,
        kind TEXT NOT NULL,
        included INTEGER NOT NULL,
        duplicate INTEGER NOT NULL,
        review_status TEXT NOT NULL,
        text TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE gurbani_fts USING fts5(
        text, normalized_text, passage_id UNINDEXED,
        content='lines', content_rowid='id'
    );
    """)
    meta = {
        "builder": f"{APP_NAME} {VERSION}",
        "source_file": str(corpus.path) if corpus.path else "",
        "encoding": corpus.encoding,
        "raw_line_count": str(corpus.raw_line_count),
        "records": str(len(corpus.records)),
        "clean_lines": str(len(corpus.clean_gurbani())),
        "passages": str(len(corpus.passages())),
        "note": "Passages are conservative source-context groupings, not scholarly shabad boundaries.",
    }
    cur.executemany("INSERT INTO corpus_meta VALUES (?,?)", meta.items())

    for r in corpus.records:
        cur.execute(
            "INSERT INTO source_records(source_line,kind,included,duplicate,review_status,text) VALUES(?,?,?,?,?,?)",
            (r.source_line, r.kind, int(r.included), int(r.duplicate), r.review_status, r.text)
        )

    for pid, rows in corpus.passages().items():
        first = rows[0]
        cur.execute(
            "INSERT INTO passages(id,ang,raag,author,section,text,line_count) VALUES(?,?,?,?,?,?,?)",
            (pid, first.ang, first.raag, first.author, first.section,
             "\n".join(x.text for x in rows), len(rows))
        )
        for r in rows:
            cur.execute(
                "INSERT INTO lines(passage_id,source_line,ang,raag,author,stanza_no,text,normalized_text,text_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, r.source_line, r.ang, r.raag, r.author, r.stanza_no,
                 r.text, r.text.casefold(), digest(r.text))
            )
    cur.execute("INSERT INTO gurbani_fts(rowid,text,normalized_text,passage_id) SELECT id,text,normalized_text,passage_id FROM lines")
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
    con.close()
    return n


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1500, 920)
        self.corpus = Corpus()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.update_search)
        self.build_ui()

    def build_ui(self):
        root = QWidget(); main = QVBoxLayout(root)
        header = QHBoxLayout()
        title = QLabel(f"ੴ  {APP_NAME}")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self.status = QLabel("No corpus loaded")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title); header.addStretch(); header.addWidget(self.status); main.addLayout(header)
        actions = QHBoxLayout()
        for text, slot in [
            ("📂 Open TXT", self.open_txt), ("⚡ Import / Rebuild", self.reimport),
            ("✓ Validate", self.validate), ("🧹 Review Queue", self.review_queue),
            ("🗄 Build gurbani.db", self.build_db), ("JSON", self.export_json), ("CSV", self.export_csv)
        ]:
            b = QPushButton(text); b.clicked.connect(slot); actions.addWidget(b)
        actions.addStretch(); main.addLayout(actions)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.overview_tab(), "Overview")
        self.tabs.addTab(self.records_tab(), "Records")
        self.tabs.addTab(self.search_tab(), "Search + Context")
        self.tabs.addTab(self.structure_tab(), "Structure Inspector")
        self.tabs.addTab(self.review_tab(), "Review Queue")
        self.tabs.addTab(self.validation_tab(), "Validation")
        main.addWidget(self.tabs)
        self.setCentralWidget(root)

    def overview_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        box = QGroupBox("Corpus overview"); form = QFormLayout(box)
        self.file_label = QLabel("—"); self.encoding_label = QLabel("—"); self.stats_label = QLabel("—")
        form.addRow("File:", self.file_label); form.addRow("Encoding:", self.encoding_label); form.addRow("Statistics:", self.stats_label)
        lay.addWidget(box)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.sample_left = QPlainTextEdit(); self.sample_right = QPlainTextEdit()
        self.sample_left.setReadOnly(True); self.sample_right.setReadOnly(True)
        split.addWidget(self.sample_left); split.addWidget(self.sample_right); lay.addWidget(split, 1)
        return w

    def records_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.filter = QComboBox(); self.filter.addItems(["ALL"] + KINDS)
        self.filter.currentTextChanged.connect(self.populate_records); lay.addWidget(self.filter)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Line","Type","Included","Duplicate","Ang","Passage","Stanza","Review","Text"])
        self.table.cellClicked.connect(self.record_clicked); self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table); return w

    def search_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        row = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Search Gurmukhi text…")
        self.search.textChanged.connect(lambda: self._timer.start(160)); row.addWidget(self.search)
        self.context_spin = QSpinBox(); self.context_spin.setRange(0, 10); self.context_spin.setValue(2)
        row.addWidget(QLabel("Extra lines:")); row.addWidget(self.context_spin); lay.addLayout(row)
        self.results = QListWidget(); self.results.itemClicked.connect(self.show_result); lay.addWidget(self.results, 1)
        self.context = QPlainTextEdit(); self.context.setReadOnly(True); lay.addWidget(self.context, 1)
        return w

    def structure_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.structure = QTableWidget(0, 8)
        self.structure.setHorizontalHeaderLabels(["Line","Ang","Raag","Author","Passage","Stanza","Lines in Passage","Text"])
        self.structure.horizontalHeader().setStretchLastSection(True); lay.addWidget(self.structure); return w

    def review_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.review_filter = QComboBox(); self.review_filter.addItems(["REVIEW", "FRAGMENT", "NOISE", "OTHER", "REFERENCE", "DUPLICATE"])
        self.review_filter.currentTextChanged.connect(self.populate_review); lay.addWidget(self.review_filter)
        self.review_table = QTableWidget(0, 6)
        self.review_table.setHorizontalHeaderLabels(["Line","Type","Keep?","Review","Text","Context"])
        self.review_table.horizontalHeader().setStretchLastSection(True); self.review_table.cellDoubleClicked.connect(self.toggle_review)
        lay.addWidget(self.review_table)
        lay.addWidget(QLabel("Double-click a row to toggle Keep/Exclude. Decisions affect the next database build."))
        return w

    def validation_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); self.validation = QPlainTextEdit(); self.validation.setReadOnly(True); lay.addWidget(self.validation); return w

    def open_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Gurbani TXT", "", "Text files (*.txt);;All files (*.*)")
        if path: self.corpus.import_file(path); self.refresh_all()

    def reimport(self):
        if self.corpus.path: self.corpus.import_file(str(self.corpus.path)); self.refresh_all()
        else: self.open_txt()

    def refresh_all(self):
        self.file_label.setText(str(self.corpus.path or "—")); self.encoding_label.setText(self.corpus.encoding)
        s = self.corpus.stats; total = len(self.corpus.records); dup = sum(r.duplicate for r in self.corpus.records)
        clean = len(self.corpus.clean_gurbani()); passages = len(self.corpus.passages())
        self.stats_label.setText(
            f"Raw lines: {self.corpus.raw_line_count:,} • Records: {total:,} • Clean Gurbani lines: {clean:,} • "
            f"Passages: {passages:,} • References: {s.get('REFERENCE',0):,} • Noise: {s.get('NOISE',0):,} • "
            f"Fragments: {s.get('FRAGMENT',0):,} • Duplicates: {dup:,}"
        )
        g = [r.text for r in self.corpus.records if r.included][:100]
        x = [f"[{r.kind}] {r.text}" for r in self.corpus.records if not r.included][:100]
        self.sample_left.setPlainText("\n".join(g)); self.sample_right.setPlainText("\n".join(x))
        self.populate_records(); self.populate_structure(); self.populate_review(); self.validate()
        self.status.setText(f"{total:,} records • {clean:,} clean Gurbani lines • {passages:,} passages")

    def populate_records(self):
        if not hasattr(self, "table"): return
        wanted = self.filter.currentText(); rows = [r for r in self.corpus.records if wanted == "ALL" or r.kind == wanted]
        self.table.setRowCount(min(len(rows), 15000))
        for i, r in enumerate(rows[:15000]):
            vals = [r.source_line, r.kind, "YES" if r.included else "NO", "YES" if r.duplicate else "NO",
                    r.ang or "", r.passage_id, r.stanza_no or "", r.review_status, r.text]
            for j, v in enumerate(vals): self.table.setItem(i, j, QTableWidgetItem(str(v)))

    def populate_structure(self):
        if not hasattr(self, "structure"): return
        rows = self.corpus.clean_gurbani(); sizes = {k: len(v) for k,v in self.corpus.passages().items()}
        self.structure.setRowCount(min(len(rows), 15000))
        for i, r in enumerate(rows[:15000]):
            vals = [r.source_line, r.ang or "", r.raag, r.author, r.passage_id, r.stanza_no or "", sizes.get(r.passage_id, 0), r.text]
            for j, v in enumerate(vals): self.structure.setItem(i, j, QTableWidgetItem(str(v)))

    def update_search(self):
        q = normalize_text(self.search.text()); self.results.clear(); self.context.clear()
        if not q: return
        qlow = q.casefold(); hits = []
        for i, r in enumerate(self.corpus.records):
            if r.included and qlow in r.text.casefold(): hits.append((i,r))
        for i, r in hits[:500]:
            item = QListWidgetItem(f"Ang {r.ang or '—'} • {r.passage_id or '—'} • line {r.source_line}\n{r.text}")
            item.setData(Qt.ItemDataRole.UserRole, i); self.results.addItem(item)
        if not hits: self.context.setPlainText("No matching Gurbani records found.")

    def show_result(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None: return
        r = self.corpus.records[idx]; n = self.context_spin.value()
        if r.passage_id:
            group = [i for i,x in enumerate(self.corpus.records) if x.passage_id == r.passage_id and x.included]
            if group:
                pos = group.index(idx); selected = group[max(0,pos-n):min(len(group),pos+n+1)]
                lines = [f"Ang {r.ang or '—'} • {r.raag or '—'} • {r.author or '—'} • {r.passage_id}", ""]
                lines += [f"[{self.corpus.records[j].source_line:>6}] {self.corpus.records[j].text}{'  ← MATCH' if j == idx else ''}" for j in selected]
                self.context.setPlainText("\n".join(lines)); return
        lo, hi = max(0, idx-n), min(len(self.corpus.records), idx+n+1)
        self.context.setPlainText("\n".join(f"[{self.corpus.records[j].source_line:>6}] {self.corpus.records[j].text}{'  ← MATCH' if j == idx else ''}" for j in range(lo,hi)))

    def record_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item:
            line = int(item.text()); r = next((x for x in self.corpus.records if x.source_line == line), None)
            if r: self.tabs.setCurrentIndex(2); self.context.setPlainText(f"Source line: {r.source_line}\nType: {r.kind}\nPassage: {r.passage_id}\n\n{r.text}")

    def populate_review(self):
        if not hasattr(self, "review_table"): return
        wanted = self.review_filter.currentText()
        rows = [r for r in self.corpus.records if (r.review_status == "REVIEW" if wanted == "REVIEW" else r.kind == wanted)]
        self.review_table.setRowCount(min(len(rows), 10000))
        for i, r in enumerate(rows[:10000]):
            vals = [r.source_line, r.kind, "KEEP" if r.included else "EXCLUDE", r.review_status, r.text, r.passage_id]
            for j, v in enumerate(vals): self.review_table.setItem(i, j, QTableWidgetItem(str(v)))

    def toggle_review(self, row, col):
        item = self.review_table.item(row, 0)
        if not item: return
        line = int(item.text()); r = next((x for x in self.corpus.records if x.source_line == line), None)
        if not r: return
        # References/noise/duplicates remain excluded unless explicitly promoted.
        r.included = not r.included
        r.review_status = "USER_KEEP" if r.included else "USER_EXCLUDE"
        self.populate_review(); self.refresh_all()

    def validate(self):
        if not hasattr(self, "validation"): return
        if not self.corpus.records: self.validation.setPlainText("No corpus loaded."); return
        bad = [r for r in self.corpus.records if "\ufffd" in r.text]
        no_gurmuk = [r for r in self.corpus.clean_gurbani() if not has_gurmukhi(r.text)]
        duplicate = sum(r.duplicate for r in self.corpus.records)
        passages = self.corpus.passages()
        broken = [p for p,rows in passages.items() if not rows or not all(has_gurmukhi(x.text) for x in rows)]
        review = [r for r in self.corpus.records if r.review_status == "REVIEW"]
        s = self.corpus.stats
        self.validation.setPlainText(
            f"CORPUS VALIDATION v{VERSION}\n{'='*70}\n"
            f"Raw source lines: {self.corpus.raw_line_count:,}\nRecords: {len(self.corpus.records):,}\n"
            f"Clean Gurbani lines: {len(self.corpus.clean_gurbani()):,}\nPassages: {len(passages):,}\n"
            f"Replacement characters: {len(bad):,}\nClean records without Gurmukhi: {len(no_gurmuk):,}\n"
            f"Duplicate records: {duplicate:,}\nReview queue: {len(review):,}\n"
            f"References: {s.get('REFERENCE',0):,}\nNoise: {s.get('NOISE',0):,}\nFragments: {s.get('FRAGMENT',0):,}\n"
            f"Ang markers: {s.get('ANG_MARKER',0):,}\nRaag markers: {s.get('RAAG_MARKER',0):,}\n"
            f"Author markers: {s.get('AUTHOR_MARKER',0):,}\nStanza markers: {s.get('STANZA_MARKER',0):,}\n"
            f"Empty/broken passages: {len(broken):,}\n\n"
            "QUALITY NOTE\n"
            "Passages are conservative contiguous source-context groups. They are designed to keep search results cohesive; "
            "they are NOT presented as verified scholarly shabad boundaries. Verify structural metadata against a trusted source before scholarly publication."
        )

    def review_queue(self):
        self.tabs.setCurrentIndex(4); self.populate_review()

    def build_db(self):
        if not self.corpus.records:
            QMessageBox.warning(self, "No corpus", "Open a TXT file first."); return
        path, _ = QFileDialog.getSaveFileName(self, "Build SQLite database", str(self.corpus.path.parent / DB_NAME), "SQLite DB (*.db)")
        if not path: return
        try:
            n = build_db(self.corpus, path)
            QMessageBox.information(self, "Database built", f"Created:\n{path}\n\nClean Gurbani lines: {n:,}\nPassages: {len(self.corpus.passages()):,}")
        except Exception as e:
            QMessageBox.critical(self, "Database error", str(e))

    def export_json(self):
        if not self.corpus.records: return
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", "gurbani_corpus.json", "JSON (*.json)")
        if not path: return
        data = [{
            "source_line":r.source_line,"type":r.kind,"included":r.included,"duplicate":r.duplicate,
            "ang":r.ang,"raag":r.raag,"author":r.author,"section":r.section,"passage_id":r.passage_id,
            "stanza_no":r.stanza_no,"review_status":r.review_status,"text":r.text
        } for r in self.corpus.records]
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Export complete", path)

    def export_csv(self):
        if not self.corpus.records: return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "gurbani_corpus.csv", "CSV (*.csv)")
        if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["source_line","type","included","duplicate","ang","raag","author","section","passage_id","stanza_no","review_status","text"])
            for r in self.corpus.records:
                w.writerow([r.source_line,r.kind,r.included,r.duplicate,r.ang,r.raag,r.author,r.section,r.passage_id,r.stanza_no,r.review_status,r.text])
        QMessageBox.information(self, "Export complete", path)


def main():
    app = QApplication(sys.argv); app.setStyle("Fusion")
    win = MainWindow(); win.show(); sys.exit(app.exec())

if __name__ == "__main__":
    main()
