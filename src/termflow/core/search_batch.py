from dataclasses import dataclass, field
from enum import StrEnum

from termflow.core.search_chunks import SourceChunk
from termflow.validators.step_a_validator import validate_step_a


class ChunkStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    VALIDATING = "validating"
    RETRYING = "retrying"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ChunkRun:
    chunk: SourceChunk
    status: ChunkStatus = ChunkStatus.PENDING
    retry_count: int = 0
    raw_response: str = ""
    new_rows: list[list[str]] = field(default_factory=list)
    update_rows: list[list[str]] = field(default_factory=list)
    error: str = ""
    attempts: list[dict] = field(default_factory=list)
    split_depth: int = 0
    usage: dict = field(default_factory=dict)
    result_reused: bool = False


@dataclass(frozen=True)
class RowCandidate:
    category: str
    row: tuple[str, ...]
    chunk_indices: tuple[int, ...]


@dataclass(frozen=True)
class SearchConflict:
    cn: str
    candidates: tuple[RowCandidate, ...]


@dataclass(frozen=True)
class SearchEntry:
    cn: str
    candidate: RowCandidate | None = None
    conflict: SearchConflict | None = None


@dataclass(frozen=True)
class SearchAggregation:
    entries: tuple[SearchEntry, ...]
    conflicts: tuple[SearchConflict, ...]

    @property
    def new_rows(self) -> list[list[str]]:
        return [list(entry.candidate.row) for entry in self.entries if entry.candidate and entry.candidate.category == "new"]

    @property
    def update_rows(self) -> list[list[str]]:
        return [list(entry.candidate.row) for entry in self.entries if entry.candidate and entry.candidate.category == "update"]


class SearchBatch:
    """Own chunk states and validated response snapshots."""

    def __init__(self, chunks: list[SourceChunk]):
        if not chunks:
            raise ValueError("A search must contain at least one chunk")
        self.chunks = tuple(chunks)
        self.runs = [ChunkRun(chunk) for chunk in chunks]
        self.cancellation_requested = False
        for run in self.runs:
            if run.chunk.core_start == run.chunk.core_end or not run.chunk.text.strip():
                run.status = ChunkStatus.COMPLETE

    def _run(self, index: int) -> ChunkRun:
        if index < 1 or index > len(self.runs):
            raise IndexError(index)
        return self.runs[index - 1]

    @property
    def completed_count(self) -> int:
        return sum(run.status == ChunkStatus.COMPLETE for run in self.runs)

    @property
    def all_complete(self) -> bool:
        return self.completed_count == len(self.runs)

    def mark_running(self, index: int) -> None:
        run = self._run(index)
        if run.status not in {ChunkStatus.PENDING, ChunkStatus.RETRYING}:
            raise ValueError(f"Chunk {index} cannot run from {run.status}")
        run.status = ChunkStatus.RUNNING
        run.error = ""

    def mark_validating(self, index: int) -> None:
        run = self._run(index)
        if run.status != ChunkStatus.RUNNING:
            raise ValueError(f"Chunk {index} cannot validate from {run.status}")
        run.status = ChunkStatus.VALIDATING

    def accept_response(self, index: int, raw: str) -> bool:
        run = self._run(index)
        if run.status not in {ChunkStatus.RUNNING, ChunkStatus.VALIDATING, ChunkStatus.PENDING, ChunkStatus.RETRYING}:
            raise ValueError(f"Chunk {index} cannot accept a response from {run.status}")
        run.status = ChunkStatus.VALIDATING
        run.raw_response = raw
        try:
            new_rows, update_rows = validate_step_a(raw)
        except Exception as exc:
            run.status = ChunkStatus.FAILED
            run.error = str(exc)
            run.attempts.append({"raw_response": raw, "valid": False, "error": run.error})
            return False
        run.new_rows = new_rows
        run.update_rows = update_rows
        run.error = ""
        run.status = ChunkStatus.COMPLETE
        run.attempts.append({"raw_response": raw, "valid": True, "new_rows": new_rows, "update_rows": update_rows})
        return True

    def accept_split_responses(self, index: int, responses: list[str]) -> bool:
        """Validate every split response before combining rows into its parent chunk."""
        run = self._run(index)
        new_rows: list[list[str]] = []
        update_rows: list[list[str]] = []
        for raw in responses:
            try:
                new_part, update_part = validate_step_a(raw)
            except Exception as exc:
                run.status = ChunkStatus.FAILED
                run.error = str(exc)
                run.attempts.append({"raw_response": raw, "valid": False, "error": run.error})
                return False
            new_rows.extend(new_part)
            update_rows.extend(update_part)
            run.attempts.append({"raw_response": raw, "valid": True, "new_rows": new_part, "update_rows": update_part})
        run.new_rows = new_rows
        run.update_rows = update_rows
        run.raw_response = "\n\n".join(responses)
        run.error = ""
        run.status = ChunkStatus.COMPLETE
        return True

    def fail_chunk(self, index: int, error: str) -> None:
        run = self._run(index)
        if run.status in {ChunkStatus.COMPLETE, ChunkStatus.CANCELLED}:
            return
        run.status = ChunkStatus.FAILED
        run.error = error
        run.attempts.append({"raw_response": "", "valid": False, "error": error})

    def retry_chunk(self, index: int) -> bool:
        run = self._run(index)
        if run.status != ChunkStatus.FAILED:
            return False
        run.retry_count += 1
        run.status = ChunkStatus.PENDING
        run.error = ""
        return True

    def cancel_pending(self) -> None:
        self.cancellation_requested = True
        for run in self.runs:
            if run.status in {ChunkStatus.PENDING, ChunkStatus.RUNNING, ChunkStatus.VALIDATING, ChunkStatus.RETRYING}:
                run.status = ChunkStatus.CANCELLED

    def resume(self) -> None:
        """Clear cancellation and make unfinished chunks eligible for a resumed run."""
        self.cancellation_requested = False
        for run in self.runs:
            if run.status == ChunkStatus.CANCELLED:
                run.status = ChunkStatus.PENDING

    def aggregate(self) -> SearchAggregation:
        return aggregate_batch(self)


def aggregate_batch(batch: SearchBatch) -> SearchAggregation:
    if not batch.all_complete:
        raise ValueError("all source chunks must pass validation before aggregation")

    ordered_cns: list[str] = []
    candidates_by_cn: dict[str, dict[tuple[str, tuple[str, ...]], list[int]]] = {}
    for run in batch.runs:
        for category, rows in (("new", run.new_rows), ("update", run.update_rows)):
            for row in rows:
                cn = row[0]
                if cn not in candidates_by_cn:
                    ordered_cns.append(cn)
                    candidates_by_cn[cn] = {}
                key = (category, tuple(row))
                chunks = candidates_by_cn[cn].setdefault(key, [])
                if run.chunk.index not in chunks:
                    chunks.append(run.chunk.index)

    entries: list[SearchEntry] = []
    conflicts: list[SearchConflict] = []
    for cn in ordered_cns:
        values = candidates_by_cn[cn]
        candidates = tuple(
            RowCandidate(category, row, tuple(chunk_indices))
            for (category, row), chunk_indices in values.items()
        )
        if len(candidates) == 1:
            entries.append(SearchEntry(cn=cn, candidate=candidates[0]))
        else:
            conflict = SearchConflict(cn=cn, candidates=candidates)
            conflicts.append(conflict)
            entries.append(SearchEntry(cn=cn, conflict=conflict))
    return SearchAggregation(tuple(entries), tuple(conflicts))


def apply_conflict_choices(aggregation: SearchAggregation, choices: dict[str, int]) -> SearchAggregation:
    expected = {conflict.cn for conflict in aggregation.conflicts}
    if set(choices) != expected:
        raise ValueError("resolve every conflict before using combined results")

    selected: dict[str, RowCandidate] = {}
    for conflict in aggregation.conflicts:
        choice = choices[conflict.cn]
        if not isinstance(choice, int) or choice < 0 or choice >= len(conflict.candidates):
            raise ValueError(f"invalid candidate selected for {conflict.cn}")
        selected[conflict.cn] = conflict.candidates[choice]

    entries = tuple(
        SearchEntry(cn=entry.cn, candidate=selected[entry.cn]) if entry.conflict else entry for entry in aggregation.entries
    )
    return SearchAggregation(entries=entries, conflicts=())
