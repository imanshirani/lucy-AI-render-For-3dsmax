"""
LucyLive AI Panel for 3ds Max 2025/2026
PySide6 QDockWidget — docked into the Max main window.
Spawns lucy_worker.py in venv310 (Max built-in Python 3.10).
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import subprocess
import tempfile
import threading

import pymxs
from PySide6 import QtCore, QtGui, QtWidgets

rt = pymxs.runtime

ROOT         = pathlib.Path(__file__).resolve().parent
VENV_PYTHON  = ROOT / "venv310" / "Scripts" / "python.exe"
WORKER_SCRIPT = ROOT / "lucy_worker.py"
CONFIG_FILE  = ROOT / "config.json"

# ── Colour palette (mirrors 3D Gaussian Splat Generator) ──────────────────
COLOR_BG_DARK    = "#1e1e1e"
COLOR_BG_MID     = "#2a2a2a"
COLOR_BG_LIGHT   = "#333333"
COLOR_BG_INPUT   = "#252525"
COLOR_ACCENT      = "#00AAFF"
COLOR_ACCENT_DIM  = "#007ABB"
COLOR_TEXT        = "#dddddd"
COLOR_TEXT_DIM    = "#888888"
COLOR_TEXT_MUTED  = "#555555"
COLOR_BORDER      = "#3a3a3a"
COLOR_DANGER      = "#FF4444"
COLOR_SUCCESS     = "#00CC66"
COLOR_WARN        = "#FFA500"

STYLESHEET = f"""
QWidget {{
    background-color: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: "Segoe UI";
    font-size: 12px;
}}
QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    font-weight: bold;
    color: {COLOR_TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    color: {COLOR_TEXT};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {COLOR_ACCENT};
}}
QPushButton {{
    background-color: {COLOR_BG_LIGHT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 10px;
    min-height: 22px;
    color: {COLOR_TEXT};
}}
QPushButton:hover  {{ background-color: #3d3d3d; }}
QPushButton:disabled {{ color: {COLOR_TEXT_MUTED}; background-color: #2a2a2a; }}
QPushButton#btn_primary {{
    background-color: {COLOR_ACCENT_DIM};
    border-color: {COLOR_ACCENT};
    font-weight: bold;
}}
QPushButton#btn_primary:hover   {{ background-color: {COLOR_ACCENT}; color: #000; }}
QPushButton#btn_primary:disabled {{ background-color: #004466; border-color: #005588; color: {COLOR_TEXT_MUTED}; }}
QPushButton#btn_danger {{
    background-color: #661111;
    border-color: {COLOR_DANGER};
}}
QPushButton#btn_danger:hover    {{ background-color: #882222; }}
QPushButton#btn_danger:disabled {{ background-color: #2d1111; color: {COLOR_TEXT_MUTED}; }}
QPushButton#btn_warn {{
    background-color: #4a3000;
    border-color: {COLOR_WARN};
}}
QPushButton#btn_warn:hover {{ background-color: #664400; }}
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_BG_DARK};
}}
QTabBar::tab {{
    background-color: {COLOR_BG_MID};
    color: {COLOR_TEXT_DIM};
    padding: 5px 14px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
}}
QTabBar::tab:selected {{
    background-color: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
}}
QTabBar::tab:hover:!selected {{ background-color: {COLOR_BG_LIGHT}; }}
QProgressBar {{
    background-color: {COLOR_BG_MID};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    text-align: center;
    height: 16px;
    color: {COLOR_TEXT};
}}
QProgressBar::chunk {{ background-color: {COLOR_ACCENT_DIM}; border-radius: 2px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 2px;
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT_DIM};
    border-color: {COLOR_ACCENT};
}}
QScrollBar:vertical {{
    background: {COLOR_BG_MID}; width: 8px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BG_LIGHT}; border-radius: 4px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QFrame[frameShape="4"] {{ color: {COLOR_BORDER}; }}
"""

_panel_instance: "LucyLivePanel | None" = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_max_main_window() -> QtWidgets.QMainWindow | None:
    try:
        hwnd = rt.windows.getMAXHWND()
        for w in QtWidgets.QApplication.topLevelWidgets():
            if int(w.winId()) == hwnd:
                return w
    except Exception:
        pass
    return QtWidgets.QApplication.activeWindow()


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except Exception:
        pass


def _sep() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setFrameShape(QtWidgets.QFrame.HLine)
    f.setFrameShadow(QtWidgets.QFrame.Sunken)
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Log panel
# ─────────────────────────────────────────────────────────────────────────────

class LogPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._stage_label = QtWidgets.QLabel("Idle")
        self._stage_label.setAlignment(QtCore.Qt.AlignCenter)
        self._stage_label.setStyleSheet(
            f"font-weight: bold; color: {COLOR_ACCENT}; font-size: 13px;")
        layout.addWidget(self._stage_label)

        self._stream_bar = QtWidgets.QProgressBar()
        self._stream_bar.setRange(0, 0)          # indeterminate while running
        self._stream_bar.setFormat("Stream: active")
        self._stream_bar.setValue(0)
        layout.addWidget(self._stream_bar)

        self._log = QtWidgets.QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QtGui.QFont("Consolas", 9))
        self._log.setMaximumBlockCount(2000)
        layout.addWidget(self._log, stretch=1)

        clear_btn = QtWidgets.QPushButton("Clear Log")
        clear_btn.clicked.connect(self._log.clear)
        layout.addWidget(clear_btn)

    def set_stage(self, text: str):
        self._stage_label.setText(text)

    def set_running(self, running: bool):
        if running:
            self._stream_bar.setRange(0, 0)
            self._stream_bar.setFormat("Streaming to Decart...")
        else:
            self._stream_bar.setRange(0, 100)
            self._stream_bar.setValue(0)
            self._stream_bar.setFormat("Idle")

    def append(self, msg: str, level: str = "info"):
        color = {
            "info":    COLOR_SUCCESS,
            "warn":    COLOR_WARN,
            "error":   COLOR_DANGER,
            "muted":   COLOR_TEXT_DIM,
        }.get(level, COLOR_TEXT)
        self._log.appendHtml(
            f'<span style="color:{color};">{html.escape(msg)}</span>')


# ─────────────────────────────────────────────────────────────────────────────
# Preview widget — shows AI output frames
# ─────────────────────────────────────────────────────────────────────────────

class PreviewWidget(QtWidgets.QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumHeight(180)
        self.setStyleSheet(
            f"background-color: {COLOR_BG_MID}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; "
            f"color: {COLOR_TEXT_DIM};")
        self.setText("Preview will appear here")
        self._output_path: pathlib.Path | None = None
        self._last_mtime: float = 0.0

    def set_output_path(self, path: pathlib.Path):
        self._output_path = path
        self._last_mtime = 0.0

    def refresh(self):
        if not self._output_path or not self._output_path.exists():
            return
        try:
            mtime = self._output_path.stat().st_mtime
        except OSError:
            return
        if mtime <= self._last_mtime:
            return
        self._last_mtime = mtime
        try:
            px = QtGui.QPixmap(str(self._output_path))
            if not px.isNull():
                self.setPixmap(px.scaled(
                    self.size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Preview window — floating, resizable, stays on top of Max
# ─────────────────────────────────────────────────────────────────────────────

class PreviewWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint |
                         QtCore.Qt.WindowCloseButtonHint | QtCore.Qt.WindowMinMaxButtonsHint)
        self.setWindowTitle("LucyLive — AI Preview")
        self.setStyleSheet(STYLESHEET)
        self.resize(1280 // 2, 720 // 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._preview = PreviewWidget()
        layout.addWidget(self._preview, stretch=1)

        # bottom bar
        bar = QtWidgets.QHBoxLayout()
        self._info = QtWidgets.QLabel("Waiting for stream…")
        self._info.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 10px;")
        bar.addWidget(self._info, stretch=1)

        fit_btn = QtWidgets.QPushButton("Fit")
        fit_btn.setFixedWidth(40)
        fit_btn.clicked.connect(self._fit)
        bar.addWidget(fit_btn)

        full_btn = QtWidgets.QPushButton("1:1")
        full_btn.setFixedWidth(40)
        full_btn.clicked.connect(self._fullsize)
        bar.addWidget(full_btn)

        layout.addLayout(bar)

    def set_output_path(self, path: pathlib.Path):
        self._preview.set_output_path(path)

    def refresh(self):
        self._preview.refresh()
        if self._preview._last_mtime > 0:
            self._info.setText("Streaming  ●")
            self._info.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 10px;")

    def set_idle(self):
        self._info.setText("Waiting for stream…")
        self._info.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 10px;")

    def _fit(self):
        self.resize(1280 // 2, 720 // 2)

    def _fullsize(self):
        self.resize(1280, 720)

    def closeEvent(self, event):
        # hide instead of destroy so it can be re-shown
        event.ignore()
        self.hide()


# ─────────────────────────────────────────────────────────────────────────────
# Worker process wrapper
# ─────────────────────────────────────────────────────────────────────────────

class WorkerProcess:
    def __init__(self, state_dir: pathlib.Path, parent_pid: int):
        self._state = state_dir
        self._pid   = parent_pid
        self._proc: subprocess.Popen | None = None

    def start(self, on_line=None) -> bool:
        if not VENV_PYTHON.exists():
            return False
        self._proc = subprocess.Popen(
            [str(VENV_PYTHON), str(WORKER_SCRIPT),
             "--state", str(self._state),
             "--parent-pid", str(self._pid)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        if on_line:
            threading.Thread(
                target=self._drain, args=(on_line,), daemon=True).start()
        return True

    def _drain(self, cb):
        if self._proc and self._proc.stdout:
            for line in self._proc.stdout:
                cb(line.rstrip())

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def write_control(self, prompt: str, reference: str | None = None,
                      recording: bool = False, rec_path: str | None = None,
                      rec_fmt: str = "JPEG Seq"):
        ctrl = {"prompt": prompt, "recording": recording, "rec_fmt": rec_fmt}
        if reference:
            ctrl["reference_image"] = reference
        if rec_path:
            ctrl["rec_path"] = rec_path
        tmp = self._state / "_ctrl_tmp.json"
        tgt = self._state / "control.json"
        tmp.write_text(json.dumps(ctrl), encoding="utf-8")
        try:
            tgt.unlink(missing_ok=True)
        except Exception:
            pass
        tmp.rename(tgt)


# ─────────────────────────────────────────────────────────────────────────────
# Stream tab
# ─────────────────────────────────────────────────────────────────────────────

class StreamTab(QtWidgets.QWidget):

    log_signal    = QtCore.Signal(str, str)   # (message, level)
    stage_signal  = QtCore.Signal(str)
    running_signal = QtCore.Signal(bool)

    def __init__(self, config: dict, log_panel: LogPanel):
        super().__init__()
        self._cfg       = config
        self._log_panel = log_panel
        self._worker: WorkerProcess | None = None
        self._state_dir: pathlib.Path | None = None
        self._reference: str | None = None

        self.log_signal.connect(log_panel.append)
        self.stage_signal.connect(log_panel.set_stage)
        self.running_signal.connect(log_panel.set_running)

        # floating preview window — created once, shown/hidden on demand
        self._preview_win = PreviewWindow(_get_max_main_window())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_prompt_group())
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_status_label())

        self._tick = QtCore.QTimer(self)
        self._tick.timeout.connect(self._on_tick)

        # warn if venv missing
        self._env_warn = QtWidgets.QLabel(
            "⚠  venv310 not found — click Install to set up dependencies.")
        self._env_warn.setWordWrap(True)
        self._env_warn.setStyleSheet(
            f"background-color: #2d1f1f; border: 1px solid {COLOR_DANGER}; "
            f"color: {COLOR_DANGER}; border-radius: 3px; padding: 6px;")
        self._env_warn.setVisible(not VENV_PYTHON.exists())
        layout.insertWidget(0, self._env_warn)

    # ── Group: Connection ───────────────────────────────────────────────────

    def _build_connection_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Connection")
        fl  = QtWidgets.QFormLayout(box)
        fl.setSpacing(6)

        self._key_edit = QtWidgets.QLineEdit()
        self._key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self._key_edit.setPlaceholderText("decart_xxxxxxxxxxxxxxxx...")
        self._key_edit.setText(self._cfg.get("decart_key", ""))
        fl.addRow("API Key:", self._key_edit)

        # connection status dot
        self._conn_dot = QtWidgets.QLabel("●  Disconnected")
        self._conn_dot.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        fl.addRow("Status:", self._conn_dot)
        return box

    # ── Group: Prompt & Reference ───────────────────────────────────────────

    def _build_prompt_group(self) -> QtWidgets.QGroupBox:
        box    = QtWidgets.QGroupBox("Prompt & Reference")
        layout = QtWidgets.QVBoxLayout(box)
        layout.setSpacing(6)

        self._prompt_edit = QtWidgets.QTextEdit()
        self._prompt_edit.setFixedHeight(58)
        self._prompt_edit.setPlaceholderText(
            "cinematic lighting, golden hour, photorealistic...")
        layout.addWidget(self._prompt_edit)

        # reference preview thumbnail
        self._ref_thumb = QtWidgets.QLabel()
        self._ref_thumb.setFixedHeight(72)
        self._ref_thumb.setAlignment(QtCore.Qt.AlignCenter)
        self._ref_thumb.setStyleSheet(
            f"background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 3px; color: {COLOR_TEXT_MUTED}; font-size: 10px;")
        self._ref_thumb.setText("No reference image")
        self._ref_thumb.setVisible(False)
        layout.addWidget(self._ref_thumb)

        ref_row = QtWidgets.QHBoxLayout()
        self._ref_label = QtWidgets.QLabel("No reference image")
        self._ref_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        self._ref_label.setVisible(True)
        ref_row.addWidget(self._ref_label, stretch=1)

        browse_btn = QtWidgets.QPushButton("Browse…")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_ref)
        ref_row.addWidget(browse_btn)

        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.setFixedWidth(46)
        clear_btn.clicked.connect(self._clear_ref)
        ref_row.addWidget(clear_btn)
        layout.addLayout(ref_row)
        return box

    # ── Controls row ────────────────────────────────────────────────────────

    def _build_controls(self) -> QtWidgets.QWidget:
        w   = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        # row 1: stream controls
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)

        self._start_btn = QtWidgets.QPushButton("▶  Start")
        self._start_btn.setObjectName("btn_primary")
        self._start_btn.setFixedHeight(34)
        self._start_btn.clicked.connect(self._on_start)
        row1.addWidget(self._start_btn)

        self._stop_btn = QtWidgets.QPushButton("■  Stop")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.setFixedHeight(34)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        row1.addWidget(self._stop_btn)

        self._rec_btn = QtWidgets.QPushButton("⏺  Record")
        self._rec_btn.setObjectName("btn_warn")
        self._rec_btn.setFixedHeight(34)
        self._rec_btn.setCheckable(True)
        self._rec_btn.setEnabled(False)
        self._rec_btn.clicked.connect(self._on_rec_toggle)
        row1.addWidget(self._rec_btn)

        col.addLayout(row1)

        # row 1b: recording output path
        row1b = QtWidgets.QHBoxLayout()
        row1b.setSpacing(4)
        rec_lbl = QtWidgets.QLabel("Save to:")
        rec_lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        rec_lbl.setFixedWidth(46)
        row1b.addWidget(rec_lbl)
        self._rec_path_edit = QtWidgets.QLineEdit()
        self._rec_path_edit.setPlaceholderText("(default: Desktop\\lucylive_rec)")
        self._rec_path_edit.setFixedHeight(24)
        self._rec_path_edit.setText(self._cfg.get("rec_path", ""))
        row1b.addWidget(self._rec_path_edit, stretch=1)

        self._rec_fmt = QtWidgets.QComboBox()
        self._rec_fmt.addItems(["JPEG Seq", "MP4"])
        self._rec_fmt.setFixedWidth(76)
        self._rec_fmt.setFixedHeight(24)
        self._rec_fmt.setCurrentText(self._cfg.get("rec_fmt", "JPEG Seq"))
        self._rec_fmt.currentTextChanged.connect(self._on_rec_fmt_changed)
        row1b.addWidget(self._rec_fmt)

        rec_browse = QtWidgets.QPushButton("…")
        rec_browse.setFixedSize(26, 24)
        rec_browse.clicked.connect(self._browse_rec_path)
        row1b.addWidget(rec_browse)
        col.addLayout(row1b)

        # row 2: preview toggle + install
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)

        self._preview_btn = QtWidgets.QPushButton("◻  Preview Window")
        self._preview_btn.setCheckable(True)
        self._preview_btn.setFixedHeight(28)
        self._preview_btn.setStyleSheet(
            f"QPushButton {{ background: {COLOR_BG_MID}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 3px; color: {COLOR_TEXT_DIM}; }}"
            f"QPushButton:checked {{ background: {COLOR_ACCENT_DIM}; border-color: {COLOR_ACCENT}; "
            f"color: white; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {COLOR_BG_LIGHT}; }}"
        )
        self._preview_btn.clicked.connect(self._toggle_preview)
        row2.addWidget(self._preview_btn, stretch=1)

        if not VENV_PYTHON.exists():
            install_btn = QtWidgets.QPushButton("Install Dependencies")
            install_btn.setObjectName("btn_warn")
            install_btn.setFixedHeight(28)
            install_btn.clicked.connect(self._run_install)
            row2.addWidget(install_btn)

        col.addLayout(row2)
        return w

    def _build_status_label(self) -> QtWidgets.QLabel:
        self._status = QtWidgets.QLabel("Ready")
        self._status.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10px;")
        return self._status

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_start(self):
        api_key = self._key_edit.text().strip()
        if not api_key or api_key == "YOUR_DECART_KEY_HERE":
            QtWidgets.QMessageBox.warning(
                self, "LucyLive", "Enter your Decart API key first.\nGet one at platform.decart.ai")
            return

        if not VENV_PYTHON.exists():
            QtWidgets.QMessageBox.warning(
                self, "LucyLive",
                "Run install.bat first to set up the Python environment.")
            return

        os.environ["DECART_API_KEY"] = api_key
        self._cfg["decart_key"] = api_key
        _save_config(self._cfg)

        self._state_dir = pathlib.Path(tempfile.mkdtemp(prefix="lucylive_"))
        self._preview_win.set_output_path(self._state_dir / "output_latest.jpg")
        # auto-open only if not already visible
        if not self._preview_win.isVisible():
            self._preview_win.show()
            self._preview_win.raise_()
            self._preview_btn.setChecked(True)
            self._preview_btn.setText("◼  Preview Window")

        self._worker = WorkerProcess(self._state_dir, os.getpid())
        self._push_control()

        if not self._worker.start(on_line=self._on_worker_line):
            self._set_status("ERROR: worker failed to start", "error")
            return

        interval = self._cfg.get("capture_interval_ms", 125)
        self._tick.start(interval)

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._rec_btn.setEnabled(True)
        self._set_status("Streaming — Decart Lucy 2.5", "info")
        self._set_conn_state("connecting")
        self.running_signal.emit(True)
        self.log_signal.emit("Stream started.", "info")

    def _on_stop(self):
        self._tick.stop()
        if self._worker:
            self._worker.stop()
            self._worker = None

        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._rec_btn.setEnabled(False)
        self._rec_btn.setChecked(False)
        self._preview_win.set_idle()
        self._set_status("Stopped")
        self._set_conn_state("disconnected")
        self.running_signal.emit(False)
        self.log_signal.emit("Stream stopped.", "muted")

    def _on_tick(self):
        if not self._worker or not self._worker.is_alive():
            self.log_signal.emit("Worker process exited.", "warn")
            self._on_stop()
            return
        self._capture_viewport()
        self._push_control()
        self._preview_win.refresh()

    def _capture_viewport(self):
        import os
        tmp = self._state_dir / "_frame_tmp.jpg"
        tgt = self._state_dir / "latest_frame.jpg"

        # method 1: getViewportDib
        try:
            dib = rt.gw.getViewportDib()
            if dib is not None:
                dib.filename = str(tmp)
                rt.save(dib)
                if tmp.exists():
                    os.replace(str(tmp), str(tgt))
                    return
        except Exception:
            pass

        # method 2: QScreen grab of the viewport rect
        try:
            import ctypes, ctypes.wintypes
            hwnd = int(rt.windows.getMAXHWND())
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
            pt = ctypes.wintypes.POINT(0, 0)
            ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
            x, y = pt.x, pt.y
            w_scr = rect.right - rect.left
            h_scr = rect.bottom - rect.top
            screen = QtWidgets.QApplication.primaryScreen()
            px = screen.grabWindow(0, x, y, w_scr, h_scr)
            w = self._cfg.get("canvas_width", 1280)
            h = self._cfg.get("canvas_height", 720)
            px = px.scaled(w, h, QtCore.Qt.IgnoreAspectRatio,
                           QtCore.Qt.SmoothTransformation)
            px.save(str(tmp), "JPEG", 88)
            os.replace(str(tmp), str(tgt))
        except Exception as e:
            self.log_signal.emit(f"capture error: {e}", "error")

    def _push_control(self):
        if not self._worker:
            return
        import os
        rec_path = self._rec_path_edit.text().strip()
        if not rec_path:
            rec_path = os.path.join(os.path.expanduser("~"), "Desktop", "lucylive_rec.mp4")
        self._worker.write_control(
            prompt    = self._prompt_edit.toPlainText().strip(),
            reference = self._reference,
            recording = self._rec_btn.isChecked(),
            rec_path  = rec_path,
            rec_fmt   = self._rec_fmt.currentText(),
        )

    def _on_worker_line(self, line: str):
        if not line:
            return
        lower = line.lower()
        level = ("error" if "error" in lower or "fatal" in lower
                 else "warn" if "warn" in lower
                 else "muted")
        self.log_signal.emit(line, level)

        # parse connection state from worker output
        if "state: connecting" in lower or "connecting to decart" in lower:
            self._set_conn_state("connecting")
        elif "state: connected" in lower:
            self._set_conn_state("connected")
        elif "state: generating" in lower or "ai video stream connected" in lower:
            self._set_conn_state("generating")
        elif "state: reconnecting" in lower:
            self._set_conn_state("reconnecting")
        elif "state: disconnected" in lower or "exited" in lower or "fatal" in lower:
            self._set_conn_state("disconnected")

    def _set_conn_state(self, state: str):
        styles = {
            "disconnected": (COLOR_TEXT_MUTED,  "●  Disconnected"),
            "connecting":   (COLOR_WARN,         "●  Connecting…"),
            "connected":    (COLOR_ACCENT,        "●  Connected"),
            "generating":   (COLOR_SUCCESS,       "●  Generating"),
            "reconnecting": (COLOR_WARN,          "●  Reconnecting…"),
        }
        color, text = styles.get(state, (COLOR_TEXT_MUTED, "●  Unknown"))
        self._conn_dot.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;")
        self._conn_dot.setText(text)
        self.stage_signal.emit(text.replace("● ", "").strip("…"))

    def _browse_rec_path(self):
        import os
        default = self._rec_path_edit.text().strip()
        if not default:
            default = os.path.join(os.path.expanduser("~"), "Desktop", "lucylive_rec")
        if self._rec_fmt.currentText() == "MP4":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save Recording As", default + ".mp4",
                "MP4 Video (*.mp4)")
        else:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Select Folder for Image Sequence", default)
        if path:
            self._rec_path_edit.setText(path)
            self._cfg["rec_path"] = path
            _save_config(self._cfg)

    def _on_rec_fmt_changed(self, fmt: str):
        path = self._rec_path_edit.text().strip()
        if fmt == "MP4":
            self._rec_path_edit.setPlaceholderText("Desktop\\lucylive_rec.mp4")
            if path:
                p = pathlib.Path(path)
                if p.is_dir() or p.suffix.lower() != ".mp4":
                    self._rec_path_edit.setText(str(p.with_suffix(".mp4")))
        else:
            self._rec_path_edit.setPlaceholderText("Desktop\\lucylive_rec  (folder)")
            if path:
                p = pathlib.Path(path)
                if p.suffix.lower() == ".mp4":
                    self._rec_path_edit.setText(str(p.with_suffix("")))
        self._cfg["rec_fmt"] = fmt
        _save_config(self._cfg)

    def _on_rec_toggle(self):
        if self._rec_btn.isChecked():
            import os
            path = self._rec_path_edit.text().strip()
            if not path:
                path = os.path.join(os.path.expanduser("~"), "Desktop", "lucylive_rec")
                self._rec_path_edit.setText(path)
            self._cfg["rec_fmt"] = self._rec_fmt.currentText()
            _save_config(self._cfg)
        self._push_control()

    def _browse_ref(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Reference Image", "",
            "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            self._reference = path
            self._ref_label.setVisible(False)
            px = QtGui.QPixmap(path)
            if not px.isNull():
                self._ref_thumb.setPixmap(px.scaled(
                    self._ref_thumb.width(), self._ref_thumb.height(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation))
                self._ref_thumb.setVisible(True)
            else:
                self._ref_label.setText(pathlib.Path(path).name)
                self._ref_label.setVisible(True)
            self._push_control()

    def _clear_ref(self):
        self._reference = None
        self._ref_thumb.setVisible(False)
        self._ref_thumb.clear()
        self._ref_label.setText("No reference image")
        self._ref_label.setVisible(True)
        self._push_control()

    def _set_status(self, msg: str, level: str = "muted"):
        color = {
            "info": COLOR_SUCCESS, "warn": COLOR_WARN,
            "error": COLOR_DANGER, "muted": COLOR_TEXT_DIM,
        }.get(level, COLOR_TEXT_DIM)
        self._status.setStyleSheet(f"color: {color}; font-size: 10px;")
        self._status.setText(msg)

    def _toggle_preview(self):
        if self._preview_win.isVisible():
            self._preview_win.hide()
            self._preview_btn.setChecked(False)
            self._preview_btn.setText("◻  Preview Window")
        else:
            self._preview_win.show()
            self._preview_win.raise_()
            self._preview_btn.setChecked(True)
            self._preview_btn.setText("◼  Preview Window")

    def _run_install(self):
        bat = ROOT / "install.bat"
        if not bat.exists():
            QtWidgets.QMessageBox.critical(self, "LucyLive", "install.bat not found.")
            return
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self._set_status("install.bat running in new window…", "warn")

    def stop_worker(self):
        self._on_stop()


# ─────────────────────────────────────────────────────────────────────────────
# About tab
# ─────────────────────────────────────────────────────────────────────────────

class AboutTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("LucyLive AI")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {COLOR_ACCENT};")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        by_label = QtWidgets.QLabel("by imanshirani")
        by_label.setStyleSheet(
            f"font-size: 10px; color: {COLOR_TEXT_MUTED};")
        by_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(by_label)

        layout.addWidget(_sep())

        info = QtWidgets.QLabel(
            "Real-time AI viewport rendering for 3ds Max\n\n"
            "Streams the Max viewport via WebRTC to\n"
            "Decart's Lucy 2.5 model and displays\n"
            "AI-rendered frames live.\n\n"
            "Lucy 2.5 is developed by Decart.\n"
            "This plugin is an independent integration\n"
            "for 3ds Max — not affiliated with Decart.\n\n"
            "Cost: ~$0.02 / second  ($1.20 / min)\n\n"
            "For 3ds Max 2025 / 2026 / 2027"
        )
        info.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        info.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(info)

        layout.addStretch()

        api_btn = QtWidgets.QPushButton("Get Decart API Key →")
        api_btn.setObjectName("btn_primary")
        api_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl("https://platform.decart.ai/")))
        layout.addWidget(api_btn)

        # GitHub button — dark theme
        gh_btn = QtWidgets.QPushButton("  GitHub — Source Code")
        gh_btn.setFixedHeight(30)
        gh_btn.setStyleSheet("""
            QPushButton {
                background-color: #24292f;
                border: 1px solid #444c56;
                border-radius: 4px;
                color: #e6edf3;
                font-size: 12px;
                font-weight: bold;
                padding-left: 8px;
                text-align: left;
            }
            QPushButton:hover { background-color: #30363d; }
        """)
        gh_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl("https://github.com/imanshirani/lucy-AI-render-For-3dsmax")))
        layout.addWidget(gh_btn)

        # PayPal donate button — blue theme
        pp_btn = QtWidgets.QPushButton("  Donate via PayPal")
        pp_btn.setFixedHeight(30)
        pp_btn.setStyleSheet("""
            QPushButton {
                background-color: #003087;
                border: 1px solid #009cde;
                border-radius: 4px;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                padding-left: 8px;
                text-align: left;
            }
            QPushButton:hover { background-color: #009cde; }
        """)
        pp_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl("https://www.paypal.com/donate/?hosted_button_id=LAMNRY6DDWDC4")))
        layout.addWidget(pp_btn)

        setup_btn = QtWidgets.QPushButton("Run install.bat")
        setup_btn.setObjectName("btn_warn")
        setup_btn.clicked.connect(lambda: subprocess.Popen(
            ["cmd", "/c", str(ROOT / "install.bat")],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        ))
        layout.addWidget(setup_btn)


# ─────────────────────────────────────────────────────────────────────────────
# Main dock widget
# ─────────────────────────────────────────────────────────────────────────────

class LucyLivePanel(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("LucyLive AI", parent)
        self.setObjectName("LucyLiveDock")
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable   |
            QtWidgets.QDockWidget.DockWidgetFloatable |
            QtWidgets.QDockWidget.DockWidgetClosable
        )
        self.setMinimumWidth(300)

        cfg  = _load_config()
        root = QtWidgets.QWidget()
        root.setStyleSheet(STYLESHEET)
        self.setWidget(root)

        vbox = QtWidgets.QVBoxLayout(root)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(6)

        # ── Header ──────────────────────────────────────────────────────────
        header = QtWidgets.QLabel("LucyLive AI")
        header.setAlignment(QtCore.Qt.AlignCenter)
        header.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {COLOR_ACCENT};")
        vbox.addWidget(header)
        vbox.addWidget(_sep())

        # ── Tabs ─────────────────────────────────────────────────────────────
        tabs = QtWidgets.QTabWidget()

        self._log_panel  = LogPanel()
        self._stream_tab = StreamTab(cfg, self._log_panel)

        tabs.addTab(self._stream_tab, "Stream")
        tabs.addTab(self._log_panel,  "Log")
        tabs.addTab(AboutTab(),       "About")

        vbox.addWidget(tabs)

    def closeEvent(self, event):
        self._stream_tab.stop_worker()
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point  (called by lucylive_panel.ms via python.ExecuteFile)
# ─────────────────────────────────────────────────────────────────────────────

def launch():
    global _panel_instance
    if _panel_instance is not None:
        try:
            _panel_instance.close()
            _panel_instance.deleteLater()
        except Exception:
            pass
        _panel_instance = None

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_win = _get_max_main_window()
    if main_win is None:
        QtWidgets.QMessageBox.critical(
            None, "LucyLive", "Could not find 3ds Max main window.")
        return

    panel = LucyLivePanel(main_win)
    main_win.addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
    panel.show()
    _panel_instance = panel


launch()
