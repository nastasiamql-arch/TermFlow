from termflow.core.state_machine import State, WorkflowState
from termflow.updater.version_check import is_newer


def test_state_machine_rejects_provider_side_transition():
    state = WorkflowState()
    state.transition(State.SOURCE_LOADED)
    state.transition(State.READY_FOR_SEARCH)
    state.transition(State.SEARCH_RUNNING)
    try:
        state.transition(State.POLISH_COMPLETE)
        assert False, "invalid transition should fail"
    except ValueError:
        pass


def test_release_version_comparison():
    assert is_newer("v1.3.0", "1.2.0")
    assert not is_newer("v1.2.0", "1.2.0")
    assert not is_newer("not-a-version", "1.2.0")


def test_new_settings_use_economical_request_defaults():
    from termflow.storage.settings import Settings

    settings = Settings()
    assert settings.search_chunks == 1
    assert settings.retries == 0
    assert settings.timeout == 900
    assert Settings.model_validate({"provider": "openai", "model": "example"}).search_chunks == 1


def test_existing_settings_values_are_preserved():
    from termflow.storage.settings import Settings

    old = Settings.model_validate({"search_chunks": 4, "retries": 2, "timeout": 600})
    assert (old.search_chunks, old.retries, old.timeout) == (4, 2, 600)


def test_builtin_prompts_match_saved_text():
    from termflow.core.prompts import list_prompts
    from termflow.storage.paths import PROMPTS

    values = {x["id"]: x for x in list_prompts()}
    a = (PROMPTS / "search" / "vocab_extractor_v3.md").read_bytes().decode("utf-8-sig")
    b = (PROMPTS / "polish" / "polish_glossary.md").read_bytes().decode("utf-8-sig")
    assert values["builtin-search"]["content"] == a
    assert values["builtin-polish"]["content"] == b


def test_builtin_prompt_bytes_match_frozen_sha256():
    import hashlib
    from termflow.storage.paths import PROMPTS

    assert hashlib.sha256((PROMPTS / "search" / "vocab_extractor_v3.md").read_bytes()).hexdigest() == "0349ca067df731f79a97e78d3936a2364ac5edc22a05199a488918dd0088395d"
    assert hashlib.sha256((PROMPTS / "polish" / "polish_glossary.md").read_bytes()).hexdigest() == "2f321ce4c4dd5eba771b8cda8b828e2fbbd83558f1abd82e34cab29759af156b"


def test_frozen_prompt_directory_uses_pyinstaller_bundle(tmp_path, monkeypatch):
    import termflow.storage.paths as paths

    (tmp_path / "prompts" / "search").mkdir(parents=True)
    (tmp_path / "prompts" / "search" / "vocab_extractor_v3.md").write_text("source prompt", encoding="utf-8")
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)

    assert paths.resolve_prompts_dir() == tmp_path / "prompts"


def test_update_installer_waits_for_termflow_to_exit(tmp_path, monkeypatch):
    import termflow.updater.installer as installer

    calls = []
    monkeypatch.setattr(installer.os, "getpid", lambda: 4321)
    monkeypatch.setattr(installer.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(installer.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    installer.launch_installer(tmp_path / "TermFlow Setup.exe")

    command = calls[0][0][-1]
    assert "Wait-Process -Id 4321" in command
    assert "Start-Process -FilePath $installer" in command
    assert "TermFlow Setup.exe" in command
    assert "-WindowStyle Normal" in command


def test_saved_default_font_size_is_upgraded_for_readability(tmp_path, monkeypatch):
    import termflow.storage.settings as settings

    config = tmp_path / "settings.json"
    config.write_text('{"font_size":11}', encoding="utf-8")
    monkeypatch.setattr(settings, "settings_path", lambda: config)

    assert settings.load_settings().font_size == 12


def test_custom_prompt_edit_and_delete(tmp_path, monkeypatch):
    import termflow.core.prompts as prompts

    monkeypatch.setattr(prompts, "APPDATA", tmp_path)
    item = prompts.create_prompt("Copy", "Search", "Original wording")
    assert item["version"] == "1"
    updated = prompts.save_prompt(item["id"], name="Renamed", content="Updated wording")
    assert updated["version"] == "2"
    assert updated["content"] == "Updated wording"
    prompts.delete_prompt(item["id"])
    assert item["id"] not in {x["id"] for x in prompts.list_prompts()}


def test_history_snapshot_is_atomic_and_keeps_prompt_and_validation(tmp_path, monkeypatch):
    import termflow.core.history as history

    monkeypatch.setattr(history, "APPDATA", tmp_path)
    path = history.save_snapshot(
        {
            "prompt_id": "builtin-search",
            "exact_prompt_text": "Exact prompt",
            "prompt_sha256": "abc123",
            "raw_response": "raw",
            "parsed_result": {"new": []},
            "validation_result": {"passed": True},
        }
    )
    assert not path.endswith(".tmp")
    saved = history.list_history()[0]
    assert saved["exact_prompt_text"] == "Exact prompt"
    assert saved["prompt_sha256"] == "abc123"
    assert saved["raw_response"] == "raw"
    assert saved["validation_result"]["passed"] is True
