from threading import Barrier, Event, Lock, Thread

from termflow.ai.base import GenerateRequest
from termflow.ai.service import ProviderConfig
from termflow.core.search_batch import ChunkStatus, SearchBatch
from termflow.core.search_chunks import split_source
from termflow.core.search_coordinator import SearchCoordinator
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE


def valid_response(cn=""):
    row = f"{cn}\tไทย\t-\tnote" if cn else EMPTY
    return f"{NEW}\n{row}\n{UPDATE}\n{EMPTY}"


class RecordingProvider:
    def __init__(self, requests, lock, barrier=None, fail_once=None):
        self.requests = requests
        self.lock = lock
        self.barrier = barrier
        self.fail_once = fail_once if fail_once is not None else set()
        self.was_cancelled = False

    def generate(self, request: GenerateRequest):
        with self.lock:
            self.requests.append(request)
            part = next((index for index in range(1, 11) if f"part {index} of 10" in request.user_input), 0)
            should_fail = part in self.fail_once
            if should_fail:
                self.fail_once.remove(part)
        if self.barrier:
            self.barrier.wait(timeout=5)
        if should_fail:
            raise RuntimeError("temporary failure")
        return valid_response()

    def cancel(self):
        self.was_cancelled = True


def make_batch():
    return SearchBatch(split_source("\n\n".join(f"paragraph {index} has enough source text" for index in range(40))))


def test_sends_ten_distinct_parts_in_parallel_with_exact_prompt_and_vocab():
    batch = make_batch()
    requests = []
    lock = Lock()
    barrier = Barrier(10)
    coordinator = SearchCoordinator(
        batch,
        prompt="EXACT PROMPT A\nKeep all original instructions.",
        vocab="READ ONLY VOCAB",
        config=ProviderConfig(provider="compatible", model="test"),
        api_key="test-secret",
        provider_factory=lambda *_: RecordingProvider(requests, lock, barrier),
    )

    coordinator.run()

    assert len(requests) == 10
    assert {request.prompt for request in requests} == {"EXACT PROMPT A\nKeep all original instructions."}
    assert {request.vocab for request in requests} == {"READ ONLY VOCAB"}
    assert len({request.source for request in requests}) == 10
    assert all(run.status == ChunkStatus.COMPLETE for run in batch.runs)


def test_failures_are_isolated_and_retry_only_failed_chunk():
    batch = make_batch()
    requests = []
    lock = Lock()

    fail_once = {3}
    def factory(*_):
        return RecordingProvider(requests, lock, fail_once=fail_once)

    SearchCoordinator(
        batch,
        prompt="prompt",
        vocab="vocab",
        config=ProviderConfig(model="test"),
        api_key="secret",
        provider_factory=factory,
    ).run()
    assert batch.runs[2].status == ChunkStatus.FAILED
    assert sum(run.status == ChunkStatus.COMPLETE for run in batch.runs) == 9
    assert batch.retry_chunk(3)
    SearchCoordinator(
        batch,
        prompt="prompt",
        vocab="vocab",
        config=ProviderConfig(model="test"),
        api_key="secret",
        provider_factory=lambda *_: RecordingProvider(requests, lock),
    ).run()
    assert batch.all_complete
    assert len(requests) == 11
    assert sum("part 3 of 10" in request.user_input for request in requests) == 2


def test_notifies_progress_and_skips_empty_core_ranges():
    batch = SearchBatch(split_source("", count=10, overlap_units=0))
    events = []
    coordinator = SearchCoordinator(
        batch,
        prompt="p",
        vocab="",
        config=ProviderConfig(model="test"),
        api_key="secret",
        on_progress=lambda *event: events.append(event),
        provider_factory=lambda *_: RecordingProvider([], Lock()),
    )

    coordinator.run()

    assert batch.all_complete
    assert len(events) == 10
    assert all("ข้ามการเรียก API" in event[2] for event in events)


def test_cancel_fans_out_to_all_active_providers_and_never_completes_batch():
    batch = make_batch()
    all_started = Event()
    lock = Lock()
    providers = []

    class BlockingProvider(RecordingProvider):
        def __init__(self):
            super().__init__([], Lock())
            self.cancel_event = Event()

        def generate(self, request):
            with lock:
                providers.append(self)
                if len(providers) == 10:
                    all_started.set()
            self.cancel_event.wait(timeout=5)
            raise InterruptedError("Request cancelled")

        def cancel(self):
            self.cancel_event.set()

    coordinator = SearchCoordinator(
        batch,
        prompt="p",
        vocab="v",
        config=ProviderConfig(model="test"),
        api_key="secret",
        provider_factory=lambda *_: BlockingProvider(),
    )
    worker = Thread(target=coordinator.run)
    worker.start()
    assert all_started.wait(timeout=5)
    coordinator.cancel()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(providers) == 10
    assert all(provider.cancel_event.is_set() for provider in providers)
    assert batch.cancellation_requested
    assert not batch.all_complete
    assert all(run.status == ChunkStatus.CANCELLED for run in batch.runs)
    batch.resume()
    assert not batch.cancellation_requested
    assert all(run.status == ChunkStatus.PENDING for run in batch.runs)
