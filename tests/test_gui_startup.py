import pytest


@pytest.fixture()
def main_window(qapp, monkeypatch):
    from termflow import main as app_main
    from termflow.storage.settings import Settings

    monkeypatch.setattr(app_main, "load_settings", lambda: Settings(check_updates_on_startup=False))
    monkeypatch.setattr(app_main.MainWindow, "check_updates", lambda *_args, **_kwargs: None)
    window = app_main.MainWindow()
    yield window
    window.close()


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_startup_constructs_editor_and_all_result_widgets(main_window):
    assert main_window.source_editor is not None
    assert main_window.result_table.columnCount() == 4
    assert main_window.raw_view is not None
    assert main_window.run_button is not None
    assert main_window.prompt_path


def test_clear_source_and_change_modes_do_not_crash(main_window, qapp):
    main_window.source_editor.setPlainText("林雪")
    main_window.source_editor.clear()
    assert main_window.source_editor.toPlainText() == ""
    main_window.mode.setCurrentIndex(1)
    main_window.mode.setCurrentIndex(0)
    qapp.processEvents()
    assert main_window.mode.currentData() == "extract"
