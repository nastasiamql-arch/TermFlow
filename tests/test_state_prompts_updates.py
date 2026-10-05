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


def test_builtin_prompts_match_saved_text():
    from termflow.core.prompts import list_prompts
    from termflow.storage.paths import PROMPTS

    values = {x["id"]: x for x in list_prompts()}
    a = (PROMPTS / "search" / "vocab_extractor_v3.md").read_bytes().decode("utf-8-sig")
    b = (PROMPTS / "polish" / "polish_glossary.md").read_bytes().decode("utf-8-sig")
    assert values["builtin-search"]["content"] == a
    assert values["builtin-polish"]["content"] == b


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
