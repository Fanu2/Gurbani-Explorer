"""
JASS Gurbani Corpus Importer / DB Builder v4.4
Shabad OS -> JASS_Gurbani.db

Design goals
------------
* Source SQLite is ALWAYS opened read-only.
* Build a separate, reproducible JASS database.
* Preserve original Shabad OS IDs and provenance.
* Prefer Shabad/line-group relationships and order_id for cohesive passages.
* Do not silently edit, clean, transliterate, or "correct" source Gurbani.
* Work defensively across Shabad OS schema releases.

Requirements:
    Python 3.x
    PySide6
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QComboBox,
    QProgressBar, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget, QHeaderView, QCheckBox
)

APP_NAME = "JASS Gurbani Corpus Builder"
VERSION = "v4.7"

TARGET_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE corpus (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_database TEXT NOT NULL,
    source_sha256 TEXT,
    scope TEXT NOT NULL
);

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    name TEXT,
    reference TEXT,
    raw_json TEXT
);

CREATE TABLE authors (
    id TEXT PRIMARY KEY,
    name TEXT,
    raw_json TEXT
);

CREATE TABLE ragas (
    id TEXT PRIMARY KEY,
    name TEXT,
    raw_json TEXT
);

CREATE TABLE sections (
    id TEXT PRIMARY KEY,
    name TEXT,
    raw_json TEXT
);

CREATE TABLE shabads (
    id TEXT PRIMARY KEY,
    source_group_id TEXT,
    author_id TEXT,
    raga_id TEXT,
    section_id TEXT,
    title TEXT,
    source_page_start INTEGER,
    source_page_end INTEGER,
    line_count INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE TABLE lines (
    id TEXT PRIMARY KEY,
    shabad_id TEXT,
    source_page INTEGER,
    source_line INTEGER,
    order_id INTEGER,
    first_letters TEXT,
    vishraam_first_letters TEXT,
    pronunciation TEXT,
    raw_json TEXT
);

CREATE TABLE line_content (
    line_id TEXT PRIMARY KEY,
    gurmukhi TEXT,
    content_source_id TEXT,
    raw_json TEXT
);

CREATE TABLE passages (
    id INTEGER PRIMARY KEY,
    shabad_id TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    first_line_order INTEGER,
    last_line_order INTEGER,
    source_page_start INTEGER,
    source_page_end INTEGER,
    text TEXT
);

CREATE TABLE passage_lines (
    passage_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (passage_id, line_id)
);

CREATE TABLE provenance (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source_database TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id TEXT,
    source_json TEXT
);

CREATE TABLE import_manifest (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_lines_shabad ON lines(shabad_id);
CREATE INDEX idx_lines_order ON lines(shabad_id, order_id);
CREATE INDEX idx_lines_page ON lines(source_page);
CREATE INDEX idx_content_text ON line_content(gurmukhi);
CREATE INDEX idx_passages_shabad ON passages(shabad_id);
CREATE INDEX idx_passage_lines_line ON passage_lines(line_id);
CREATE INDEX idx_provenance_entity ON provenance(entity_type, entity_id);
"""

def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'

def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def json_text(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)

def connect_ro(path: Path):
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def tables(conn):
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]

def cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({ident(table)})")]

def first_col(columns, candidates, contains=True):
    low = {c.lower(): c for c in columns}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    if contains:
        for c in columns:
            lc = c.lower()
            if any(token.lower() in lc for token in candidates):
                return c
    return None

def count(conn, table):
    if table not in tables(conn):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {ident(table)}").fetchone()[0]

def row_map(conn, table, row):
    return dict(zip(cols(conn, table), row))

def display_name_from_row(row):
    if not row:
        return ""
    for k, v in row.items():
        if v is None:
            continue
        if k.lower() in ("name", "title", "label", "english_name", "pa"):
            if isinstance(v, str):
                return v
    for v in row.values():
        if isinstance(v, str) and v.strip():
            return v[:160]
    return ""

class Builder(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1500, 930)
        self.source_path = None
        self.source = None
        self.schema = []
        self.analysis = {}
        self.building = False
        self._ui()

    def _ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        header = QFrame()
        header.setStyleSheet(
            "QFrame{background:#111925;border:1px solid #2b3b55;border-radius:12px;}"
        )
        h = QHBoxLayout(header)
        title = QLabel("ੴ  JASS Gurbani Corpus Builder")
        title.setStyleSheet("font-size:23pt;font-weight:700;color:#f4f7fb;")
        h.addWidget(title)
        sub = QLabel("v4.6  •  verified asset text → validated JASS database")
        sub.setStyleSheet("color:#91a8c7;padding-left:15px;")
        h.addWidget(sub)
        h.addStretch()
        self.badge = QLabel("NO SOURCE")
        self.badge.setStyleSheet(
            "padding:10px;border:1px solid #30435f;border-radius:8px;color:#a9c1e3;"
        )
        h.addWidget(self.badge)
        outer.addWidget(header)

        bar = QHBoxLayout()
        self.open_btn = QPushButton("📂 Open master.sqlite")
        self.open_btn.clicked.connect(self.open_source)
        bar.addWidget(self.open_btn)

        self.analyze_btn = QPushButton("🔎 Analyze Schema")
        self.analyze_btn.clicked.connect(self.analyze)
        self.analyze_btn.setEnabled(False)
        bar.addWidget(self.analyze_btn)

        self.build_btn = QPushButton("🗄 Build JASS_Gurbani.db")
        self.build_btn.setStyleSheet(
            "QPushButton{background:#21436f;border:1px solid #5e8ed4;padding:9px 14px;}"
        )
        self.build_btn.clicked.connect(self.build_database)
        bar.addWidget(self.build_btn)

        self.validate_btn = QPushButton("✓ Validate Built DB")
        self.validate_btn.clicked.connect(self.validate_target)
        bar.addWidget(self.validate_btn)

        bar.addStretch()
        bar.addWidget(QLabel("Scope:"))
        self.scope = QComboBox()
        self.scope.addItems([
            "Sri Guru Granth Sahib — auto-detect",
            "All source lines"
        ])
        bar.addWidget(self.scope)
        outer.addLayout(bar)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        # Overview
        overview = QWidget()
        ov = QVBoxLayout(overview)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        ov.addWidget(self.summary)
        self.tabs.addTab(overview, "Overview")

        # Mapping
        mapping = QWidget()
        mv = QVBoxLayout(mapping)
        self.mapping_table = QTableWidget(0, 3)
        self.mapping_table.setHorizontalHeaderLabels(["JASS field", "Detected source", "Status"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        mv.addWidget(self.mapping_table)
        self.tabs.addTab(mapping, "Mapping")

        # Source records
        source_page = QWidget()
        sv = QVBoxLayout(source_page)
        sv.addWidget(QLabel("Detected source/composition records"))
        self.source_table = QTableWidget(0, 4)
        self.source_table.setHorizontalHeaderLabels(["ID", "Name", "Reference", "Raw"])
        self.source_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.source_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.source_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        sv.addWidget(self.source_table)
        self.sggs_only = QCheckBox("Show likely Sri Guru Granth Sahib matches only")
        self.sggs_only.stateChanged.connect(self.populate_sources)
        sv.addWidget(self.sggs_only)
        self.tabs.addTab(source_page, "Sources")

        # Structure investigator
        structure_page = QWidget()
        stv = QVBoxLayout(structure_page)
        top = QHBoxLayout()
        top.addWidget(QLabel("Table:"))
        self.structure_table = QComboBox()
        self.structure_table.currentTextChanged.connect(self.inspect_table)
        top.addWidget(self.structure_table, 1)
        self.inspect_btn = QPushButton("🔬 Inspect Table")
        self.inspect_btn.clicked.connect(lambda: self.inspect_table(self.structure_table.currentText()))
        self.inspect_btn.setEnabled(False)
        top.addWidget(self.inspect_btn)
        self.text_scan_btn = QPushButton("📝 Find Text Candidates")
        self.text_scan_btn.clicked.connect(self.scan_text_candidates)
        self.text_scan_btn.setEnabled(False)
        top.addWidget(self.text_scan_btn)
        self.deep_scan_btn = QPushButton("🔎 Deep Text Investigation")
        self.deep_scan_btn.clicked.connect(self.deep_text_investigation)
        self.deep_scan_btn.setEnabled(False)
        top.addWidget(self.deep_scan_btn)
        self.relationship_btn = QPushButton("🔗 Relationships")
        self.relationship_btn.clicked.connect(self.scan_relationships)
        self.relationship_btn.setEnabled(False)
        top.addWidget(self.relationship_btn)
        self.asset_link_btn = QPushButton("🔬 Asset Link")
        self.asset_link_btn.clicked.connect(self.investigate_asset_link)
        self.asset_link_btn.setEnabled(False)
        top.addWidget(self.asset_link_btn)
        stv.addLayout(top)

        self.structure_info = QLabel("Open and analyze a SQLite source first.")
        self.structure_info.setWordWrap(True)
        stv.addWidget(self.structure_info)

        stv.addWidget(QLabel("Columns"))
        self.columns_table = QTableWidget(0, 6)
        self.columns_table.setHorizontalHeaderLabels(["#", "Column", "Type", "PK", "Not Null", "Sample / Notes"])
        self.columns_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.columns_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        stv.addWidget(self.columns_table, 1)

        stv.addWidget(QLabel("Sample rows (first 25)"))
        self.sample_table = QTableWidget(0, 0)
        self.sample_table.setEditTriggers(QTableWidget.NoEditTriggers)
        stv.addWidget(self.sample_table, 2)
        self.tabs.addTab(structure_page, "Structure")

        # Asset relationship investigation
        asset_page = QWidget()
        av = QVBoxLayout(asset_page)
        self.asset_link_info = QLabel("Asset relationship investigation has not been run yet.")
        self.asset_link_info.setWordWrap(True)
        av.addWidget(self.asset_link_info)
        self.asset_link_report = QPlainTextEdit()
        self.asset_link_report.setReadOnly(True)
        av.addWidget(self.asset_link_report)
        self.tabs.addTab(asset_page, "Asset Link")

        # Investigation report
        investigation_page = QWidget()
        iv = QVBoxLayout(investigation_page)
        self.investigation_info = QLabel("Deep investigation has not been run yet.")
        self.investigation_info.setWordWrap(True)
        iv.addWidget(self.investigation_info)
        self.investigation_table = QTableWidget(0, 8)
        self.investigation_table.setHorizontalHeaderLabels(["Rank", "Table", "Text column", "Link column", "Gurmukhi", "Line-ID overlap", "Rows", "Confidence"])
        self.investigation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.investigation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.investigation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        iv.addWidget(self.investigation_table, 2)
        self.investigation_report = QPlainTextEdit()
        self.investigation_report.setReadOnly(True)
        iv.addWidget(self.investigation_report, 2)
        self.tabs.addTab(investigation_page, "Investigation")

        # Log
        log_page = QWidget()
        lv = QVBoxLayout(log_page)
        self.progress = QProgressBar()
        lv.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lv.addWidget(self.log)
        self.tabs.addTab(log_page, "Build Log")

        self.statusBar().showMessage("Open a Shabad OS master.sqlite to begin.")
        self._style()

    def _style(self):
        self.setStyleSheet("""
        QMainWindow,QWidget{background:#0b1018;color:#e7edf7;font-family:"Segoe UI";font-size:10pt;}
        QLineEdit,QComboBox,QPlainTextEdit,QTableWidget{background:#0e151f;color:#edf3fb;border:1px solid #293a52;border-radius:7px;}
        QPushButton{background:#162235;color:#eaf1fb;border:1px solid #30435f;border-radius:8px;padding:8px 12px;}
        QPushButton:hover{background:#1c2c44;}
        QTabWidget::pane{border:1px solid #263449;background:#0e151f;}
        QTabBar::tab{background:#111925;padding:9px 15px;border:1px solid #263449;}
        QTabBar::tab:selected{background:#20334f;}
        QHeaderView::section{background:#162235;color:#bcd0ea;padding:7px;border:0;}
        """)

    def log_line(self, text):
        self.log.appendPlainText(text)
        QApplication.processEvents()

    def open_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Shabad OS SQLite", "", "SQLite (*.sqlite *.db *.sqlite3);;All Files (*)"
        )
        if path:
            self.load_source(Path(path))

    def load_source(self, path: Path):
        try:
            if self.source:
                self.source.close()
            self.source = connect_ro(path)
            self.source_path = path
            self.schema = tables(self.source)
            self.badge.setText(path.name)
            self.analyze_btn.setEnabled(True)
            self.log.clear()
            self.log_line(f"Opened READ-ONLY: {path}")
            self.analyze()
        except Exception as e:
            QMessageBox.critical(self, "Open error", str(e))

    def analyze(self):
        if not self.source:
            self.statusBar().showMessage("Open master.sqlite first.")
            return

        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("🔎 Analyzing…")
        self.statusBar().showMessage("Analyzing source schema…")
        QApplication.processEvents()

        try:
            t = set(self.schema)
            self.analysis = {"tables": self.schema}

            lines_table = "lines" if "lines" in t else None
            group_table = "line_groups" if "line_groups" in t else ("shabads" if "shabads" in t else None)
            content_table = "line_content" if "line_content" in t else ("line_data" if "line_data" in t else None)

            lc = cols(self.source, lines_table) if lines_table else []
            gc = cols(self.source, group_table) if group_table else []
            cc = cols(self.source, content_table) if content_table else []
            asset_table = "asset_lines" if "asset_lines" in t else None
            ac = cols(self.source, asset_table) if asset_table else []

            self.analysis.update({
                "lines_table": lines_table,
                "group_table": group_table,
                "content_table": content_table,
                "line_id": first_col(lc, ["id", "line_id"], False),
                "shabad_id": first_col(lc, ["shabad_id", "line_group_id", "group_id"], True),
                "source_page": first_col(lc, ["source_page", "ang", "page"], True),
                "source_line": first_col(lc, ["source_line", "line_number"], True),
                "order_id": first_col(lc, ["order_id", "sequence", "order"], True),
                "first_letters": first_col(lc, ["first_letters"], True),
                "vishraam_first_letters": first_col(lc, ["vishraam_first_letters"], True),
                "content_line_id": first_col(cc, ["line_id", "id"], False),
                "content_text": first_col(cc, ["gurmukhi", "unicode", "text", "content", "value"], True),
                "asset_table": asset_table,
                "asset_line_id": first_col(ac, ["line_id"], True),
                "asset_text": first_col(ac, ["data", "gurmukhi", "unicode", "text", "content"], True),
                "asset_type": first_col(ac, ["type"], True),
                "asset_id": first_col(ac, ["asset_id"], True),
                "asset_additional": first_col(ac, ["additional"], True),
                "group_id": first_col(gc, ["id", "shabad_id", "line_group_id"], False),
                "group_author": first_col(gc, ["author_id", "writer_id"], True),
                "group_raga": first_col(gc, ["raga_id", "raag_id"], True),
                "group_section": first_col(gc, ["section_id"], True),
            })
            self.populate_summary()
            self.populate_mapping()
            self.populate_sources()
            self.populate_structure_tables()
            self.asset_link_btn.setEnabled(True)
            # The inspected release stores authoritative Gurmukhi in asset_lines.data.
            # Run the investigation automatically so Build cannot proceed on an
            # unresolved/empty text mapping.
            self.deep_text_investigation(auto=True)
            self.tabs.setCurrentIndex(0)
            self.log_line("Schema analysis completed successfully.")
            self.statusBar().showMessage(
                f"Schema analysis complete • {len(self.schema)} tables detected"
            )
            self.tabs.setCurrentIndex(0)
        except Exception as exc:
            self.analysis = {"tables": self.schema}
            self.statusBar().showMessage("Schema analysis failed.")
            self.log_line(f"ANALYZE ERROR: {type(exc).__name__}: {exc}")
            QMessageBox.critical(
                self, "Schema analysis failed",
                f"The source could not be analyzed.\n\n{type(exc).__name__}: {exc}"
            )
        finally:
            self.analyze_btn.setText("🔎 Analyze Schema")
            self.analyze_btn.setEnabled(bool(self.source))

    def populate_summary(self):
        t = set(self.schema)
        lines = self.analysis.get("lines_table")
        groups = self.analysis.get("group_table")
        content = self.analysis.get("content_table")
        text = [
            f"Source: {self.source_path}",
            f"Read-only: YES",
            f"SQLite tables: {len(self.schema)}",
            "",
            "Detected corpus structures:",
            f"  lines:       {count(self.source, lines) if lines else 0:,}",
            f"  groups:      {count(self.source, groups) if groups else 0:,}",
            f"  line content:{count(self.source, content) if content else 0:,}",
            f"  sources:     {count(self.source, 'sources'):,}",
            f"  authors:     {count(self.source, 'authors'):,}",
            f"  ragas:       {count(self.source, 'ragas'):,}",
            f"  sections:    {count(self.source, 'sections'):,}",
            f"  asset_lines: {count(self.source, 'asset_lines') if 'asset_lines' in self.schema else 0:,}",
            "",
            "Verified text path in this release:",
            "  lines.id ← asset_lines.line_id",
            "  Gurmukhi ← asset_lines.data WHERE type='primary'",
            "  SGGS scope ← line_groups.section_id → sections.source_id='SGGS'",
            "",
            "Import principle:",
            "  master.sqlite is never modified.",
            "  A new JASS_Gurbani.db is created separately.",
            "  Original IDs are preserved.",
            "  Passages are reconstructed from shabad/group + order_id.",
            "",
            "Scope:",
            f"  {self.scope.currentText()}",
            "",
            "IMPORTANT:",
            "Sri Guru Granth Sahib auto-detection is conservative.",
            "If the release does not expose a reliable source/composition path,",
            "the builder will report that limitation instead of silently pretending",
            "that all 141k+ lines are SGGS.",
        ]
        self.summary.setPlainText("\n".join(text))

    def populate_mapping(self):
        fields = [
            ("line.id", self.analysis.get("line_id")),
            ("line.shabad_id", self.analysis.get("shabad_id")),
            ("line.source_page", self.analysis.get("source_page")),
            ("line.source_line", self.analysis.get("source_line")),
            ("line.order_id", self.analysis.get("order_id")),
            ("line.first_letters", self.analysis.get("first_letters")),
            ("line_content.line_id", self.analysis.get("content_line_id")),
            ("line_content.gurmukhi/text", self.analysis.get("content_text")),
            ("asset_lines.line_id", self.analysis.get("asset_line_id")),
            ("asset_lines.data (primary)", self.analysis.get("asset_text")),
            ("asset_lines.type", self.analysis.get("asset_type")),
            ("asset_lines.asset_id", self.analysis.get("asset_id")),
            ("asset_lines.additional", self.analysis.get("asset_additional")),
            ("group.author_id", self.analysis.get("group_author")),
            ("group.raga_id", self.analysis.get("group_raga")),
            ("group.section_id", self.analysis.get("group_section")),
        ]
        self.mapping_table.setRowCount(len(fields))
        for r, (name, detected) in enumerate(fields):
            self.mapping_table.setItem(r, 0, QTableWidgetItem(name))
            self.mapping_table.setItem(r, 1, QTableWidgetItem(str(detected or "—")))
            status = "✓ detected" if detected else "○ unavailable"
            self.mapping_table.setItem(r, 2, QTableWidgetItem(status))

    def populate_structure_tables(self):
        self.structure_table.blockSignals(True)
        self.structure_table.clear()
        self.structure_table.addItems(self.schema)
        self.structure_table.blockSignals(False)
        enabled = bool(self.source and self.schema)
        self.inspect_btn.setEnabled(enabled)
        self.text_scan_btn.setEnabled(enabled)
        self.deep_scan_btn.setEnabled(enabled)
        self.relationship_btn.setEnabled(enabled)
        if self.schema:
            preferred = "lines" if "lines" in self.schema else self.schema[0]
            self.structure_table.setCurrentText(preferred)
            self.inspect_table(preferred)

    @staticmethod
    def _gurmukhi_score(value):
        if not isinstance(value, str) or not value.strip():
            return 0.0
        chars = [c for c in value if not c.isspace()]
        if not chars:
            return 0.0
        hits = sum(1 for c in chars if "\u0a00" <= c <= "\u0a7f")
        return hits / len(chars)

    def _sample_column_stats(self, table, column, limit=50):
        try:
            rows = self.source.execute(
                f"SELECT {ident(column)} FROM {ident(table)} LIMIT ?", (limit,)
            ).fetchall()
        except Exception as exc:
            return {"nonempty": 0, "gurmukhi": 0.0, "examples": [f"ERROR: {exc}"]}
        values = [r[0] for r in rows if r[0] not in (None, "")]
        text_values = [str(v) for v in values]
        score = max((self._gurmukhi_score(v) for v in text_values), default=0.0)
        examples = []
        for v in text_values[:3]:
            one = " ".join(v.split())
            examples.append(one[:180])
        return {"nonempty": len(values), "gurmukhi": score, "examples": examples}

    def inspect_table(self, table):
        if not self.source or not table or table not in self.schema:
            return
        try:
            info = self.source.execute(f"PRAGMA table_info({ident(table)})").fetchall()
            count_rows = count(self.source, table)
            self.structure_info.setText(
                f"Table: {table}  •  Rows: {count_rows:,}  •  Columns: {len(info)}\n"
                "Samples are read-only and limited to the first 25 rows. "
                "Gurmukhi scoring is heuristic and is used only to locate likely text fields."
            )
            self.columns_table.setRowCount(len(info))
            for r, row in enumerate(info):
                cid, name, typ, notnull, default, pk = row
                stats = self._sample_column_stats(table, name)
                note = f"non-empty sample: {stats['nonempty']}; max Gurmukhi ratio: {stats['gurmukhi']:.0%}"
                if stats["examples"]:
                    note += " • " + " | ".join(stats["examples"])
                vals = [str(cid), str(name), str(typ or ""), str(pk), str(notnull), note]
                for c, val in enumerate(vals):
                    self.columns_table.setItem(r, c, QTableWidgetItem(val))

            rows = self.source.execute(f"SELECT * FROM {ident(table)} LIMIT 25").fetchall()
            headers = [str(x[1]) for x in info]
            self.sample_table.clear()
            self.sample_table.setColumnCount(len(headers))
            self.sample_table.setHorizontalHeaderLabels(headers)
            self.sample_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    txt = "" if value is None else str(value)
                    self.sample_table.setItem(r, c, QTableWidgetItem(txt[:1000]))
            self.sample_table.resizeColumnsToContents()
            for c in range(self.sample_table.columnCount()):
                if self.sample_table.columnWidth(c) > 420:
                    self.sample_table.setColumnWidth(c, 420)
            self.statusBar().showMessage(f"Inspected {table} • {count_rows:,} rows")
        except Exception as exc:
            self.log_line(f"STRUCTURE ERROR ({table}): {type(exc).__name__}: {exc}")
            QMessageBox.critical(self, "Table inspection failed", str(exc))

    def scan_text_candidates(self):
        if not self.source:
            return
        self.log_line("Scanning source columns for likely Gurmukhi/text content…")
        results = []
        for table in self.schema:
            info = self.source.execute(f"PRAGMA table_info({ident(table)})").fetchall()
            for _, name, typ, _, _, _ in info:
                stats = self._sample_column_stats(table, name, 100)
                if stats["nonempty"] == 0:
                    continue
                # Rank columns that contain Gurmukhi, then generic text columns.
                score = stats["gurmukhi"]
                if score > 0 or any(x in name.lower() for x in ("gurmukhi", "unicode", "text", "content", "bani", "line")):
                    results.append((score, table, name, typ or "", stats["nonempty"], stats["examples"]))
        results.sort(key=lambda x: (-x[0], x[1], x[2]))
        lines = ["TEXT / GURMUKHI CANDIDATE SCAN", "=" * 72, "", "Ranked from read-only samples; this does not change the source database.", ""]
        if not results:
            lines.append("No likely text columns were detected from sampled data.")
        else:
            for rank, (score, table, name, typ, nonempty, examples) in enumerate(results[:80], 1):
                lines.append(f"{rank:02d}. {table}.{name}  type={typ or '-'}  Gurmukhi={score:.0%}  nonempty={nonempty}")
                for ex in examples[:2]:
                    lines.append(f"    {ex}")
                lines.append("")
        self.log.clear()
        self.log.setPlainText("\n".join(lines))
        self.tabs.setCurrentIndex(6)
        self.log_line(f"Text candidate scan complete • {len(results)} candidates")

    @staticmethod
    def _is_probable_text(value):
        if value is None:
            return False
        if isinstance(value, (bytes, bytearray)):
            return False
        text = str(value).strip()
        return bool(text) and (len(text) >= 2 or "\u0a00" <= text[0] <= "\u0a7f")

    def _column_values(self, table, column, limit=250):
        try:
            rows = self.source.execute(
                f"SELECT {ident(column)} FROM {ident(table)} WHERE {ident(column)} IS NOT NULL LIMIT ?",
                (limit,)
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _best_line_id_column(self, table, line_ids, limit=300):
        c = cols(self.source, table)
        if not line_ids:
            return None, 0.0
        best_col = None
        best_overlap = 0.0
        for column in c:
            values = self._column_values(table, column, limit)
            if not values:
                continue
            nonempty = [str(v) for v in values if v not in (None, "")]
            if not nonempty:
                continue
            hits = sum(1 for v in nonempty if v in line_ids)
            overlap = hits / len(nonempty)
            name_bonus = any(token in column.lower() for token in ("line_id", "lineid", "line"))
            if overlap > best_overlap or (overlap == best_overlap and name_bonus):
                best_col, best_overlap = column, overlap
        return best_col, best_overlap

    def _sample_line_ids(self, limit=5000):
        table = self.analysis.get("lines_table") or "lines"
        idc = self.analysis.get("line_id")
        if not table or not idc or table not in self.schema:
            return set()
        rows = self.source.execute(
            f"SELECT {ident(idc)} FROM {ident(table)} WHERE {ident(idc)} IS NOT NULL LIMIT ?",
            (limit,)
        ).fetchall()
        return {str(r[0]) for r in rows}

    def deep_text_investigation(self, auto=False):
        """Find actual Gurmukhi-bearing source tables and test linkage to lines.id."""
        if not self.source:
            return
        self.log.clear()
        self.log_line("Starting deep text investigation (read-only)…")
        self.progress.setValue(0)
        line_ids = self._sample_line_ids()
        results = []

        for ti, table in enumerate(self.schema, 1):
            info = self.source.execute(f"PRAGMA table_info({ident(table)})").fetchall()
            row_count = count(self.source, table)
            for _, column, typ, _, _, _ in info:
                values = self._column_values(table, column, 250)
                if not values:
                    continue
                texts = [str(v) for v in values if self._is_probable_text(v)]
                if not texts:
                    continue
                scores = [self._gurmukhi_score(v) for v in texts]
                gscore = max(scores, default=0.0)
                gcount = sum(1 for x in scores if x >= 0.20)
                if gscore <= 0 and not any(x in column.lower() for x in ("gurmukhi", "bani", "text", "unicode", "content")):
                    continue

                link_col, overlap = self._best_line_id_column(table, line_ids)
                name = column.lower()
                name_bonus = 1.0 if any(x in name for x in ("gurmukhi", "unicode", "text", "content", "bani")) else 0.0
                link_bonus = 1.0 if link_col and any(x in link_col.lower() for x in ("line_id", "lineid")) else 0.0
                confidence = min(1.0, 0.55 * gscore + 0.30 * overlap + 0.10 * name_bonus + 0.05 * link_bonus)
                if gcount == 0 and gscore == 0:
                    continue
                examples = []
                for v in texts:
                    if self._gurmukhi_score(v) > 0:
                        examples.append(" ".join(v.split())[:180])
                    if len(examples) >= 3:
                        break
                results.append({
                    "table": table, "text_column": column, "link_column": link_col,
                    "gurmukhi": gscore, "overlap": overlap, "rows": row_count,
                    "confidence": confidence, "gurmukhi_hits": gcount, "examples": examples,
                    "type": typ or ""
                })
            self.progress.setValue(int(ti / max(1, len(self.schema)) * 90))
            QApplication.processEvents()

        results.sort(key=lambda r: (-r["confidence"], -r["gurmukhi"], -r["overlap"], r["table"], r["text_column"]))
        self.analysis["text_candidates"] = results
        self._populate_investigation(results, line_ids)
        self._maybe_adopt_verified_text_mapping(results)
        self.progress.setValue(100)
        if not auto:
            self.tabs.setCurrentIndex(5)
        self.log_line(f"Deep text investigation complete • {len(results)} Gurmukhi/text candidates")

    def _maybe_adopt_verified_text_mapping(self, results):
        """Adopt the verified Shabad OS asset_lines text path when its schema is present."""
        if self.analysis.get("asset_table") == "asset_lines":
            ac = set(cols(self.source, "asset_lines"))
            if {"line_id", "data", "type"}.issubset(ac):
                primary = self.source.execute(
                    "SELECT COUNT(*) FROM asset_lines WHERE type='primary' "
                    "AND data IS NOT NULL AND trim(data) <> ''"
                ).fetchone()[0]
                linked = self.source.execute(
                    "SELECT COUNT(DISTINCT a.line_id) FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                    "WHERE a.type='primary' AND a.data IS NOT NULL AND trim(a.data) <> ''"
                ).fetchone()[0]
                line_total = count(self.source, "lines")
                self.analysis["text_mapping_detail"] = (
                    f"asset_lines primary text links {linked:,} of {line_total:,} lines"
                )
                self.log_line(self.analysis["text_mapping_detail"] + ".")
                self.analysis["content_table"] = "asset_lines"
                self.analysis["content_line_id"] = "line_id"
                self.analysis["content_text"] = "data"
                self.analysis["text_mapping_status"] = "verified"
                self.analysis["text_mapping_detail"] = (
                    f"asset_lines.data (type=primary); {primary:,} non-empty primary records"
                )
                self.log_line(
                    "VERIFIED TEXT PATH: asset_lines.line_id → lines.id; "
                    f"asset_lines.data (type=primary) = {primary:,} non-empty records."
                )
                self.populate_mapping()
                return

        """Adopt only a strong line-linked candidate; otherwise leave mapping unresolved."""
        verified = [
            r for r in results
            if r["gurmukhi"] >= 0.20 and r["overlap"] >= 0.80 and r["link_column"]
        ]
        if not verified:
            self.analysis["content_table"] = None
            self.analysis["content_line_id"] = None
            self.analysis["content_text"] = None
            self.analysis["text_mapping_status"] = "unresolved"
            self.log_line("No candidate met the conservative verification threshold (Gurmukhi >= 20%, line-ID overlap >= 80%).")
            self.populate_mapping()
            return
        best = verified[0]
        self.analysis["content_table"] = best["table"]
        self.analysis["content_line_id"] = best["link_column"]
        self.analysis["content_text"] = best["text_column"]
        self.analysis["text_mapping_status"] = "verified-candidate"
        self.log_line(
            f"Verified text candidate: {best['table']}.{best['text_column']} "
            f"linked by {best['link_column']} (overlap {best['overlap']:.0%})."
        )
        self.populate_mapping()

    def _populate_investigation(self, results, line_ids):
        self.investigation_table.setRowCount(min(len(results), 100))
        for r, item in enumerate(results[:100], 1):
            vals = [
                str(r), item["table"], item["text_column"], item["link_column"] or "—",
                f"{item['gurmukhi']:.0%}", f"{item['overlap']:.0%}", f"{item['rows']:,}",
                f"{item['confidence']:.0%}"
            ]
            for c, value in enumerate(vals):
                self.investigation_table.setItem(r - 1, c, QTableWidgetItem(value))

        lines = [
            "JASS GURBANI SOURCE TEXT INVESTIGATION",
            "=" * 78,
            "",
            f"Sampled source line IDs: {len(line_ids):,}",
            f"Candidates found: {len(results):,}",
            "",
            "Verification rule:",
            "  • Gurmukhi ratio >= 20% in sampled values",
            "  • candidate link column overlaps sampled lines.id by >= 80%",
            "  • adoption is automatic only when both conditions are satisfied",
            "",
        ]
        if results:
            for rank, item in enumerate(results[:30], 1):
                lines.append(
                    f"{rank:02d}. {item['table']}.{item['text_column']}  "
                    f"link={item['link_column'] or '-'}  "
                    f"gurmukhi={item['gurmukhi']:.0%}  overlap={item['overlap']:.0%}  "
                    f"confidence={item['confidence']:.0%}"
                )
                for ex in item["examples"][:2]:
                    lines.append(f"    {ex}")
                lines.append("")
        else:
            lines.append("No Gurmukhi-bearing text candidate was detected in the sampled columns.")
        status = self.analysis.get("text_mapping_status", "not-run")
        lines += ["", f"Mapping status: {status}"]
        if status in ("verified", "verified-partial", "verified-candidate"):
            lines.append(
                f"Selected: {self.analysis.get('content_table')}.{self.analysis.get('content_text')} "
                f"via {self.analysis.get('content_line_id')}"
            )
            if self.analysis.get("text_mapping_detail"):
                lines.append(f"Detail: {self.analysis.get('text_mapping_detail')}")
        else:
            lines.append("No text mapping was adopted. The builder will not silently import empty line content.")
        self.investigation_report.setPlainText("\n".join(lines))
        self.investigation_info.setText(
            "Deep investigation examines all source tables read-only. "
            "A candidate is only adopted when its Gurmukhi content is strongly linked to sampled lines.id values."
        )

    def investigate_asset_link(self):
        """Perform an exact, read-only investigation of asset_lines -> lines linkage."""
        if not self.source or "asset_lines" not in self.schema or "lines" not in self.schema:
            self.asset_link_report.setPlainText("asset_lines and lines are both required for this investigation.")
            return

        self.log_line("Starting exact asset_lines → lines relationship investigation (read-only)…")
        try:
            ac = set(cols(self.source, "asset_lines"))
            lc = set(cols(self.source, "lines"))
            required = {"line_id", "data"}
            if not required.issubset(ac) or "id" not in lc:
                self.asset_link_report.setPlainText(
                    "Required columns are unavailable: asset_lines.line_id, asset_lines.data, or lines.id."
                )
                return

            total_assets = count(self.source, "asset_lines")
            primary = self.source.execute(
                "SELECT COUNT(*) FROM asset_lines WHERE type='primary'"
            ).fetchone()[0] if "type" in ac else 0
            primary_text = self.source.execute(
                "SELECT COUNT(*) FROM asset_lines WHERE type='primary' AND data IS NOT NULL AND trim(data) <> ''"
            ).fetchone()[0] if "type" in ac else 0
            joined = self.source.execute(
                "SELECT COUNT(*) FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                "WHERE a.type='primary' AND a.data IS NOT NULL AND trim(a.data) <> ''"
            ).fetchone()[0] if "type" in ac else self.source.execute(
                "SELECT COUNT(*) FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                "WHERE a.data IS NOT NULL AND trim(a.data) <> ''"
            ).fetchone()[0]
            distinct_linked = self.source.execute(
                "SELECT COUNT(DISTINCT a.line_id) FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                "WHERE a.type='primary' AND a.data IS NOT NULL AND trim(a.data) <> ''"
            ).fetchone()[0] if "type" in ac else 0
            lines_total = count(self.source, "lines")
            missing = self.source.execute(
                "SELECT COUNT(*) FROM lines l LEFT JOIN asset_lines a ON a.line_id=l.id "
                "AND a.type='primary' AND a.data IS NOT NULL AND trim(a.data) <> '' "
                "WHERE a.line_id IS NULL"
            ).fetchone()[0] if "type" in ac else None

            asset_ids = []
            if "asset_id" in ac:
                asset_ids = self.source.execute(
                    "SELECT COALESCE(CAST(asset_id AS TEXT),'(NULL)'), COUNT(*) "
                    "FROM asset_lines WHERE type='primary' GROUP BY asset_id ORDER BY COUNT(*) DESC"
                ).fetchall()

            if {"type", "asset_id"}.issubset(ac):
                samples = self.source.execute(
                    "SELECT a.line_id, substr(a.data,1,180), a.asset_id "
                    "FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                    "WHERE a.type='primary' AND a.data IS NOT NULL AND trim(a.data)<>'' LIMIT 10"
                ).fetchall()
            else:
                samples = self.source.execute(
                    "SELECT a.line_id, substr(a.data,1,180) "
                    "FROM asset_lines a JOIN lines l ON l.id=a.line_id "
                    "WHERE a.data IS NOT NULL AND trim(a.data)<>'' LIMIT 10"
                ).fetchall()

            lines = [
                "JASS GURBANI ASSET RELATIONSHIP INVESTIGATION",
                "=" * 78, "",
                "All measurements below are exact database queries; the source is read-only.", "",
                f"asset_lines rows:                  {total_assets:,}",
                f"primary asset_lines rows:          {primary:,}",
                f"primary rows with Gurmukhi data:  {primary_text:,}",
                f"primary text rows joined to lines: {joined:,}",
                f"distinct lines reached by primary: {distinct_linked:,}",
                f"lines rows:                         {lines_total:,}",
                f"lines without primary text link:    {missing:,}" if missing is not None else "",
                "",
            ]
            if primary_text:
                lines.append(
                    f"Primary text → lines.id coverage: {distinct_linked / lines_total:.2%}"
                    if lines_total else "Primary text → lines.id coverage: n/a"
                )
            lines += [
                "",
                "Conclusion:",
                "  asset_lines.line_id → lines.id is an exact relational link when the join reaches the distinct line count.",
                "  asset_lines.data is treated as authoritative only for rows explicitly marked type='primary'.",
                "  SGGS membership is NOT inferred here; scope is handled separately through sections.source_id.",
                "",
                "Primary asset distribution:",
            ]
            if asset_ids:
                for aid, n in asset_ids:
                    lines.append(f"  {aid}: {n:,}")
            else:
                lines.append("  asset_id/type metadata unavailable")
            lines += ["", "Verified samples:"]
            for row in samples:
                if len(row) == 3:
                    lid, txt, aid = row
                    lines.append(f"  line_id={lid}  asset_id={aid}")
                else:
                    lid, txt = row
                    lines.append(f"  line_id={lid}")
                lines.append(f"    {txt}")

            self.asset_link_report.setPlainText("\n".join(lines))
            self.asset_link_info.setText(
                "Exact relationship check completed. This distinguishes a real line-linked text asset from a merely Gurmukhi-looking table."
            )
            self.tabs.setCurrentIndex(4)
            self.log_line("Asset relationship investigation complete.")
        except Exception as exc:
            self.log_line(f"ASSET LINK ERROR: {type(exc).__name__}: {exc}")
            QMessageBox.critical(self, "Asset relationship investigation failed", str(exc))

    def scan_relationships(self):
        if not self.source:
            return
        lines = ["SOURCE RELATIONSHIP INVESTIGATION", "=" * 78, ""]
        for table in self.schema:
            try:
                fks = self.source.execute(f"PRAGMA foreign_key_list({ident(table)})").fetchall()
            except Exception:
                fks = []
            if fks:
                lines.append(f"{table} foreign keys:")
                for fk in fks:
                    lines.append(f"  {fk[3]} -> {fk[2]}.{fk[4]}")
                lines.append("")

        lines.append("Likely ID/link columns by name:")
        for table in self.schema:
            c = cols(self.source, table)
            links = [x for x in c if any(token in x.lower() for token in ("_id", "line", "group", "section", "author", "raga"))]
            if links:
                lines.append(f"  {table}: {', '.join(links)}")
        self.investigation_report.setPlainText("\n".join(lines))
        self.tabs.setCurrentIndex(5)
        self.log_line("Relationship investigation complete (read-only).")

    def _source_records(self):
        if not self.source:
            return []
        table = "sources" if "sources" in self.schema else None
        if not table:
            return []
        c = cols(self.source, table)
        idc = first_col(c, ["id"], False)
        namec = first_col(c, ["name", "title", "label"], True)
        refc = first_col(c, ["reference", "ref", "url"], True)
        if not idc:
            return []
        rows = self.source.execute(f"SELECT * FROM {ident(table)} LIMIT 500").fetchall()
        out = []
        for row in rows:
            d = dict(zip(c, row))
            out.append({
                "id": d.get(idc),
                "name": d.get(namec, "") if namec else display_name_from_row(d),
                "reference": d.get(refc, "") if refc else "",
                "raw": d
            })
        return out

    @staticmethod
    def likely_sggs(record):
        blob = json_text(record).lower()
        keys = [
            "guru granth", "sri guru granth", "sggs",
            "guru_granth", "aad granth", "granth sahib"
        ]
        return any(k in blob for k in keys)

    def populate_sources(self):
        records = self._source_records()
        if self.sggs_only.isChecked():
            records = [r for r in records if self.likely_sggs(r)]
        self.source_table.setRowCount(len(records))
        for r, rec in enumerate(records):
            self.source_table.setItem(r, 0, QTableWidgetItem(str(rec["id"])))
            self.source_table.setItem(r, 1, QTableWidgetItem(str(rec["name"] or "")))
            self.source_table.setItem(r, 2, QTableWidgetItem(str(rec["reference"] or "")))
            self.source_table.setItem(r, 3, QTableWidgetItem(json_text(rec["raw"])))

    def _generic_copy(self, target, source_table, id_candidates=("id",),
                      name_candidates=("name", "title", "label")):
        if source_table not in self.schema:
            return 0
        c = cols(self.source, source_table)
        idc = first_col(c, list(id_candidates), False)
        if not idc:
            return 0
        namec = first_col(c, list(name_candidates), True)
        rows = self.source.execute(f"SELECT * FROM {ident(source_table)}").fetchall()
        n = 0
        for row in rows:
            d = dict(zip(c, row))
            sid = str(d.get(idc))
            name = str(d.get(namec) or "") if namec else display_name_from_row(d)
            # Resolve the destination table before building the SQL string.
            # Keeping the conditional outside the f-string avoids nested-brace
            # parsing problems and makes the mapping explicit.
            if source_table == "sources":
                target_table = "sources"
                sql = (
                    f"INSERT OR REPLACE INTO {ident(target_table)} "
                    "(id,name,reference,raw_json) VALUES (?,?,?,?)"
                )
                params = (sid, name, str(d.get("reference") or ""), json_text(d))
            elif source_table in ("authors", "ragas", "sections"):
                target_table = source_table
                sql = (
                    f"INSERT OR REPLACE INTO {ident(target_table)} "
                    "(id,name,raw_json) VALUES (?,?,?)"
                )
                params = (sid, name, json_text(d))
            else:
                target_table = "authors"
                sql = (
                    f"INSERT OR REPLACE INTO {ident(target_table)} "
                    "(id,name,raw_json) VALUES (?,?,?)"
                )
                params = (sid, name, json_text(d))

            target.execute(sql, params)
            n += 1
        return n

    def _fetch_text_map(self):
        """Return line_id -> authoritative Gurmukhi text."""
        result = {}
        table = self.analysis.get("content_table")
        if not table:
            return result
        idc = self.analysis.get("content_line_id")
        textc = self.analysis.get("content_text")
        if not idc or not textc:
            return result

        if table == "asset_lines" and "type" in cols(self.source, table):
            rows = self.source.execute(
                f"SELECT {ident(idc)}, {ident(textc)} FROM {ident(table)} "
                "WHERE type='primary' AND data IS NOT NULL AND trim(data) <> ''"
            ).fetchall()
        else:
            rows = self.source.execute(
                f"SELECT {ident(idc)}, {ident(textc)} FROM {ident(table)}"
            ).fetchall()
        for row in rows:
            if row[0] is not None and row[1] not in (None, ""):
                # Keep the first non-empty representation for deterministic import.
                result.setdefault(str(row[0]), str(row[1]))
        return result

    def _fetch_asset_metadata_map(self):
        """Return line_id -> primary asset metadata such as page/line/source asset."""
        result = {}
        if self.analysis.get("content_table") != "asset_lines":
            return result
        cols_present = set(cols(self.source, "asset_lines"))
        if not {"line_id", "type"}.issubset(cols_present):
            return result
        extra = "additional" if "additional" in cols_present else None
        asset_col = "asset_id" if "asset_id" in cols_present else None
        select_cols = ["line_id"]
        if extra:
            select_cols.append(extra)
        if asset_col:
            select_cols.append(asset_col)
        rows = self.source.execute(
            "SELECT " + ", ".join(ident(c) for c in select_cols) +
            " FROM asset_lines WHERE type='primary'"
        ).fetchall()
        for row in rows:
            lid = str(row[0]) if row[0] is not None else None
            if not lid or lid in result:
                continue
            raw = {}
            if extra and row[select_cols.index(extra)] not in (None, ""):
                try:
                    raw = json.loads(row[select_cols.index(extra)])
                except Exception:
                    raw = {}
            result[lid] = {
                "page": raw.get("page"),
                "line": raw.get("line"),
                "asset_id": row[select_cols.index(asset_col)] if asset_col else None,
                "additional": raw,
            }
        return result

    def _line_rows(self):
        table = self.analysis.get("lines_table")
        if not table:
            return []
        return self.source.execute(f"SELECT * FROM {ident(table)}").fetchall()

    def _group_metadata(self):
        table = self.analysis.get("group_table")
        if not table:
            return {}
        c = cols(self.source, table)
        idc = self.analysis.get("group_id")
        if not idc:
            return {}
        out = {}
        for row in self.source.execute(f"SELECT * FROM {ident(table)}").fetchall():
            d = dict(zip(c, row))
            out[str(d.get(idc))] = d
        return out

    def _is_sggs_group(self, group):
        if not group:
            return False
        blob = json_text(group).lower()
        return self.likely_sggs(group) or "sggs" in blob

    def build_database(self):
        if not self.source:
            QMessageBox.information(self, "No source", "Open master.sqlite first.")
            return
        if self.building:
            return

        default = str(self.source_path.with_name("JASS_Gurbani.db"))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Create JASS database", default, "SQLite Database (*.db *.sqlite)"
        )
        if not out_path:
            return
        out = Path(out_path)

        if out.resolve() == self.source_path.resolve():
            QMessageBox.warning(self, "Unsafe target", "The output must be a different file.")
            return

        if out.exists():
            answer = QMessageBox.question(
                self, "Replace database?",
                f"{out.name} already exists.\nReplace it?",
                QMessageBox.Yes | QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return

        self.building = True
        self.progress.setValue(0)
        self.log.clear()
        self.tabs.setCurrentIndex(4)

        try:
            self._build(out)
            QMessageBox.information(
                self, "Build complete",
                f"JASS database created successfully:\n\n{out}\n\n"
                "The source database was not modified."
            )
        except Exception as exc:
            self.log_line(f"ERROR: {exc}")
            QMessageBox.critical(self, "Build failed", str(exc))
        finally:
            self.building = False

    def _build(self, out: Path):
        if out.exists():
            out.unlink()

        target = sqlite3.connect(out)
        target.execute("PRAGMA journal_mode=WAL")
        target.executescript(TARGET_SCHEMA)

        source_hash = sha256_file(self.source_path)
        now = datetime.now(timezone.utc).isoformat()

        scope = self.scope.currentText()
        target.execute(
            "INSERT INTO corpus VALUES (1,?,?,?,?,?,?)",
            ("JASS Gurbani Corpus", VERSION, now, str(self.source_path), source_hash, scope)
        )

        manifest = {
            "builder": APP_NAME,
            "version": VERSION,
            "created_at": now,
            "source_database": str(self.source_path),
            "source_sha256": source_hash,
            "scope": scope,
            "source_tables": self.schema,
        }
        for k, v in manifest.items():
            target.execute(
                "INSERT INTO import_manifest(key,value) VALUES (?,?)",
                (k, json_text(v) if not isinstance(v, str) else v)
            )

        self.log_line("Creating normalized JASS schema…")
        self.progress.setValue(5)

        # Copy small reference tables.
        self._copy_reference_table(target, "sources", "sources")
        self._copy_reference_table(target, "authors", "authors")
        self._copy_reference_table(target, "ragas", "ragas")
        self._copy_reference_table(target, "sections", "sections")

        self.progress.setValue(15)
        if not self.analysis.get("content_table") or not self.analysis.get("content_line_id") or not self.analysis.get("content_text"):
            raise RuntimeError(
                "Actual Gurbani text has not been verified. Run Deep Text Investigation first; "
                "the builder will not create an empty corpus."
            )

        text_map = self._fetch_text_map()
        asset_metadata = self._fetch_asset_metadata_map()
        groups = self._group_metadata()
        line_rows = self._line_rows()

        sggs_group_ids = set()
        if scope.startswith("Sri Guru"):
            if not {"line_groups", "sections"}.issubset(set(self.schema)):
                raise RuntimeError("Cannot prove Sri Guru Granth Sahib scope: line_groups/sections relationship is unavailable.")
            sggs_group_ids = {
                str(r[0]) for r in self.source.execute(
                    "SELECT g.id FROM line_groups g "
                    "JOIN sections s ON s.id=g.section_id "
                    "WHERE s.source_id='SGGS'"
                ).fetchall()
            }
            if not sggs_group_ids:
                raise RuntimeError("Sri Guru Granth Sahib scope could not be established from sections.source_id='SGGS'.")
            self.log_line(f"Verified SGGS scope: {len(sggs_group_ids):,} line groups.")
            self.log_line("SGGS scope path: lines.line_group_id → line_groups.id → sections.id → sections.source_id='SGGS'.")

        if not line_rows:
            raise RuntimeError("No usable lines table was detected.")

        lc = cols(self.source, self.analysis["lines_table"])
        idc = self.analysis.get("line_id")
        gidc = self.analysis.get("shabad_id")
        if not idc:
            raise RuntimeError("Could not identify lines.id.")
        if not gidc:
            raise RuntimeError("Could not identify lines.shabad_id / group relationship.")

        # Build line records in source order first, then deterministic passage order.
        imported = 0
        skipped = 0
        grouped = defaultdict(list)

        for idx, row in enumerate(line_rows):
            d = dict(zip(lc, row))
            lid = d.get(idc)
            gid = d.get(gidc)
            if lid in (None, "") or gid in (None, ""):
                skipped += 1
                continue

            group = groups.get(str(gid), {})
            if scope.startswith("Sri Guru") and str(gid) not in sggs_group_ids:
                skipped += 1
                continue

            lid = str(lid)
            gid = str(gid)
            page = d.get(self.analysis.get("source_page")) if self.analysis.get("source_page") else None
            src_line = d.get(self.analysis.get("source_line")) if self.analysis.get("source_line") else None
            meta = asset_metadata.get(lid, {})
            if page is None:
                page = meta.get("page")
            if src_line is None:
                src_line = meta.get("line")
            order = d.get(self.analysis.get("order_id")) if self.analysis.get("order_id") else None
            first = d.get(self.analysis.get("first_letters")) if self.analysis.get("first_letters") else None
            vfirst = d.get(self.analysis.get("vishraam_first_letters")) if self.analysis.get("vishraam_first_letters") else None

            target.execute(
                """INSERT OR REPLACE INTO lines
                   (id,shabad_id,source_page,source_line,order_id,
                    first_letters,vishraam_first_letters,pronunciation,raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (lid, gid, page, src_line, order, first, vfirst,
                 d.get("pronunciation"), json_text(d))
            )

            text = text_map.get(lid, "")
            if not text:
                # Some releases store Gurmukhi directly on lines.
                tc = first_col(lc, ["gurmukhi", "unicode", "text", "content"], True)
                if tc:
                    text = str(d.get(tc) or "")

            target.execute(
                "INSERT OR REPLACE INTO line_content(line_id,gurmukhi,content_source_id,raw_json) "
                "VALUES (?,?,?,?)",
                (lid, text, str(asset_metadata.get(lid, {}).get("asset_id") or ""),
                 json_text({"source_table": self.analysis["content_table"],
                            "asset_id": asset_metadata.get(lid, {}).get("asset_id"),
                            "additional": asset_metadata.get(lid, {}).get("additional", {})}))
            )

            grouped[gid].append({
                "id": lid, "page": page, "order": order, "text": text
            })

            target.execute(
                """INSERT INTO provenance
                   (entity_type,entity_id,source_database,source_table,source_id,source_json)
                   VALUES (?,?,?,?,?,?)""",
                ("line", lid, str(self.source_path), self.analysis["lines_table"], lid, json_text(d))
            )
            imported += 1

            if idx % 5000 == 0:
                self.progress.setValue(15 + int((idx / max(1, len(line_rows))) * 55))
                self.log_line(f"Processed {idx:,} source lines…")

        self.log_line(f"Imported lines: {imported:,}")
        self.log_line(f"Skipped lines: {skipped:,}")
        self.progress.setValue(75)

        # Shabad/group metadata and passages.
        passage_id = 1
        for gid, items in grouped.items():
            items.sort(key=lambda x: (
                x["order"] is None,
                x["order"] if x["order"] is not None else 0,
                x["id"]
            ))
            group = groups.get(gid, {})
            gc = self.analysis.get("group_table")
            author_id = group.get(self.analysis.get("group_author")) if self.analysis.get("group_author") else None
            raga_id = group.get(self.analysis.get("group_raga")) if self.analysis.get("group_raga") else None
            section_id = group.get(self.analysis.get("group_section")) if self.analysis.get("group_section") else None

            pages = [x["page"] for x in items if isinstance(x["page"], int)]
            text = "\n".join(x["text"] for x in items if x["text"])
            orders = [x["order"] for x in items if isinstance(x["order"], int)]

            target.execute(
                """INSERT OR REPLACE INTO shabads
                   (id,source_group_id,author_id,raga_id,section_id,title,
                    source_page_start,source_page_end,line_count,raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (gid, gid, str(author_id) if author_id is not None else None,
                 str(raga_id) if raga_id is not None else None,
                 str(section_id) if section_id is not None else None,
                 display_name_from_row(group), min(pages) if pages else None,
                 max(pages) if pages else None, len(items), json_text(group))
            )

            for pos, item in enumerate(items, start=1):
                target.execute(
                    "INSERT INTO passage_lines(passage_id,line_id,position) VALUES (?,?,?)",
                    (passage_id, item["id"], pos)
                )

            target.execute(
                """INSERT INTO passages
                   (id,shabad_id,line_count,first_line_order,last_line_order,
                    source_page_start,source_page_end,text)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (passage_id, gid, len(items),
                 min(orders) if orders else None,
                 max(orders) if orders else None,
                 min(pages) if pages else None,
                 max(pages) if pages else None,
                 text)
            )

            target.execute(
                """INSERT INTO provenance
                   (entity_type,entity_id,source_database,source_table,source_id,source_json)
                   VALUES (?,?,?,?,?,?)""",
                ("passage", str(passage_id), str(self.source_path),
                 self.analysis.get("group_table") or "lines", gid, json_text(group))
            )
            passage_id += 1

        target.execute("INSERT INTO import_manifest VALUES (?,?)", ("lines_imported", str(imported)))
        target.execute("INSERT INTO import_manifest VALUES (?,?)", ("lines_skipped", str(skipped)))
        target.execute("INSERT INTO import_manifest VALUES (?,?)", ("passages_created", str(passage_id - 1)))
        target.execute("INSERT INTO import_manifest VALUES (?,?)", ("content_records", str(len(text_map))))

        target.commit()
        self.progress.setValue(92)
        self.log_line(f"Created cohesive passages: {passage_id - 1:,}")

        # Final integrity / indexes.
        target.execute("PRAGMA optimize")
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Target integrity_check failed: {integrity}")
        target.commit()
        target.close()

        self.progress.setValue(100)
        self.log_line("✓ Target SQLite integrity_check: OK")
        self.log_line(f"✓ JASS database: {out}")
        self.log_line("✓ Source database remained read-only.")

    def _copy_reference_table(self, target, target_table, source_table):
        if source_table not in self.schema:
            return
        c = cols(self.source, source_table)
        idc = first_col(c, ["id"], False)
        if not idc:
            return
        namec = first_col(c, ["name", "title", "label"], True)
        refc = first_col(c, ["reference", "ref", "url"], True)
        for row in self.source.execute(f"SELECT * FROM {ident(source_table)}").fetchall():
            d = dict(zip(c, row))
            sid = str(d.get(idc))
            name = str(d.get(namec) or "") if namec else display_name_from_row(d)
            if target_table == "sources":
                target.execute(
                    "INSERT OR REPLACE INTO sources(id,name,reference,raw_json) VALUES (?,?,?,?)",
                    (sid, name, str(d.get(refc) or "") if refc else "", json_text(d))
                )
            else:
                target.execute(
                    f"INSERT OR REPLACE INTO {ident(target_table)}(id,name,raw_json) VALUES (?,?,?)",
                    (sid, name, json_text(d))
                )

    def validate_target(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Validate JASS database", "", "SQLite Database (*.db *.sqlite)"
        )
        if not path:
            return
        try:
            c = sqlite3.connect(path)
            tables_found = [
                r[0] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
            checks = {
                "corpus": c.execute("SELECT COUNT(*) FROM corpus").fetchone()[0],
                "shabads": c.execute("SELECT COUNT(*) FROM shabads").fetchone()[0],
                "lines": c.execute("SELECT COUNT(*) FROM lines").fetchone()[0],
                "line_content": c.execute("SELECT COUNT(*) FROM line_content").fetchone()[0],
                "passages": c.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
                "passage_lines": c.execute("SELECT COUNT(*) FROM passage_lines").fetchone()[0],
                "provenance": c.execute("SELECT COUNT(*) FROM provenance").fetchone()[0],
            }
            c.close()

            report = [
                "JASS_Gurbani.db VALIDATION",
                "=" * 60,
                f"File: {path}",
                f"SQLite integrity: {integrity}",
                f"Tables: {len(tables_found)}",
                "",
            ]
            for k, v in checks.items():
                report.append(f"{k:18} {v:,}")
            report += [
                "",
                "Required tables:",
            ]
            required = [
                "corpus","sources","authors","ragas","sections","shabads",
                "lines","line_content","passages","passage_lines",
                "provenance","import_manifest"
            ]
            for name in required:
                report.append(("✓ " if name in tables_found else "✗ ") + name)

            self.log.clear()
            self.log.setPlainText("\n".join(report))
            self.tabs.setCurrentIndex(6)
        except Exception as e:
            QMessageBox.critical(self, "Validation error", str(e))

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = Builder()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
