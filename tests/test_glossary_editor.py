from PySide6.QtWidgets import QApplication

from termflow.ui.copyable_table import CopyableTableWidget


def test_glossary_editor_uses_page_theme_and_readable_font():
    app = QApplication.instance() or QApplication([])
    editor = CopyableTableWidget()
    editor.resize(500, 180)
    editor.set_editor_theme(dark=False)
    editor.show()
    app.processEvents()

    light = editor.grab().toImage().pixelColor(400, 100).name()
    assert light == "#ffffff"
    assert editor.font().pointSize() >= 14

    editor.set_editor_theme(dark=True)
    app.processEvents()
    dark = editor.grab().toImage().pixelColor(400, 100).name()
    assert dark == "#1e1e1e"
