"""Dark theme in Spotify colours: Fusion + palette + one app-level stylesheet.

Widgets get object names or dynamic properties, never inline setStyleSheet: an inline sheet cuts its children off
from the app-level rules (pyside6-desktop, QSS rules 1 and 27)."""
import ctypes, sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyledItemDelegate

ASSETS = Path(__file__).resolve().parent / "assets"  # svg icons the stylesheet points at; ship with the build

QSS = """
QMainWindow, QDialog, QMessageBox { background: #121212; }
QWidget#backdrop {
    background: qradialgradient(cx:0.15, cy:0, radius:1.1, fx:0.15, fy:0, stop:0 #1b3d27, stop:0.55 #121212);
}
QFrame#card { background: rgba(24, 24, 24, 0.94); border: 1px solid #262626; border-radius: 12px; }

QLabel { color: #ffffff; background: transparent; }
QLabel:disabled { color: #6a6a6a; }
QLabel#title { font-size: 12pt; font-weight: 600; }
QLabel#hint, QStatusBar QLabel { color: #b3b3b3; }
QLabel[on="true"] { color: #1ed760; }
QLabel[on="false"] { color: #b3b3b3; }
QLabel#hint:disabled, QLabel[on="true"]:disabled, QLabel[on="false"]:disabled, QGroupBox:disabled { color: #6a6a6a; }

QPushButton {
    background: transparent; color: #ffffff; font-weight: 600;
    border: 1px solid #535353; border-radius: 8px; padding: 6px 18px; min-height: 18px;
}
QPushButton:hover { border-color: #ffffff; }
QPushButton:pressed { background: #1f1f1f; }
QPushButton:disabled { color: #5a5a5a; border-color: #2e2e2e; }
QPushButton[accent="true"] { background: #1db954; color: #000000; border-color: #1db954; }  /* border: none drops the radius */
QPushButton[accent="true"]:hover { background: #1ed760; border-color: #1ed760; }
QPushButton[accent="true"]:pressed { background: #169c46; border-color: #169c46; }
QPushButton[accent="true"]:disabled { background: #1c3a27; color: #4f6f5a; border-color: #1c3a27; }

QLineEdit, QComboBox {
    background: #242424; color: #ffffff; border: 1px solid #2f2f2f; border-radius: 8px; padding: 6px 10px;
    selection-background-color: #1db954; selection-color: #000000;
}
QLineEdit:hover, QComboBox:hover { border-color: #535353; }
QLineEdit:focus, QComboBox:focus { border-color: #1db954; }
QLineEdit:disabled, QComboBox:disabled { color: #6a6a6a; background: #1c1c1c; border-color: #262626; }
QComboBox { min-width: 120px; combobox-popup: 0; }  /* the list opens below the box, not over it */
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url("@ASSETS/chevron.svg"); width: 10px; height: 10px; }
QComboBox QFrame { background: transparent; border: none; }  /* the popup window around the list (round_popup) */
QComboBox QAbstractItemView {
    background: #282828; color: #ffffff; border: 1px solid #3a3a3a; border-radius: 8px; padding: 4px; outline: none;
}
QComboBox QAbstractItemView::item { padding: 6px 10px; border-radius: 6px; }
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected { background: #3e3e3e; color: #ffffff; }

QListWidget, QTableWidget { background: transparent; border: none; color: #ffffff; outline: none; }
QListWidget::item { padding: 7px 8px; border-radius: 6px; }
QListWidget::item:hover { background: #242424; }
QListWidget::item:selected { background: #2a2a2a; color: #ffffff; }
QAbstractItemView::indicator {
    width: 14px; height: 14px; border: 2px solid #727272; border-radius: 4px; background: transparent;
}
QAbstractItemView::indicator:hover { border-color: #ffffff; }
QAbstractItemView::indicator:checked { background: #1db954; border-color: #1db954; image: url("@ASSETS/check.svg"); }
QTableWidget { selection-background-color: #2a2a2a; selection-color: #ffffff; }
QTableWidget::item { padding: 0 8px; border-bottom: 1px solid #222222; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: transparent; color: #b3b3b3; font-weight: 600;
    border: none; border-bottom: 1px solid #2a2a2a; padding: 6px 8px;
}
QTableCornerButton::section { background: transparent; border: none; }

QGroupBox { border: none; margin-top: 20px; color: #b3b3b3; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0; }
QRadioButton { color: #ffffff; spacing: 8px; }
QRadioButton:disabled { color: #6a6a6a; }
QRadioButton::indicator { width: 14px; height: 14px; border: 2px solid #727272; border-radius: 9px; background: transparent; }
QRadioButton::indicator:hover { border-color: #ffffff; }
QRadioButton::indicator:checked { width: 8px; height: 8px; border: 5px solid #1db954; background: #121212; }

QProgressBar { background: #2a2a2a; border: none; border-radius: 3px; max-height: 6px; min-width: 160px; }
QProgressBar::chunk { background: #1db954; border-radius: 3px; }
QStatusBar { background: #121212; border-top: 1px solid #1f1f1f; }
QStatusBar::item { border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: #3e3e3e; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: #5a5a5a; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background: #282828; color: #ffffff; border: none; padding: 6px; }
"""


def _palette():
    """For what the stylesheet does not cover: dialogs, link colour, placeholders, disabled text."""
    p = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "#121212"), (QPalette.ColorRole.WindowText, "#ffffff"),
                        (QPalette.ColorRole.Base, "#181818"), (QPalette.ColorRole.AlternateBase, "#202020"),
                        (QPalette.ColorRole.Text, "#ffffff"), (QPalette.ColorRole.Button, "#242424"),
                        (QPalette.ColorRole.ButtonText, "#ffffff"), (QPalette.ColorRole.Highlight, "#1db954"),
                        (QPalette.ColorRole.HighlightedText, "#000000"), (QPalette.ColorRole.Link, "#1ed760"),
                        (QPalette.ColorRole.PlaceholderText, "#8a8a8a"), (QPalette.ColorRole.ToolTipBase, "#282828"),
                        (QPalette.ColorRole.ToolTipText, "#ffffff")):
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6a6a6a"))
    return p


def apply(app):
    app.setStyle("Fusion")  # the native Windows styles ignore parts of the palette and stylesheet
    app.setFont(QFont("Segoe UI", 10))
    app.setPalette(_palette())
    app.setStyleSheet(QSS.replace("@ASSETS", ASSETS.as_posix()))


def round_popup(combo):
    """A combo box's list opens in a window of its own, square unless it is frameless and see-through; then the
    stylesheet's rounded list shows. The default delegate also ignores the ::item rules."""
    combo.setItemDelegate(QStyledItemDelegate(combo))
    popup = combo.view().window()
    popup.setWindowFlags(popup.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def dark_title_bar(window):
    """Dark native title bar in the window colour (Windows 10 1809+ / 11); a no-op elsewhere."""
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return
    hwnd = int(window.winId())
    # DWMWA_USE_IMMERSIVE_DARK_MODE = 20, DWMWA_CAPTION_COLOR = 35 (COLORREF 0x00BBGGRR; Windows 11 only)
    for attr, value in ((20, 1), (35, 0x121212)):
        v = ctypes.c_int(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
