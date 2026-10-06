from pathlib import Path
from time import monotonic, sleep
from zipfile import ZipFile

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from termflow.ai.base import GenerateRequest
from termflow.ai.service import HTTPProvider
from termflow.core.prompt_loader import import_prompt_text
from termflow.core.state_machine import State
from termflow.storage.paths import PROMPTS


def test_cache_reuses_only_valid_exact_requests(tmp_path, monkeypatch):
    import termflow.core.result_cache as cache
    monkeypatch.setattr(cache, "LOCAL", tmp_path)
    provider = HTTPProvider("secret", "model")
    calls = []
    raw = "=== คำศัพท์ใหม่ ===\nCN\tTH\t-\tNOTE\n=== คำศัพท์อัปเดต ===\n— ไม่มีรายการ —"
    monkeypatch.setattr(provider, "_generate_once", lambda req: calls.append(req) or raw)
    request = GenerateRequest(prompt="exact", source="source", vocab="vocab", validation_step="A")
    assert provider.generate(request) == raw
    assert provider.generate(request) == raw
    assert len(calls) == 1 and provider.cache_hit
    for field in ("prompt", "source", "vocab"):
        provider.generate(request.model_copy(update={field: "changed"}))
    assert len(calls) == 4
    provider.generate(request.model_copy(update={"reuse_result": False}))
    assert len(calls) == 5
    provider.model = "other-model"
    provider.generate(request)
    assert len(calls) == 6


def test_invalid_results_are_never_cached(tmp_path, monkeypatch):
    import termflow.core.result_cache as cache
    monkeypatch.setattr(cache, "LOCAL", tmp_path)
    provider = HTTPProvider("secret", "model")
    calls = []
    monkeypatch.setattr(provider, "_generate_once", lambda req: calls.append(req) or "bad")
    request = GenerateRequest(prompt="exact", validation_step="B", expected_rows=[["CN", "TH", "NOTE"]])
    provider.generate(request)
    provider.generate(request)
    assert len(calls) == 2
    assert not list(tmp_path.rglob("*.json"))


def test_import_preserves_utf8_text_and_docx_tabs(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_bytes("คำสั่ง\r\n中文\tไม่ย่อ".encode("utf-8-sig"))
    assert import_prompt_text(path) == "คำสั่ง\r\n中文\tไม่ย่อ"
    docx = tmp_path / "prompt.docx"
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>คำสั่ง</w:t><w:tab/><w:t>中文</w:t><w:br/>'
           '<w:t>เดิม</w:t></w:r></w:p></w:body></w:document>')
    with ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", xml)
    assert import_prompt_text(docx) == "คำสั่ง\t中文\nเดิม"


@pytest.fixture
def window(tmp_path, monkeypatch):
    import termflow.core.history as history
    import termflow.core.prompts as prompts
    import termflow.core.result_cache as cache
    import termflow.main as main
    import termflow.storage.profiles as profiles
    import termflow.storage.settings as settings
    app = QApplication.instance() or QApplication([])
    for module in (prompts, profiles, settings, history):
        monkeypatch.setattr(module, "APPDATA", tmp_path)
    monkeypatch.setattr(cache, "LOCAL", tmp_path)
    monkeypatch.setattr(main, "load_settings", lambda: settings.Settings(show_welcome=False, check_updates_on_startup=False,
                                                                        model="test", polish_model="polish-test",
                                                               search_prompt_path=str(PROMPTS / "search/vocab_extractor_v3.md"),
                                                                        polish_prompt_path=str(PROMPTS / "polish/polish_glossary.md")))
    monkeypatch.setattr(main, "get", lambda _provider: "secret")
    win = main.MainWindow()
    yield win, app
    for thread in (win._thread, win._search_thread):
        if thread and thread.isRunning():
            thread.quit()
            thread.wait(5000)
    win.close()
    app.processEvents()


def test_search_16000_characters_is_one_request(window, monkeypatch):
    win, _app = window
    monkeypatch.setattr(win, "_start_search_worker", lambda: None)
    win.source_view.setPlainText("文" * 16_000)
    win.run_search()
    assert len(win._search_batch.runs) == 1
    assert win._search_batch.runs[0].chunk.text == "文" * 16_000


def test_search_two_chunks_accepts_source_over_16000(window, monkeypatch):
    win, _app = window
    monkeypatch.setattr(win, "_start_search_worker", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    win.settings.search_chunks = 2
    win.source_view.setPlainText("文" * 32_000)
    win.run_search()
    assert win._search_batch is not None
    assert len(win._search_batch.runs) == 2
    assert all(len(run.chunk.text) <= 16_000 for run in win._search_batch.runs)
    chunks = win._search_batch.chunks
    assert chunks[0].core_start == 0
    assert chunks[0].core_end == chunks[1].core_start
    assert chunks[1].core_end == 32_000


def test_too_few_chunks_does_not_start_request_or_change_state(window, monkeypatch):
    win, _app = window
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: messages.append(message))
    win.settings.search_chunks = 1
    win.source_view.setPlainText("文" * 16_001)
    state = win.workflow.state.current
    win.run_search()
    assert win._search_batch is None
    assert win.workflow.state.current == state
    assert "เลือกอย่างน้อย 2 ช่วง" in messages[0]


def test_polish_preflight_failure_does_not_enter_running(window, monkeypatch):
    import termflow.main as main
    win, _app = window
    win.workflow.state.current = State.USER_REVIEW
    win.new_table.fill_rows([["CN", "TH", "หญิง", "NOTE"]])
    win.new_table.select_all_rows(True)
    monkeypatch.setattr(main, "get", lambda _provider: None)
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *_args: None)
    win.run_polish()
    assert win.workflow.state.current == State.POLISH_READY
    assert win._thread is None


def test_prompt_select_saves_unsaved_custom_edits(tmp_path, monkeypatch):
    import termflow.core.prompts as prompts
    from termflow.ui.prompt_manager import PromptManagerDialog
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(prompts, "APPDATA", tmp_path)
    prompt = prompts.create_prompt("new B", "Polish", "old")
    dialog = PromptManagerDialog(category="Polish")
    dialog.refresh(prompt["id"])
    assert dialog.save_button.isEnabled()
    dialog.content.setPlainText("updated exact prompt")
    dialog.select_prompt()
    assert dialog.selected_prompt["content"] == "updated exact prompt"
    assert dialog.selected_prompt["version"] == "2"


def test_polish_retry_waits_for_old_thread_and_restores_sex(window, monkeypatch):
    import termflow.main as main
    win, app = window
    win.workflow.state.current = State.USER_REVIEW
    win.new_table.fill_rows([["CN", "TH", "หญิง", "NOTE"]])
    win.new_table.select_all_rows(True)
    requests = []

    class Provider:
        api_key = "secret"
        def generate(self, request):
            requests.append(request)
            if len(requests) == 1:
                raise RuntimeError("temporary error")
            return "### ผลลัพธ์ TSV\n```tsv\nCN\tTH\tNOTE\n```\nสรุปท้ายผล"

    class RetryBox(QMessageBox):
        def exec(self):
            return 0
        def clickedButton(self):
            return self.buttons()[0]

    configs = []
    monkeypatch.setattr(main, "create_provider", lambda config, _key: configs.append(config) or Provider())
    monkeypatch.setattr(main, "QMessageBox", RetryBox)
    win.run_polish()
    deadline = monotonic() + 5
    while monotonic() < deadline and (win.workflow.state.current != State.FINAL_READY or win._busy_with_ai()):
        app.processEvents()
        sleep(0.005)
    assert win.workflow.state.current == State.FINAL_READY
    assert len(requests) == 2
    assert all(request.source == "" for request in requests)
    assert all(request.prompt == win._selected_prompt["content"] for request in requests)
    assert configs[0].model == "polish-test"
    assert win.workflow.final_rows == [["CN", "TH", "หญิง", "NOTE"]]


def test_search_can_restart_after_final_without_direct_state_assignment():
    from termflow.core.workflow import Workflow
    workflow = Workflow()
    workflow.begin_search()
    workflow.accept_search("=== คำศัพท์ใหม่ ===\nCN\tTH\tหญิง\tNOTE\n=== คำศัพท์อัปเดต ===\n— ไม่มีรายการ —")
    payload = workflow.prepare_polish(workflow.new_rows)
    workflow.begin_polish()
    workflow.accept_polish("CN\tTH\tNOTE", payload)
    assert workflow.state.current == State.FINAL_READY
    workflow.begin_search()
    assert workflow.state.current == State.SEARCH_RUNNING


def test_failed_search_can_be_repaired_locally_without_provider(window, monkeypatch):
    import termflow.main as main
    from termflow.ai.service import ProviderConfig
    from termflow.core.search_batch import SearchBatch
    from termflow.core.search_chunks import split_source

    win, _app = window
    win.workflow.begin_search()
    win.workflow.state.transition(State.SEARCH_FAILED)
    batch = SearchBatch(split_source("เนื้อหานิยาย", 1))
    invalid = "=== คำศัพท์ใหม่ ===\nCN\tTH\tหญิง\t\n=== คำศัพท์อัปเดต ===\n— ไม่มีรายการ —"
    assert not batch.accept_response(1, invalid)
    win._search_batch = batch
    win._search_selected_prompt = win.prompt_file("A")
    win._search_prompt = win._search_selected_prompt["content"]
    win._search_config = ProviderConfig(provider="compatible", model="test")
    win._search_api_key = "secret"
    win.search_progress = main.SearchProgressDialog(win, 1)
    def forbidden(*_args):
        raise AssertionError("Local correction must never invoke API")
    monkeypatch.setattr(main, "create_provider", forbidden)
    win.accept_local_search_edit(1, invalid.replace("หญิง\t\n", "หญิง\tNOTE\n"))
    assert win.workflow.state.current == State.USER_REVIEW
    assert win.workflow.new_rows == [["CN", "TH", "หญิง", "NOTE"]]
    assert batch.runs[0].attempts[0]["raw_response"] == invalid
    assert batch.runs[0].attempts[-1]["origin"] == "user_edit_no_api"
    assert batch.runs[0].retry_count == 0


def test_prompt_selection_is_used_in_actual_polish_request(window, tmp_path, monkeypatch):
    import termflow.main as main
    win, _app = window
    path = tmp_path / "updated-B.md"
    content = "EXACT updated Prompt B\nไม่ย่อ"
    path.write_bytes(content.encode("utf-8"))
    monkeypatch.setattr(main.QFileDialog, "getOpenFileName", lambda *_args: (str(path), ""))
    win.select_prompt_file("B")
    win.workflow.state.current = State.USER_REVIEW
    win.new_table.fill_rows([["CN", "TH", "ชาย", "NOTE"]])
    win.new_table.select_all_rows(True)
    requests = []
    monkeypatch.setattr(win, "start_worker", lambda _provider, request: requests.append(request))
    win.run_polish()
    assert requests[0].prompt == content
    assert requests[0].expected_rows == [["CN", "TH", "NOTE"]]
    assert "INPUT TSV:" in requests[0].user_input
    assert requests[0].allow_polish_removals


def test_shared_prompt_files_survive_profile_switch_and_read_external_changes(window, tmp_path, monkeypatch):
    import termflow.main as main
    from termflow.storage.profiles import create_profile
    win, _app = window
    for step, content in (("A", "EXACT Prompt A\r\n中文"), ("B", "EXACT Prompt B\r\nภาษาไทย")):
        path = tmp_path / f"prompt-{step}.md"
        path.write_bytes(content.encode("utf-8"))
        monkeypatch.setattr(main.QFileDialog, "getOpenFileName", lambda *_args, path=path: (str(path), ""))
        win.select_prompt_file(step)
        assert win.prompt_file(step)["content"] == content
    other = create_profile("Other novel")
    win.switch_profile(other.id)
    assert win.prompt_file("A")["content"] == "EXACT Prompt A\r\n中文"
    assert win.prompt_file("B")["content"] == "EXACT Prompt B\r\nภาษาไทย"
    old = win.prompt_file("B")
    Path(win.settings.polish_prompt_path).write_bytes("UPDATED B\nไม่ย่อ".encode("utf-8"))
    current = win.prompt_file("B")
    assert current["content"] == "UPDATED B\nไม่ย่อ"
    assert current["version"] != old["version"]


def test_missing_shared_prompt_file_does_not_fall_back_to_builtin(window, tmp_path):
    win, _app = window
    win.settings.search_prompt_path = str(tmp_path / "missing.md")
    with pytest.raises(Exception, match="Prompt"):
        win.prompt_file("A")


@pytest.mark.parametrize("approve", [False, True])
def test_removed_rows_gate_final_copy_and_record_review_in_history(window, monkeypatch, approve):
    import termflow.core.history as history
    import termflow.main as main
    win, app = window
    win.workflow.state.current = State.USER_REVIEW
    win.new_table.fill_rows([["CN1", "TH1", "หญิง", "NOTE1"], ["CN2", "TH2", "ชาย", "NOTE2"]])
    win.new_table.select_all_rows(True)
    monkeypatch.setattr(win, "start_worker", lambda *_args: None)
    monkeypatch.setattr(main.PolishRemovalReview, "exec", lambda _self: main.QDialog.Accepted if approve else main.QDialog.Rejected)
    monkeypatch.setattr(main.QMessageBox, "information", lambda *_args: None)
    win.run_polish()
    win.on_response("ตัด CN2 เพราะ duplicate\n=== COPY-READY TSV ===\n```tsv\nCN1\tTH1\tNOTE1\n```")
    record = history.list_history()[0]
    assert record["excluded_rows"][0]["cn"] == "CN2"
    assert record["exclusions_confirmed"] == approve
    app.clipboard().setText("untouched")
    win.copy_final()
    if approve:
        assert app.clipboard().text() == "CN1\tTH1\tหญิง\tNOTE1"
        assert win.workflow.state.current == State.FINAL_READY
    else:
        assert app.clipboard().text() == "untouched"
        assert win.workflow.state.current == State.POLISH_FAILED


def test_legacy_prompt_manager_and_dropdown_are_not_in_main_ui(window):
    from PySide6.QtWidgets import QPushButton
    win, _app = window
    labels = {button.text() for button in win.findChildren(QPushButton)}
    assert "Prompt Manager" not in labels
    assert "Open Prompt หาศัพท์" in labels
    assert "Open Prompt เกลา" in labels
    assert not hasattr(win, "prompt_choices")
