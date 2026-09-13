import sys, sqlite3, re, json
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QFont, QPainter, QLinearGradient, QColor, QPen, QBrush, QImage, QFontDatabase, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QListWidget, QListWidgetItem, QTextEdit, QSplitter,
    QFrame, QMessageBox, QFileDialog, QStackedWidget, QStatusBar, QComboBox,
    QCheckBox, QFormLayout, QSlider, QTabWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView
)

APP = "JASS Gurbani Explorer v1.0 • Canonical Corpus Workspace"
DEFAULT_DB = Path(__file__).with_name("JASS_Gurbani.db")
STATE_FILE = Path(__file__).with_name("jass_explorer_state.json")


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def tokens(s):
    return [x for x in re.findall(r"[^\s]+", str(s or "").strip()) if x]


def best_gurmukhi_font():
    families = set(QFontDatabase.families())
    for name in ("Nirmala UI", "Raavi", "Noto Sans Gurmukhi", "Noto Sans", "Segoe UI"):
        if name in families:
            return name
    return "Sans Serif"


class GurbaniDB:
    """Database adapter for the canonical JASS_Gurbani.db produced by Builder v4.6."""
    REQUIRED = {
        "corpus", "sources", "authors", "ragas", "sections", "shabads", "lines",
        "line_content", "passages", "passage_lines", "provenance", "import_manifest"
    }

    def __init__(self, path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = self.REQUIRED - self.tables
        if missing:
            self.close()
            raise RuntimeError("Not a canonical JASS database. Missing tables: " + ", ".join(sorted(missing)))
        integrity = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            self.close()
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        self._count = self.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def count(self):
        return self._count

    def corpus_info(self):
        row = self.conn.execute("SELECT * FROM corpus LIMIT 1").fetchone()
        return dict(row) if row else {}

    def manifest(self):
        return {r[0]: r[1] for r in self.conn.execute("SELECT key,value FROM import_manifest ORDER BY key")}

    def table_counts(self):
        return {
            name: self.conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in sorted(self.REQUIRED)
        }

    def _search_base(self):
        return """
            SELECT l.id, l.shabad_id, l.source_page, l.source_line, l.order_id,
                   l.first_letters, l.vishraam_first_letters,
                   lc.gurmukhi AS text,
                   s.title, s.author_id, s.raga_id, s.section_id,
                   a.name AS author_name, r.name AS raga_name,
                   sec.name AS section_name
            FROM lines l
            JOIN line_content lc ON lc.line_id=l.id
            LEFT JOIN shabads s ON s.id=l.shabad_id
            LEFT JOIN authors a ON a.id=s.author_id
            LEFT JOIN ragas r ON r.id=s.raga_id
            LEFT JOIN sections sec ON sec.id=s.section_id
        """

    def search(self, query, mode="All words", full_words=True, first_letter=False,
               limit=500, author="All", raga="All", section="All"):
        q = clean(query)
        if not q:
            return []
        terms = tokens(q)
        clauses = []
        params = []
        for term in terms:
            clauses.append("lc.gurmukhi LIKE ?")
            params.append("%" + term + "%")
        joiner = " OR " if mode == "Any word" else " AND "
        sql = self._search_base() + " WHERE " + joiner.join(clauses)
        if author != "All":
            sql += " AND a.name=?"
            params.append(author)
        if raga != "All":
            sql += " AND r.name=?"
            params.append(raga)
        if section != "All":
            sql += " AND sec.name=?"
            params.append(section)
        sql += " ORDER BY l.shabad_id, l.order_id, l.id LIMIT ?"
        params.append(max(limit * 8, limit))

        candidates = self.conn.execute(sql, params).fetchall()
        scored = []
        for row in candidates:
            text = clean(row["text"])
            words = tokens(text)
            if first_letter:
                ok = [any(w.startswith(term[:1]) for w in words) for term in terms]
            elif full_words:
                wordset = set(words)
                ok = [term in wordset for term in terms]
            else:
                ok = [term in text for term in terms]
            if (all(ok) if mode == "All words" else any(ok)):
                score = sum(text.count(term) for term in terms)
                scored.append((score, row))
        scored.sort(key=lambda x: (
            -x[0], str(x[1]["shabad_id"]),
            x[1]["order_id"] if x[1]["order_id"] is not None else 10**9,
            str(x[1]["id"])
        ))
        return [row for _, row in scored[:limit]]

    def get_line(self, line_id):
        return self.conn.execute(self._search_base() + " WHERE l.id=?", (line_id,)).fetchone()

    def get_passage_for_line(self, line_id):
        return self.conn.execute("""
            SELECT p.*
            FROM passages p
            JOIN passage_lines pl ON pl.passage_id=p.id
            WHERE pl.line_id=?
            ORDER BY p.id
            LIMIT 1
        """, (line_id,)).fetchone()

    def passage_lines(self, passage_id):
        return self.conn.execute("""
            SELECT l.id, l.shabad_id, l.source_page, l.source_line, l.order_id,
                   lc.gurmukhi AS text, pl.position
            FROM passage_lines pl
            JOIN lines l ON l.id=pl.line_id
            JOIN line_content lc ON lc.line_id=l.id
            WHERE pl.passage_id=?
            ORDER BY pl.position, l.order_id, l.id
        """, (passage_id,)).fetchall()

    def passage_bundle(self, line_id):
        passage = self.get_passage_for_line(line_id)
        if passage:
            return passage, self.passage_lines(passage["id"])
        line = self.get_line(line_id)
        return None, [line] if line else []

    def random_lines(self, n=100):
        return self.conn.execute(self._search_base() + " ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()

    def distinct(self, field):
        exprs = {"author": "a.name", "raga": "r.name", "section": "sec.name"}
        expr = exprs.get(field)
        if not expr:
            return []
        return [r[0] for r in self.conn.execute(
            self._search_base() +
            f" WHERE {expr} IS NOT NULL AND TRIM({expr})<>'' GROUP BY {expr} ORDER BY {expr}"
        )]


class CardPreview(QWidget):
    THEMES = {
        "Midnight Gold": ("#080b12", "#29364d", "#d9b86c", "#ffffff"),
        "Saffron Dawn": ("#2a1208", "#7d421e", "#f5ca73", "#fff9ef"),
        "Amrit Glow": ("#061919", "#145b58", "#b7eee4", "#f7ffff"),
        "Royal Indigo": ("#0a0d2b", "#30346e", "#c9cdff", "#ffffff"),
        "Lotus Night": ("#210b1e", "#71355e", "#f1abd0", "#fff8fc"),
        "Forest Serenity": ("#07170f", "#255d3d", "#b9dfb4", "#f8fff7"),
        "Paper & Ink": ("#f5efe1", "#e5dac2", "#8a5b27", "#1e1a15"),
    }
    RATIOS = {"4:5": (1080, 1350), "1:1": (1080, 1080), "9:16": (1080, 1920)}

    def __init__(self):
        super().__init__()
        self.text = "ੴ"
        self.title = ""
        self.footer = ""
        self.watermark = "JASS GURBANI"
        self.theme = "Midnight Gold"
        self.font_size = 34
        self.ratio = "4:5"
        self.show_watermark = True
        self.font_name = best_gurmukhi_font()
        self.image = QImage()
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(360, 420)
        self.label.setStyleSheet("border:none;background:transparent")
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)

    def set_content(self, text, title="", footer=""):
        self.text = text or "ੴ"
        self.title = title or ""
        self.footer = footer or ""
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_image()

    def show_image(self):
        if self.image.isNull():
            return
        from PySide6.QtGui import QPixmap
        pix = QPixmap.fromImage(self.image).scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pix)

    def render(self, width, height):
        bg1, bg2, accent, fg = self.THEMES.get(self.theme, self.THEMES["Midnight Gold"])
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(bg1))
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            rect = QRectF(12, 12, width - 24, height - 24)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor(bg1)); gradient.setColorAt(.5, QColor(bg2)); gradient.setColorAt(1, QColor(bg1))
            painter.setBrush(QBrush(gradient)); painter.setPen(Qt.NoPen); painter.drawRoundedRect(rect, 28, 28)
            c = QColor(accent); c.setAlpha(55); painter.setPen(QPen(c, max(2, width // 540)))
            for inset in (28, 46, 64):
                painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), 18, 18)
            painter.setPen(QColor(accent)); painter.setFont(QFont("Segoe UI Symbol", max(24, width // 38), QFont.Bold))
            painter.drawText(QRectF(35, 28, width - 70, 55), Qt.AlignCenter, "ੴ")
            if self.title:
                painter.setFont(QFont("Segoe UI", max(12, int(self.font_size * .48)), QFont.DemiBold))
                painter.drawText(QRectF(50, 88, width - 100, 48), Qt.AlignCenter, self.title)
            top = 145 if self.title else 120
            bottom = 145 if (self.footer or (self.show_watermark and self.watermark)) else 75
            text_rect = rect.adjusted(90, top, -55, -bottom)  # extra left breathing room for Gurbani text
            doc = QTextDocument(); doc.setDocumentMargin(0); doc.setDefaultFont(QFont(self.font_name, max(18, int(self.font_size * width / 1080)), QFont.Medium)); doc.setTextWidth(text_rect.width()); doc.setPlainText(self.text)
            painter.save(); painter.translate(text_rect.left(), text_rect.top()); painter.setPen(QColor(fg)); doc.drawContents(painter, QRectF(0, 0, text_rect.width(), text_rect.height())); painter.restore()
            if self.footer:
                painter.setPen(QColor(accent)); painter.setFont(QFont("Segoe UI", max(9, int(10 * width / 1080)), QFont.DemiBold)); painter.drawText(QRectF(40, height - 112, width - 80, 28), Qt.AlignCenter, self.footer)
            if self.show_watermark and self.watermark:
                c = QColor(fg); c.setAlpha(150); painter.setPen(c); painter.setFont(QFont("Segoe UI", max(8, int(9 * width / 1080)), QFont.DemiBold)); painter.drawText(QRectF(35, height - 55, width - 70, 28), Qt.AlignCenter, self.watermark)
        finally:
            painter.end()
        return image

    def refresh(self):
        self.image = self.render(*self.RATIOS.get(self.ratio, self.RATIOS["4:5"])); self.show_image()

    def save_png(self, path):
        return self.render(*self.RATIOS.get(self.ratio, self.RATIOS["4:5"])).save(str(path), "PNG")


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP); self.resize(1680, 1000)
        self.db = None; self.results = []; self.current = None; self.current_passage = ""; self.random_rows = []
        self.favorites = set(); self.history = []; self.dark = True
        self.load_state(); self.build_ui(); self.apply_style()
        if DEFAULT_DB.exists(): self.open_db(DEFAULT_DB, quiet=True)

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root); outer = QVBoxLayout(root); outer.setContentsMargins(18, 14, 18, 12)
        head = QHBoxLayout(); hv = QVBoxLayout(); title = QLabel("ੴ  JASS GURBANI"); title.setObjectName("title"); sub = QLabel("SEARCH  •  PASSAGE READER  •  RESEARCH  •  CARD STUDIO"); sub.setObjectName("subtitle"); hv.addWidget(title); hv.addWidget(sub); head.addLayout(hv); head.addStretch(); self.badge = QLabel("DATABASE • —"); self.badge.setObjectName("badge"); head.addWidget(self.badge); outer.addLayout(head)
        self.stack = QStackedWidget(); self.stack.addWidget(self.search_page()); self.stack.addWidget(self.reader_page()); self.stack.addWidget(self.card_page()); self.stack.addWidget(self.random_page()); self.stack.addWidget(self.favorites_page()); self.stack.addWidget(self.research_page())
        nav = QFrame(); nav.setObjectName("nav"); nv = QVBoxLayout(nav)
        for label, idx in [("⌕  Search",0),("▤  Reader",1),("▣  Card Studio",2),("✦  Random",3),("♥  Favorites",4),("◈  Research",5)]:
            b = QPushButton(label); b.clicked.connect(lambda _, i=idx: self.stack.setCurrentIndex(i)); nv.addWidget(b)
        nv.addStretch(); op = QPushButton("Open Database"); op.clicked.connect(self.choose_db); nv.addWidget(op); theme = QPushButton("☾  Toggle Theme"); theme.clicked.connect(self.toggle_theme); nv.addWidget(theme)
        row = QHBoxLayout(); row.addWidget(nav); row.addWidget(self.stack, 1); outer.addLayout(row, 1); self.setStatusBar(QStatusBar())

    def search_page(self):
        page = QWidget(); lay = QVBoxLayout(page); bar = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Type a Gurmukhi word or phrase…"); self.search.setMinimumHeight(50); self.search.returnPressed.connect(self.do_search); bar.addWidget(self.search, 1); b = QPushButton("🔎 SEARCH"); b.clicked.connect(self.do_search); bar.addWidget(b); c = QPushButton("Clear"); c.clicked.connect(self.clear_search); bar.addWidget(c); lay.addLayout(bar)
        tool = QFrame(); tool.setObjectName("toolbar"); tv = QHBoxLayout(tool); tv.addWidget(QLabel("Match")); self.mode = QComboBox(); self.mode.addItems(["All words", "Any word"]); tv.addWidget(self.mode); self.full = QCheckBox("Full word(s)"); self.full.setChecked(True); tv.addWidget(self.full); self.first = QCheckBox("First letter"); tv.addWidget(self.first); tv.addWidget(QLabel("Author")); self.author = QComboBox(); tv.addWidget(self.author); tv.addWidget(QLabel("Raag")); self.raga = QComboBox(); tv.addWidget(self.raga); tv.addWidget(QLabel("Section")); self.section = QComboBox(); tv.addWidget(self.section); tv.addStretch(); lay.addWidget(tool)
        self.info = QLabel("Search the canonical line_content table. Results resolve to complete passages."); self.info.setObjectName("muted"); lay.addWidget(self.info)
        split = QSplitter(Qt.Horizontal); self.list = QListWidget(); self.list.currentRowChanged.connect(self.select_result); split.addWidget(self.list)
        panel = QFrame(); panel.setObjectName("panel"); pv = QVBoxLayout(panel); self.meta = QLabel("Select a search result"); self.meta.setObjectName("muted"); pv.addWidget(self.meta); self.reader = QTextEdit(); self.reader.setReadOnly(True); self.reader.setFont(QFont(best_gurmukhi_font(), 28)); pv.addWidget(self.reader, 1); acts = QHBoxLayout()
        for label, fn in [("♥ Favorite", self.favorite_current),("▤ Open Reader", self.open_reader),("✦ Create Card", self.use_current_for_card),("📋 Copy", self.copy_passage),("💾 Export TXT", self.export_passage),("◀ Prev", self.prev_result),("Next ▶", self.next_result)]:
            x = QPushButton(label); x.clicked.connect(fn); acts.addWidget(x)
        pv.addLayout(acts); split.addWidget(panel); split.setSizes([620, 1000]); lay.addWidget(split, 1); return page

    def reader_page(self):
        page = QWidget(); lay = QVBoxLayout(page); h = QHBoxLayout(); x = QLabel("▤  PASSAGE READER"); x.setObjectName("panelTitle"); h.addWidget(x); h.addStretch(); self.reader_title = QLabel("No passage selected"); self.reader_title.setObjectName("muted"); h.addWidget(self.reader_title); lay.addLayout(h); self.big_reader = QTextEdit(); self.big_reader.setReadOnly(True); self.big_reader.setFont(QFont(best_gurmukhi_font(), 34)); lay.addWidget(self.big_reader, 1); a = QHBoxLayout()
        for label, fn in [("♥ Favorite", self.favorite_current),("✦ Card Studio", self.use_current_for_card),("📋 Copy Passage", self.copy_passage),("💾 Export TXT", self.export_passage)]: b = QPushButton(label); b.clicked.connect(fn); a.addWidget(b)
        a.addStretch(); lay.addLayout(a); return page

    def card_page(self):
        page = QWidget(); lay = QHBoxLayout(page); left = QFrame(); left.setObjectName("panel"); lv = QVBoxLayout(left); t = QLabel("CARD STUDIO"); t.setObjectName("panelTitle"); lv.addWidget(t); self.card_text = QTextEdit(); self.card_text.setPlaceholderText("Select a passage or paste Gurmukhi Gurbani here…"); lv.addWidget(self.card_text, 1); form = QFormLayout(); self.design = QComboBox(); self.design.addItems(CardPreview.THEMES); form.addRow("Design", self.design); self.ratio = QComboBox(); self.ratio.addItems(CardPreview.RATIOS); form.addRow("Size", self.ratio); self.card_font = QSlider(Qt.Horizontal); self.card_font.setRange(20, 60); self.card_font.setValue(34); form.addRow("Text size", self.card_font); self.card_title = QLineEdit(); form.addRow("Title", self.card_title); self.card_footer = QLineEdit(); form.addRow("Footer", self.card_footer); self.card_water = QLineEdit("JASS GURBANI"); form.addRow("Watermark", self.card_water); self.water_on = QCheckBox("Show watermark"); self.water_on.setChecked(True); form.addRow("", self.water_on); lv.addLayout(form); ar = QHBoxLayout(); ex = QPushButton("🖼 Export PNG"); ex.clicked.connect(self.export_card); ar.addWidget(ex); rf = QPushButton("↻ Refresh"); rf.clicked.connect(self.update_card); ar.addWidget(rf); cl = QPushButton("Clear"); cl.clicked.connect(lambda: self.card_text.clear()); ar.addWidget(cl); lv.addLayout(ar); lay.addWidget(left, 1); right = QFrame(); right.setObjectName("panel"); rv = QVBoxLayout(right); p = QLabel("LIVE PREVIEW"); p.setObjectName("panelTitle"); rv.addWidget(p); self.canvas = CardPreview(); rv.addWidget(self.canvas, 1); lay.addWidget(right, 1)
        for w in (self.card_text, self.card_title, self.card_footer, self.card_water): w.textChanged.connect(self.update_card)
        for w in (self.design, self.ratio): w.currentTextChanged.connect(self.update_card)
        self.card_font.valueChanged.connect(self.update_card); self.water_on.stateChanged.connect(self.update_card); return page

    def random_page(self):
        page = QWidget(); lay = QVBoxLayout(page); h = QHBoxLayout(); x = QLabel("✦  RANDOM DISCOVERY"); x.setObjectName("panelTitle"); h.addWidget(x); h.addStretch(); b = QPushButton("New Selection"); b.clicked.connect(self.load_random); h.addWidget(b); lay.addLayout(h); self.random_list = QListWidget(); self.random_list.currentRowChanged.connect(self.select_random); lay.addWidget(self.random_list, 1); return page

    def favorites_page(self):
        page = QWidget(); lay = QVBoxLayout(page); h = QHBoxLayout(); x = QLabel("♥  FAVORITES"); x.setObjectName("panelTitle"); h.addWidget(x); h.addStretch(); b = QPushButton("Refresh"); b.clicked.connect(self.refresh_favorites); h.addWidget(b); lay.addLayout(h); self.fav_list = QListWidget(); self.fav_list.currentRowChanged.connect(self.select_favorite); lay.addWidget(self.fav_list, 1); return page

    def research_page(self):
        page = QWidget(); lay = QVBoxLayout(page); h = QHBoxLayout(); x = QLabel("◈  RESEARCH & DATABASE"); x.setObjectName("panelTitle"); h.addWidget(x); h.addStretch(); b = QPushButton("Refresh Statistics"); b.clicked.connect(self.refresh_research); h.addWidget(b); lay.addLayout(h); tabs = QTabWidget(); self.stats_text = QTextEdit(); self.stats_text.setReadOnly(True); tabs.addTab(self.stats_text, "Statistics"); self.manifest_text = QTextEdit(); self.manifest_text.setReadOnly(True); tabs.addTab(self.manifest_text, "Import Manifest"); self.struct_table = QTableWidget(); self.struct_table.setEditTriggers(QAbstractItemView.NoEditTriggers); tabs.addTab(self.struct_table, "Structure"); lay.addWidget(tabs, 1); return page

    def open_db(self, path, quiet=False):
        try:
            if self.db: self.db.close()
            self.db = GurbaniDB(path); self.badge.setText(f"DATABASE • {self.db.path.name} • {self.db.count():,} lines"); self.statusBar().showMessage(f"Loaded canonical JASS database • {self.db.count():,} lines", 4000); self.populate_filters(); self.load_random(); self.refresh_favorites(); self.refresh_research()
            if not quiet: QMessageBox.information(self, "Database opened", f"Canonical JASS database loaded.\n\n{path}\n\n{self.db.count():,} lines available.")
        except Exception as e:
            if not quiet: QMessageBox.critical(self, "Database error", str(e))
            else: self.statusBar().showMessage(f"Database not loaded: {e}", 5000)

    def choose_db(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open JASS Gurbani Database", str(Path.home()), "SQLite Database (*.db *.sqlite *.sqlite3)")
        if p: self.open_db(p)

    def populate_filters(self):
        for combo, field in ((self.author, "author"), (self.raga, "raga"), (self.section, "section")):
            combo.blockSignals(True); combo.clear(); combo.addItem("All")
            try: combo.addItems(self.db.distinct(field))
            finally: combo.blockSignals(False)

    def do_search(self):
        if not self.db: return
        q = self.search.text().strip()
        if not q: self.info.setText("Enter a Gurmukhi word or phrase."); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.results = self.db.search(q, self.mode.currentText(), self.full.isChecked(), self.first.isChecked(), 500, self.author.currentText(), self.raga.currentText(), self.section.currentText())
        except Exception as e:
            QMessageBox.critical(self, "Search error", str(e)); return
        finally:
            QApplication.restoreOverrideCursor()
        self.list.clear()
        for r in self.results:
            it = QListWidgetItem(f"#{r['id']}  •  {r['title'] or 'Shabad'}\n{clean(r['text'])[:240]}"); it.setData(Qt.UserRole, str(r['id'])); self.list.addItem(it)
        self.info.setText(f"{len(self.results):,} result(s) • canonical line search • passage-aware")
        if self.results: self.list.setCurrentRow(0)

    def select_result(self, index):
        if 0 <= index < len(self.results): self.show_line(self.results[index])

    def show_line(self, row):
        self.current = row; line_id = str(row["id"]); passage, lines = self.db.passage_bundle(line_id); blocks = [clean(x["text"]) for x in lines if x and clean(x["text"])]; self.current_passage = "\n".join(blocks); self.reader.setPlainText(self.current_passage); self.big_reader.setPlainText(self.current_passage); self.reader_title.setText(f"Passage {passage['id'] if passage else '—'} • {len(lines)} lines")
        parts = [f"Line {line_id}", f"Shabad {row['shabad_id']}"]
        if passage: parts += [f"Passage {passage['id']}", f"{passage['line_count']} lines"]
        if row["source_page"] is not None: parts.append(f"Ang {row['source_page']}")
        for key, label in (("raga_name", "Raag"), ("author_name", "Author"), ("section_name", "Section")):
            if row[key]: parts.append(f"{label}: {row[key]}")
        self.meta.setText("  •  ".join(parts)); self.history = [line_id] + [x for x in self.history if x != line_id]; self.history = self.history[:100]

    def open_reader(self): self.stack.setCurrentIndex(1)
    def prev_result(self): self.list.setCurrentRow(max(0, self.list.currentRow() - 1))
    def next_result(self): self.list.setCurrentRow(min(self.list.count() - 1, self.list.currentRow() + 1))

    def favorite_current(self):
        if not self.current: return
        line_id = str(self.current["id"])
        if line_id in self.favorites: self.favorites.remove(line_id); msg = "Removed from favorites"
        else: self.favorites.add(line_id); msg = "Added to favorites"
        self.save_state(); self.refresh_favorites(); self.statusBar().showMessage(msg, 1800)

    def refresh_favorites(self):
        if not hasattr(self, "fav_list") or not self.db: return
        self.fav_list.clear()
        for line_id in sorted(self.favorites):
            row = self.db.get_line(line_id)
            if row: self.fav_list.addItem(f"{line_id}  •  {clean(row['text'])[:230]}")

    def select_favorite(self, index):
        ids = sorted(self.favorites)
        if self.db and 0 <= index < len(ids): self.show_line(self.db.get_line(ids[index])); self.stack.setCurrentIndex(1)

    def use_current_for_card(self):
        if not self.current: return
        self.stack.setCurrentIndex(2); self.card_text.setPlainText(self.current_passage or clean(self.current["text"])); footer = []
        if self.current["source_page"] is not None: footer.append(f"Ang {self.current['source_page']}")
        if self.current["raga_name"]: footer.append(self.current["raga_name"])
        if self.current["author_name"]: footer.append(self.current["author_name"])
        self.card_footer.setText("  •  ".join(footer)); self.update_card()

    def update_card(self, *args):
        if not hasattr(self, "canvas"): return
        self.canvas.theme = self.design.currentText(); self.canvas.ratio = self.ratio.currentText(); self.canvas.font_size = self.card_font.value(); self.canvas.title = self.card_title.text(); self.canvas.footer = self.card_footer.text(); self.canvas.watermark = self.card_water.text(); self.canvas.show_watermark = self.water_on.isChecked(); self.canvas.set_content(self.card_text.toPlainText(), self.card_title.text(), self.card_footer.text())

    def export_card(self):
        if not self.card_text.toPlainText().strip(): QMessageBox.information(self, "Empty card", "Select or enter Gurbani first."); return
        p, _ = QFileDialog.getSaveFileName(self, "Export Gurbani Card", str(Path.home() / "gurbani_card.png"), "PNG Image (*.png)")
        if p and self.canvas.save_png(p): self.statusBar().showMessage(f"Exported {p}", 3000)

    def copy_passage(self):
        if self.current_passage: QApplication.clipboard().setText(self.current_passage); self.statusBar().showMessage("Passage copied", 1500)

    def export_passage(self):
        if not self.current_passage: return
        p, _ = QFileDialog.getSaveFileName(self, "Export Gurbani Passage", str(Path.home() / "gurbani_passage.txt"), "Text (*.txt)")
        if p: Path(p).write_text(self.current_passage, encoding="utf-8"); self.statusBar().showMessage(f"Exported {p}", 2500)

    def load_random(self):
        if not self.db: return
        self.random_rows = self.db.random_lines(100)
        if hasattr(self, "random_list"):
            self.random_list.clear()
            for r in self.random_rows: self.random_list.addItem(f"#{r['id']}  •  {r['title'] or 'Shabad'}\n{clean(r['text'])[:240]}")
            if self.random_rows: self.random_list.setCurrentRow(0)

    def select_random(self, index):
        if 0 <= index < len(self.random_rows): self.show_line(self.random_rows[index]); self.stack.setCurrentIndex(1)

    def refresh_research(self):
        if not self.db or not hasattr(self, "stats_text"): return
        info = self.db.corpus_info(); counts = self.db.table_counts(); manifest = self.db.manifest(); lines = ["JASS GURBANI DATABASE", "=" * 60, f"File: {self.db.path}", "SQLite integrity: OK", "", "Corpus:"]
        for key, value in info.items(): lines.append(f"{key:20} {value}")
        lines += ["", "Table counts:"] + [f"{key:20} {value:,}" for key, value in counts.items()]; self.stats_text.setPlainText("\n".join(lines)); self.manifest_text.setPlainText("\n".join(f"{key}\n{value}\n" for key, value in manifest.items()))
        self.struct_table.setRowCount(0); self.struct_table.setColumnCount(2); self.struct_table.setHorizontalHeaderLabels(["Table", "Rows"]); self.struct_table.setRowCount(len(counts))
        for i, (key, value) in enumerate(counts.items()): self.struct_table.setItem(i, 0, QTableWidgetItem(key)); self.struct_table.setItem(i, 1, QTableWidgetItem(f"{value:,}"))
        self.struct_table.resizeColumnsToContents()

    def clear_search(self): self.search.clear(); self.results = []; self.list.clear(); self.reader.clear(); self.big_reader.clear(); self.meta.setText("Select a search result"); self.info.setText("Search cleared.")

    def load_state(self):
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8")); self.favorites = set(map(str, data.get("favorites", []))); self.history = list(map(str, data.get("history", [])))
        except Exception: self.favorites = set(); self.history = []

    def save_state(self):
        try: STATE_FILE.write_text(json.dumps({"favorites": sorted(self.favorites), "history": self.history}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception: pass

    def toggle_theme(self): self.dark = not self.dark; self.apply_style()

    def apply_style(self):
        if self.dark: bg, panel, field, text, muted, border, accent = "#080c12", "#151b24", "#10151d", "#eef2f7", "#929dac", "#2a3442", "#788fff"
        else: bg, panel, field, text, muted, border, accent = "#eef2f7", "#ffffff", "#f8fafc", "#17202c", "#617080", "#d5dce6", "#526ad7"
        self.setStyleSheet(f'''QWidget{{background:{bg};color:{text};font-family:"Segoe UI"}} QLabel#title{{font-size:31px;font-weight:850}} QLabel#subtitle,QLabel#muted{{color:{muted}}} QLabel#badge{{background:{panel};border:1px solid {border};border-radius:12px;padding:9px 14px;color:{muted}}} QFrame#nav,QFrame#panel{{background:{panel};border:1px solid {border};border-radius:16px}} QFrame#toolbar{{background:{panel};border:1px solid {border};border-radius:12px}} QLabel#panelTitle{{color:{muted};font-weight:800}} QLineEdit,QTextEdit,QComboBox{{background:{field};color:{text};border:1px solid {border};border-radius:10px;padding:9px}} QLineEdit:focus,QTextEdit:focus{{border:2px solid {accent}}} QPushButton{{background:{panel};color:{text};border:1px solid {border};border-radius:10px;padding:10px 13px;font-weight:650}} QPushButton:hover{{border-color:{accent}}} QListWidget{{background:{field};border:none}} QListWidget::item{{background:{panel};border:1px solid {border};border-radius:10px;padding:10px;margin:2px}} QListWidget::item:selected{{background:{field};border:1px solid {accent}}} QCheckBox{{color:{text}}} QStatusBar{{background:{bg};color:{muted}}} QSlider::groove:horizontal{{height:6px;background:{border};border-radius:3px}} QSlider::handle:horizontal{{width:16px;margin:-5px 0;border-radius:8px;background:{accent}}} QTabWidget::pane{{border:1px solid {border}}} QHeaderView::section{{background:{panel};color:{text};padding:6px}}''')

    def closeEvent(self, event):
        self.save_state()
        if self.db: self.db.close()
        event.accept()


def main():
    app = QApplication(sys.argv); app.setApplicationName(APP); window = Main(); window.show(); sys.exit(app.exec())


if __name__ == "__main__":
    main()
