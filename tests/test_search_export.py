from hashlib import sha256
from pathlib import Path

from termflow.core.search_batch import SearchBatch, aggregate_batch
from termflow.core.search_chunks import split_source
from termflow.core.search_export import format_step_a_result
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE, validate_step_a


def test_formats_both_required_sections_as_tsv():
    new = [["林雪", "หลินเสวี่ย", "หญิง", "ตัวละคร"]]
    update = [["洛川", "ลั่วชวน", "ชาย", "ศิษย์"]]

    text = format_step_a_result(new, update)

    assert text == f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n\n{UPDATE}\n洛川\tลั่วชวน\tชาย\tศิษย์\n"
    assert validate_step_a(text) == (new, update)


def test_empty_category_uses_required_marker():
    text = format_step_a_result([], [])
    assert text == f"{NEW}\n{EMPTY}\n\n{UPDATE}\n{EMPTY}\n"
    assert validate_step_a(text) == ([], [])


def test_export_formatting_never_mutates_source_or_vocab_files(tmp_path: Path):
    source = tmp_path / "source.txt"
    vocab = tmp_path / "vocab.tsv"
    source.write_text("第一段\r\n\r\n第二段", encoding="utf-8")
    vocab.write_text("旧词\tคำเดิม\t-\tหมายเหตุ\r\n", encoding="utf-8")
    before = {
        path: (path.stat().st_mtime_ns, path.stat().st_size, sha256(path.read_bytes()).hexdigest())
        for path in (source, vocab)
    }

    batch = SearchBatch(split_source(source.read_text(encoding="utf-8")))
    for run in batch.runs:
        if run.status.value == "pending":
            assert batch.accept_response(run.chunk.index, f"{NEW}\n{EMPTY}\n{UPDATE}\n{EMPTY}")
    combined = format_step_a_result(*(
        aggregate_batch(batch).new_rows,
        aggregate_batch(batch).update_rows,
    ))
    result = tmp_path / "result.txt"
    result.write_text(combined, encoding="utf-8")

    after = {
        path: (path.stat().st_mtime_ns, path.stat().st_size, sha256(path.read_bytes()).hexdigest())
        for path in (source, vocab)
    }
    assert before == after
