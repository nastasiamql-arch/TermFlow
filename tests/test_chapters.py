from pathlib import Path

import pytest

from termflow.core.chapters import find_chapters, join_chapters


def _write(folder: Path, name: str, body: str) -> None:
    (folder / name).write_text(body, encoding="utf-8")


def test_chapter_files_natural_sort_and_filter(tmp_path):
    for name in ("0010.txt", "0002.txt", "0001.txt", "notes.json", "0030.MD", "0003"):
        _write(tmp_path, name, "正文")
    chapters = find_chapters(tmp_path)
    assert [c.name for c in chapters] == ["0001.txt", "0002.txt", "0003", "0010.txt", "0030.MD"]


def test_combination_preserves_order_and_full_content(tmp_path):
    _write(tmp_path, "0001.txt", "林雪在第一章。\n第二行")
    _write(tmp_path, "0002.txt", "洛川在第二章。")
    text = join_chapters(find_chapters(tmp_path))
    assert text.index("林雪") < text.index("洛川")
    assert text.count("===== SOURCE FILE:") == 2
    assert "第二行" in text


def test_empty_or_invalid_chapters_are_not_silently_skipped(tmp_path):
    with pytest.raises(ValueError):
        join_chapters([])
    _write(tmp_path, "0001.txt", "    ")
    with pytest.raises(ValueError, match="ว่างเปล่า"):
        join_chapters(find_chapters(tmp_path))
    (tmp_path / "0001.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="อ่านบท"):
        join_chapters(find_chapters(tmp_path))


def test_gui_chapter_selection_and_range(tmp_path, qapp, monkeypatch):
    from termflow import main as app_main
    from termflow.storage.settings import Settings

    monkeypatch.setattr(app_main, "load_settings", lambda: Settings(check_updates_on_startup=False))
    for n in range(1, 6):
        _write(tmp_path, f"{n:04}.txt", f"第{n}章\n")
    window = app_main.MainWindow(check_updates=False)
    try:
        window.chapter_folder = tmp_path
        window.refresh_chapters()
        assert window.chapter_list.count() == 5
        assert window.source_editor.toPlainText() == ""
        window.first_chapter.setValue(2)
        window.last_chapter.setValue(4)
        window.select_chapter_range()
        selected = [c.name for c in window.selected_chapters()]
        assert selected == ["0002.txt", "0003.txt", "0004.txt"]
        source = window.source_editor.toPlainText()
        assert "第2章" in source and "第4章" in source
        assert "第1章" not in source
        _write(tmp_path, "0002.txt", "第二章改แล้ว")
        assert "第二章改แล้ว" in join_chapters(window.selected_chapters())
        window.set_all_chapters(False)
        assert window.selected_chapters() == []
        assert window.source_editor.toPlainText() == ""
        window.set_all_chapters(True)
        assert len(window.selected_chapters()) == 5
        qapp.processEvents()
    finally:
        window.close()
