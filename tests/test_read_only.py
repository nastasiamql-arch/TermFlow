import hashlib
from pathlib import Path

from termflow.core.prompt_loader import load_prompt
from termflow.core.workflow import Workflow
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE
from termflow.validators.step_b_validator import COPY_READY


def test_vocab_read_is_non_mutating(tmp_path: Path):
    vocab = tmp_path / "vocab.tsv"
    vocab.write_text("CN\tTH\n林雪\tหลินเสวี่ย\n", encoding="utf-8")
    before = (vocab.stat().st_mtime_ns, vocab.stat().st_size, hashlib.sha256(vocab.read_bytes()).hexdigest())
    workflow = Workflow()
    workflow.vocab = vocab.read_text("utf-8-sig")
    workflow.source = "Chinese source text"
    workflow.begin_search()
    new, _ = workflow.accept_search(f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\tศิษย์\n{UPDATE}\n{EMPTY}")
    b_input = workflow.prepare_polish(new)
    workflow.begin_polish()
    b_rows = "\n".join("\t".join([cn, th, "polished note"]) for cn, th, _note in (x.split("\t") for x in b_input.splitlines()))
    workflow.accept_polish(f"{COPY_READY}\n{b_rows}", b_input)
    after = (vocab.stat().st_mtime_ns, vocab.stat().st_size, hashlib.sha256(vocab.read_bytes()).hexdigest())
    assert before == after


def test_search_can_run_again_after_polish():
    workflow = Workflow()
    workflow.source = "Chinese source text"
    workflow.begin_search()
    new, _ = workflow.accept_search(f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\tศิษย์\n{UPDATE}\n{EMPTY}")
    b_input = workflow.prepare_polish(new)
    workflow.begin_polish()
    b_rows = "\n".join("\t".join([cn, th, "polished note"]) for cn, th, _note in (x.split("\t") for x in b_input.splitlines()))
    workflow.accept_polish(f"{COPY_READY}\n{b_rows}", b_input)

    workflow.begin_search()
    assert workflow.state.current.value == "SEARCH_RUNNING"
    new_again, _ = workflow.accept_search(f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\tศิษย์ใหม่\n{UPDATE}\n{EMPTY}")
    assert new_again[0][3] == "ศิษย์ใหม่"


def test_prompt_loader_preserves_source(tmp_path: Path):
    p = tmp_path / "prompt.md"
    p.write_bytes(b"Exact\r\nPrompt\r\n")
    text, digest = load_prompt(p)
    assert text == "Exact\r\nPrompt\r\n"
    assert len(digest) == 64


def test_polish_accepts_prompt_b_analysis_and_fenced_copy_ready_tsv():
    workflow = Workflow()
    selected = [["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์สำนัก"]]
    workflow.begin_search()
    workflow.accept_search(f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก\n{UPDATE}\n{EMPTY}")
    b_input = workflow.prepare_polish(selected)
    workflow.begin_polish()
    response = (
        "[Genre: XIANXIA]\nAnalysis and change summary.\n"
        f"{COPY_READY}\n```text\n林雪\tหลินเสวี่ย\tศิษย์สำนัก\n```"
    )

    assert workflow.accept_polish(response, b_input) == [["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์สำนัก"]]
