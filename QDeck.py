import sys, os, json
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap, QShortcut, QKeySequence
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QComboBox, QLabel, QStackedLayout, QHeaderView)

COLS = ["Arm", "Type", "Name", "File", "Pre-wait (s)", "Duration (s)", "Post-wait (s)", "Continue"]
CONT = ["Do not continue", "Auto-continue", "Auto-follow"]
NUM = {4: "pre", 5: "dur", 6: "post"}
VIDEO = (".mp4", ".mov", ".avi", ".wmv", ".mkv", ".m4v")
IMAGE = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
STYLE = """QMainWindow,QWidget{background:#222;color:#eee}
QTableWidget{background:#2b2b2b;gridline-color:#3a3a3a;selection-background-color:#2f6fd0}
QHeaderView::section{background:#333;color:#ccc;padding:4px;border:0}
QPushButton{background:#444;padding:6px 10px;border-radius:4px}
QPushButton:hover{background:#555}
QComboBox{background:#444;padding:5px}"""


class Output(QWidget):
    """Full-screen window for the beamer: black, shows one video or image at a time."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background:black")
        self.video = QVideoWidget()
        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setMinimumSize(1, 1)
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        for w in (QWidget(), self.video, self.image):
            self.stack.addWidget(w)
        self.current, self.pm = None, None

    def blank(self):
        self.current = None
        self.stack.setCurrentIndex(0)

    def show_video(self):
        self.current = "video"
        self.stack.setCurrentIndex(1)

    def show_image(self, path):
        self.current, self.pm = path, QPixmap(path)
        self.stack.setCurrentIndex(2)
        self.fit()

    def fit(self):
        if self.pm and self.current not in (None, "video"):
            self.image.setPixmap(self.pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def place(self, screen):
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QDeck")
        self.setStyleSheet(STYLE)
        self.cues, self.playing, self.gen = [], [], 0
        self.out = Output()

        go = QPushButton("GO")
        go.setMinimumSize(130, 70)
        go.setStyleSheet("font-size:34px;font-weight:bold;background:#555")
        go.clicked.connect(lambda _=False: self.go())

        self.scr = QComboBox()
        self.scr.addItem("Output: off")
        for i, s in enumerate(QApplication.screens()):
            g = s.geometry()
            self.scr.addItem(f"Output: screen {i + 1} ({g.width()}x{g.height()})")
        self.scr.currentIndexChanged.connect(self.set_output)

        bar = QHBoxLayout()
        bar.addWidget(go)
        for text, fn in [("Add media…", self.add_media), ("Add Stop-all", self.add_stop),
                         ("Up", lambda: self.move(-1)), ("Down", lambda: self.move(1)),
                         ("Delete", self.delete), ("Stop all (Esc)", self.stop_all),
                         ("Open…", self.load), ("Save…", self.save)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
        bar.addWidget(self.scr)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemChanged.connect(self.changed)
        self.table.cellDoubleClicked.connect(self.dbl)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addLayout(bar)
        lay.addWidget(self.table)
        self.setCentralWidget(root)

        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.go)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.stop_all)
        self.scr.setCurrentIndex(self.scr.count() - 1)  # last screen = beamer

    # ---------- output ----------
    def set_output(self, i):
        if i == 0:
            self.out.hide()
        elif len(QApplication.screens()) == 1:
            self.out.setGeometry(60, 60, 640, 360)  # only one screen: small preview window
            self.out.show()
        else:
            self.out.place(QApplication.screens()[i - 1])

    # ---------- cue list editing ----------
    def new_cue(self, typ, path=""):
        return {"type": typ, "name": os.path.splitext(os.path.basename(path))[0] or typ,
                "file": path, "pre": 0.0, "dur": 0.0, "post": 0.0, "cont": CONT[0], "armed": True}

    def add_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add media")
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            self.cues.append(self.new_cue("Video" if ext in VIDEO else "Image" if ext in IMAGE else "Audio", f))
        self.refresh(len(self.cues) - 1)

    def add_stop(self):
        self.cues.append(self.new_cue("Stop all"))
        self.refresh(len(self.cues) - 1)

    def move(self, d):
        r, s = self.table.currentRow(), self.table.currentRow() + d
        if 0 <= r < len(self.cues) and 0 <= s < len(self.cues):
            self.cues[r], self.cues[s] = self.cues[s], self.cues[r]
            self.refresh(s)

    def delete(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.cues):
            del self.cues[r]
            self.refresh(min(r, len(self.cues) - 1))

    def refresh(self, row=None):
        t = self.table
        t.blockSignals(True)
        t.setRowCount(len(self.cues))
        for r, c in enumerate(self.cues):
            vals = ["", c["type"], c["name"], os.path.basename(c["file"]), c["pre"], c["dur"], c["post"], c["cont"]]
            for k, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if k == 0:
                    it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    it.setCheckState(Qt.Checked if c["armed"] else Qt.Unchecked)
                elif k in (1, 3, 7):
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                t.setItem(r, k, it)
        t.blockSignals(False)
        if row is not None and 0 <= row < len(self.cues):
            t.selectRow(row)

    def changed(self, it):
        r, k = it.row(), it.column()
        c = self.cues[r]
        if k == 0:
            c["armed"] = it.checkState() == Qt.Checked
        elif k == 2:
            c["name"] = it.text()
        elif k in NUM:
            try:
                c[NUM[k]] = max(0.0, float(it.text().replace(",", ".")))
            except ValueError:
                pass
            self.refresh(r)

    def dbl(self, r, k):
        c = self.cues[r]
        if k == 7:
            c["cont"] = CONT[(CONT.index(c["cont"]) + 1) % len(CONT)]
        elif k == 3 and c["type"] != "Stop all":
            f, _ = QFileDialog.getOpenFileName(self, "Choose file")
            if f:
                c["file"] = f
        else:
            return
        self.refresh(r)

    def save(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save show", "", "QDeck show (*.json)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.cues, f, indent=1)

    def load(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open show", "", "QDeck show (*.json)")
        if p:
            self.stop_all()
            with open(p, encoding="utf-8") as f:
                self.cues = json.load(f)
            self.refresh(0)

    # ---------- playback ----------
    def go(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.cues):
            self.fire(r)

    def fire(self, i):
        if i >= len(self.cues):
            return
        c, g = self.cues[i], self.gen
        pre, post = int(c["pre"] * 1000), int(c["post"] * 1000)
        self.table.selectRow(min(i + 1, len(self.cues) - 1))  # selection moves on, like QLab

        def follow():
            if g == self.gen and c["cont"] == "Auto-follow":
                self.fire(i + 1)

        QTimer.singleShot(pre, lambda: g == self.gen and self.start(c, follow))
        if c["cont"] == "Auto-continue":
            QTimer.singleShot(pre + post, lambda: g == self.gen and self.fire(i + 1))

    def start(self, c, follow):
        t = c["type"]
        if t == "Stop all":
            self.stop_media()
            return follow()
        if not c["armed"] or not c["file"]:
            return follow()
        if t == "Image":
            self.out.show_image(c["file"])
            if c["dur"] > 0:
                def end():
                    if self.out.current == c["file"]:
                        self.out.blank()
                    follow()
                QTimer.singleShot(int(c["dur"] * 1000), end)
            else:
                follow()
            return
        p, a = QMediaPlayer(), QAudioOutput()
        p.setAudioOutput(a)
        if t == "Video":
            p.setVideoOutput(self.out.video)
            self.out.show_video()
        p.setSource(QUrl.fromLocalFile(c["file"]))
        entry = (p, a)
        self.playing.append(entry)

        def status(s):
            if s == QMediaPlayer.MediaStatus.EndOfMedia:
                if entry in self.playing:
                    self.playing.remove(entry)
                if t == "Video" and self.out.current == "video":
                    self.out.blank()
                follow()
        p.mediaStatusChanged.connect(status)
        p.play()

    def stop_media(self):
        for p, _ in self.playing:
            p.stop()
        self.playing.clear()
        self.out.blank()

    def stop_all(self):
        self.gen += 1  # cancels pending pre-waits and auto-continues
        self.stop_media()

    def closeEvent(self, e):
        self.out.close()
        e.accept()


ICON = r"C:\Users\Milo\Downloads\QDeck.ico"  # fallback; an QDeck.ico next to this script wins

if __name__ == "__main__":
    import ctypes
    try:  # stops Windows grouping the taskbar button under the Python icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("qdeck.show.app")
    except Exception:
        pass
    app = QApplication(sys.argv)
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "QDeck.ico")
    app.setWindowIcon(QIcon(local if os.path.exists(local) else ICON))
    w = Main()
    w.resize(1150, 650)
    w.show()
    sys.exit(app.exec())
