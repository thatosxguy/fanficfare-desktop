"""Neutral desktop theme with black surfaces and oxblood accents."""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette


ASSETS = Path(__file__).resolve().parent / "assets"


def apply_theme(app):
    QFontDatabase.addApplicationFont(str(ASSETS / "IBMPlexSans-Regular.ttf"))
    app.setFont(QFont("IBM Plex Sans", 11))
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#000000", QPalette.ColorRole.WindowText: "#F7F7F7",
        QPalette.ColorRole.Base: "#0B0B0B", QPalette.ColorRole.AlternateBase: "#101012",
        QPalette.ColorRole.Text: "#F7F7F7", QPalette.ColorRole.Button: "#0B0B0B",
        QPalette.ColorRole.ButtonText: "#F7F7F7", QPalette.ColorRole.PlaceholderText: "#96969F",
        QPalette.ColorRole.Highlight: "#4A0404", QPalette.ColorRole.HighlightedText: "#F7F7F7",
        QPalette.ColorRole.ToolTipBase: "#171719", QPalette.ColorRole.ToolTipText: "#F7F7F7",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#777780"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


def display_words(metadata):
    raw = metadata.get("numWords", "")
    if not raw:
        return "—"
    try:
        return f"{int(str(raw).replace(',', '')):,}"
    except ValueError:
        return str(raw)


STYLE = """
QWidget { color: #F7F7F7; font-family: 'IBM Plex Sans'; font-size: 14px; }
QMainWindow, QWidget#page { background: #000000; }
QLabel { background: transparent; }
QLabel#appName { font-size: 18px; font-weight: 600; }
QLabel#heading { font-size: 32px; font-weight: 600; }
QLabel#sectionTitle { font-size: 19px; font-weight: 600; }
QLabel#fieldLabel { font-size: 13px; font-weight: 600; }
QLabel#muted { color: #ACACB5; font-size: 13px; }
QLabel#caption { color: #ACACB5; font-size: 12px; }
QLabel#badge { color: #D3D3D9; background: #171719; border: 1px solid #29292C; border-radius: 10px; padding: 5px 10px; font-size: 12px; }
QFrame#panel { background: #0B0B0B; border: 1px solid #252528; border-radius: 14px; }
QFrame#divider { background: #252528; max-height: 1px; border: none; }
QPlainTextEdit, QLineEdit, QComboBox { background: #121214; color: #F7F7F7; border: 1px solid #303034; border-radius: 8px; padding: 9px 11px; selection-background-color: #4A0404; }
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #8E2C2C; }
QPlainTextEdit#storyLinks { background: #121214; font-size: 15px; }
QPlainTextEdit#storyDetails { background: transparent; border: none; padding: 0; }
QComboBox { min-width: 85px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url(ARROW_PATH); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #171719; border: 1px solid #303034; selection-background-color: #4A0404; padding: 5px; }
QPushButton, QToolButton { background: #19191C; color: #F7F7F7; border: 1px solid #303034; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #222225; border-color: #49494F; }
QPushButton:focus, QToolButton:focus { border: 1px solid #8E2C2C; }
QPushButton#primary { background: #6E0808; border-color: #8E2C2C; }
QPushButton#primary:hover { background: #851414; }
QPushButton#primary:disabled { background: #101012; border-color: #232326; color: #777780; }
QPushButton#quiet, QToolButton#quiet { background: transparent; border: none; color: #ACACB5; padding: 8px 10px; }
QPushButton#quiet:hover, QToolButton#quiet:hover { background: #19191C; color: #F7F7F7; }
QPushButton#inline { background: transparent; border: none; color: #ACACB5; padding: 3px 4px; font-weight: 400; font-size: 13px; }
QPushButton#inline:hover { color: #F7F7F7; }
QPushButton:disabled, QToolButton:disabled { background: #101012; border-color: #232326; color: #777780; }
QPushButton#quiet:disabled { background: transparent; border: none; color: #777780; }
QTableWidget { background: #0B0B0B; alternate-background-color: #101012; border: none; gridline-color: transparent; selection-background-color: #291012; selection-color: #F7F7F7; }
QTableWidget::item { padding: 6px 10px; border: none; }
QTableWidget::item:selected { background: #291012; border: none; }
QHeaderView { background: #0B0B0B; }
QHeaderView::section { background: #0B0B0B; color: #ACACB5; font-size: 12px; padding: 10px; border: none; border-bottom: 1px solid #252528; }
QProgressBar { border: none; border-radius: 3px; background: #202023; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: #6E0808; border-radius: 3px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #55555D; border-radius: 4px; background: #121214; }
QCheckBox::indicator:checked { background: #6E0808; border-color: #8E2C2C; image: url(CHECK_PATH); }
QSplitter::handle { background: #252528; width: 1px; margin: 18px 0; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #3B3B40; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QMenu { background: #171719; border: 1px solid #303034; border-radius: 8px; padding: 5px; }
QMenu::item:selected { background: #4A0404; }
QToolTip { background: #171719; color: #F7F7F7; border: 1px solid #303034; padding: 5px; }
""".replace("CHECK_PATH", (ASSETS / "check.svg").as_posix()).replace("ARROW_PATH", (ASSETS / "chevron.svg").as_posix())
