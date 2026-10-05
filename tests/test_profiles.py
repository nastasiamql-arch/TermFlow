from termflow.storage.profiles import (
    create_profile,
    delete_profile,
    file_snapshot,
    load_profiles,
    set_active_profile,
    update_profile,
)


def test_profiles_remember_selected_files_and_settings_atomically(tmp_path, monkeypatch):
    import termflow.storage.profiles as profiles

    monkeypatch.setattr(profiles, "APPDATA", tmp_path)
    load_profiles()
    profile = create_profile("นิยายเรื่องหนึ่ง")
    update_profile(
        profile.id,
        source_path="C:/novels/chapter.txt",
        vocab_path="C:/novels/vocab.tsv",
        search_chunks=3,
        selected_search_prompt="builtin-search",
    )
    set_active_profile(profile.id)

    saved = load_profiles()
    selected = next(item for item in saved.profiles if item.id == profile.id)
    assert saved.active_profile_id == profile.id
    assert selected.name == "นิยายเรื่องหนึ่ง"
    assert selected.source_path == "C:/novels/chapter.txt"
    assert selected.vocab_path == "C:/novels/vocab.tsv"
    assert selected.search_chunks == 3
    assert selected.selected_search_prompt == "builtin-search"
    assert not profiles.profiles_path().with_suffix(".tmp").exists()


def test_deleting_active_profile_selects_remaining_profile(tmp_path, monkeypatch):
    import termflow.storage.profiles as profiles

    monkeypatch.setattr(profiles, "APPDATA", tmp_path)
    first = create_profile("First")
    second = create_profile("Second")
    set_active_profile(first.id)

    delete_profile(first.id)

    saved = load_profiles()
    assert [item.id for item in saved.profiles] == [second.id]
    assert saved.active_profile_id == second.id


def test_file_snapshot_reads_utf8_bom_and_detects_changed_content(tmp_path):
    source = tmp_path / "chapter.txt"
    source.write_text("第一章\nสวัสดี", encoding="utf-8-sig")
    first = file_snapshot(source)
    source.write_text("第一章\nสวัสดี โลก", encoding="utf-8-sig")
    second = file_snapshot(source)

    assert first.text == "第一章\nสวัสดี"
    assert first.sha256 != second.sha256
    assert second.text.endswith("โลก")
