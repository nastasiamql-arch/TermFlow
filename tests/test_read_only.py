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


def test_prompt_loader_preserves_source(tmp_path: Path):
    p = tmp_path / "prompt.md"
    p.write_bytes(b"Exact\r\nPrompt\r\n")
    text, digest = load_prompt(p)
    assert text == "Exact\r\nPrompt\r\n"
    assert len(digest) == 64
