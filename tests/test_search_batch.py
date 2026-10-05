import pytest

from termflow.core.search_batch import ChunkStatus, SearchBatch, aggregate_batch, apply_conflict_choices
from termflow.core.search_chunks import split_source
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE


def response(new=None, update=None):
    new_section = EMPTY if new is None else "\n".join(new)
    update_section = EMPTY if update is None else "\n".join(update)
    return f"{NEW}\n{new_section}\n{UPDATE}\n{update_section}"


def make_batch():
    return SearchBatch(split_source("\n\n".join(f"paragraph {i}" for i in range(30))))


def complete_all(batch, responses):
    for chunk in batch.chunks:
        if chunk.text:
            assert batch.accept_response(chunk.index, responses.get(chunk.index, response()))


def test_batch_accepts_only_strictly_valid_per_chunk_results():
    batch = make_batch()
    assert batch.accept_response(1, response(["林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"]))
    assert batch.runs[0].status == ChunkStatus.COMPLETE
    assert batch.runs[0].new_rows == [["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์สำนัก"]]

    assert not batch.accept_response(2, response(["洛川\tลั่วชวน\t???\tศิษย์สำนัก"]))
    assert batch.runs[1].status == ChunkStatus.FAILED
    assert batch.runs[1].raw_response
    assert batch.runs[1].error


def test_incomplete_batch_cannot_be_aggregated_and_failed_chunk_can_retry():
    batch = make_batch()
    batch.accept_response(1, response())
    batch.accept_response(2, response(["bad\trow"]))

    with pytest.raises(ValueError, match="all source chunks must pass"):
        aggregate_batch(batch)

    assert batch.retry_chunk(2)
    assert batch.runs[1].status == ChunkStatus.PENDING
    assert batch.runs[1].retry_count == 1
    assert batch.runs[0].status == ChunkStatus.COMPLETE
    assert batch.accept_response(2, response())


def test_cancel_keeps_completed_chunks_and_cancels_unfinished_chunks():
    batch = make_batch()
    batch.accept_response(1, response())
    batch.cancel_pending()

    assert batch.runs[0].status == ChunkStatus.COMPLETE
    assert all(run.status in {ChunkStatus.COMPLETE, ChunkStatus.CANCELLED} for run in batch.runs)
    with pytest.raises(ValueError, match="all source chunks must pass"):
        aggregate_batch(batch)


def test_aggregate_deduplicates_exact_overlap_rows_and_preserves_source_order():
    batch = make_batch()
    same = "林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"
    other = "洛川\tลั่วชวน\tชาย\tศิษย์สำนัก"
    complete_all(batch, {1: response([same]), 2: response([same, other]), 3: response([other])})

    aggregate = aggregate_batch(batch)

    assert aggregate.new_rows == [same.split("\t"), other.split("\t")]
    assert aggregate.update_rows == []
    assert aggregate.conflicts == ()


def test_aggregate_reports_conflicts_without_choosing_or_merging_candidates():
    batch = make_batch()
    row_a = "林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"
    row_b = "林雪\tหลินเสวี่ย\tยังไม่ยืนยัน\tศิษย์สำนัก"
    update = "林雪\tหลินเสวี่ย2\tหญิง\tศิษย์สำนัก"
    complete_all(batch, {1: response([row_a]), 2: response([row_b]), 3: response(update=[update])})

    aggregate = aggregate_batch(batch)

    assert aggregate.new_rows == []
    assert aggregate.update_rows == []
    assert len(aggregate.conflicts) == 1
    conflict = aggregate.conflicts[0]
    assert conflict.cn == "林雪"
    assert {(candidate.category, candidate.row) for candidate in conflict.candidates} == {
        ("new", tuple(row_a.split("\t"))),
        ("new", tuple(row_b.split("\t"))),
        ("update", tuple(update.split("\t"))),
    }

    resolved = apply_conflict_choices(aggregate, {"林雪": 1})
    assert resolved.new_rows == [row_b.split("\t")]
    assert resolved.update_rows == []


def test_conflict_resolution_requires_valid_choice_for_every_cn():
    batch = make_batch()
    complete_all(
        batch,
        {
            1: response(["林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"]),
            2: response(["林雪\tหลินเสวี่ย2\tหญิง\tศิษย์สำนัก"]),
        },
    )
    aggregate = aggregate_batch(batch)
    with pytest.raises(ValueError, match="resolve every conflict"):
        apply_conflict_choices(aggregate, {})
    with pytest.raises(ValueError, match="invalid candidate"):
        apply_conflict_choices(aggregate, {"林雪": 99})
