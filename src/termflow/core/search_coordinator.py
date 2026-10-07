from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock
from time import monotonic
from typing import Callable

import httpx

from termflow.ai.base import GenerateRequest
from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.search_batch import ChunkRun, ChunkStatus, SearchBatch
from termflow.core.result_cache import ResultCache, cache_key
from termflow.core.local_repair import repair_formatting
from termflow.validators.step_a_validator import validate_step_a

ProgressCallback = Callable[[int, str, str, int, int], None]


class SearchCoordinator:
    """Run every non-empty SOURCE chunk in parallel using independent providers."""

    def __init__(
        self,
        batch: SearchBatch,
        *,
        prompt: str,
        vocab: str,
        config: ProviderConfig,
        api_key: str,
        on_progress: ProgressCallback | None = None,
        provider_factory=create_provider,
    ):
        self.batch = batch
        self.prompt = prompt
        self.vocab = vocab
        self.config = config
        self.api_key = api_key
        self.on_progress = on_progress or (lambda *_args: None)
        self.provider_factory = provider_factory
        self.cancelled = Event()
        self._providers = {}
        self._providers_lock = Lock()
        self.result_cache = ResultCache()

    def cancel(self) -> None:
        self.cancelled.set()
        with self._providers_lock:
            providers = list(self._providers.values())
        for provider in providers:
            provider.cancel()

    def _notify(self, run: ChunkRun, message: str = "") -> None:
        self.on_progress(
            run.chunk.index,
            run.status.value,
            message or run.error,
            len(run.new_rows),
            len(run.update_rows),
        )

    def _run_chunk(self, run: ChunkRun) -> None:
        if self.cancelled.is_set():
            return
        self.batch.mark_running(run.chunk.index)
        self._notify(run)
        try:
            provider = self.provider_factory(self.config, self.api_key)
            with self._providers_lock:
                self._providers[run.chunk.index] = provider
            try:
                started = monotonic()
                try:
                    raw = self._generate_part(provider, run, run.chunk.text, depth=0, suffix="")
                finally:
                    run.duration_seconds += monotonic() - started
                if self.cancelled.is_set():
                    return
                self.batch.mark_validating(run.chunk.index)
                self._notify(run, "กำลังตรวจรูปแบบผลลัพธ์")
                accepted = self.batch.accept_response(run.chunk.index, raw)
            except _SplitCompleted as split_result:
                if self.cancelled.is_set():
                    return
                self.batch.mark_validating(run.chunk.index)
                self._notify(run, "ตรวจผลส่วนย่อย")
                accepted = self.batch.accept_split_responses(run.chunk.index, split_result.responses)
            message = "แก้เฉพาะรูปแบบในเครื่อง · ไม่เรียก API ซ้ำ" if run.origin == "local_repair_no_api" else ""
            self._notify(run, message if accepted else run.error)
        except Exception as exc:
            if not self.cancelled.is_set():
                if "provider" in locals():
                    run.request_count = max(run.request_count, getattr(provider, "request_count", 0))
                    run.usage = {"raw": getattr(provider, "last_usage", {}), **getattr(provider, "normalized_usage", lambda: {})()}
                self.batch.fail_chunk(run.chunk.index, str(exc))
                self._notify(run, run.error)
        finally:
            with self._providers_lock:
                self._providers.pop(run.chunk.index, None)

    def _generate_part(self, provider, run: ChunkRun, source: str, *, depth: int, suffix: str) -> str:
        if self.cancelled.is_set():
            raise InterruptedError("Request cancelled")
        request = GenerateRequest(
            prompt=self.prompt,
            source=source,
            vocab=self.vocab,
            user_input=(
                "Return the requested result only. Do not write or modify files. "
                f"This is SOURCE part {run.chunk.index} of {len(self.batch.runs)}. "
                "Apply the exact system Prompt to every line of this part."
                f"{suffix}"
            ),
        )
        key = cache_key(
            workflow="search-step-a", provider=self.config.provider, base_url=self.config.base_url,
            model=self.config.model, prompt=request.prompt, source=request.source, vocab=request.vocab,
            user_input=request.user_input, validator_version="step-a-v1",
        )
        if getattr(self.config, "reuse_results", True):
            cached = self.result_cache.get(key, validate_step_a)
            if cached is not None:
                run.cache_hit = True
                return cached
        try:
            raw = provider.generate(request)
            run.original_response = raw
            run.request_count += getattr(provider, "request_count", 1)
            run.usage = {"raw": getattr(provider, "last_usage", {}), **getattr(provider, "normalized_usage", lambda: {})()}
            try:
                validate_step_a(raw)
            except Exception:
                repaired = repair_formatting(raw, "A")
                if repaired is None:
                    raise
                validate_step_a(repaired)
                run.original_response = raw
                run.repaired_response = repaired
                run.origin = "local_repair_no_api"
                raw = repaired
            if getattr(self.config, "reuse_results", True) and (not self.api_key or self.api_key not in raw):
                self.result_cache.put(key, raw, validate_step_a)
            return raw
        except httpx.ReadTimeout as exc:
            run.request_count += max(0, getattr(provider, "request_count", 1))
            raise httpx.ReadTimeout(
                f"AI response timeout after {self.config.timeout} seconds. No automatic retry was sent.",
                request=exc.request,
            ) from exc

    @staticmethod
    def _split_source(source: str) -> tuple[str, str]:
        """Split at a nearby line boundary without dropping or duplicating text."""
        midpoint = len(source) // 2
        boundaries = [index + 1 for index, char in enumerate(source) if char == "\n"]
        boundary = min(boundaries, key=lambda item: abs(item - midpoint)) if boundaries else midpoint
        if boundary <= 0 or boundary >= len(source):
            boundary = midpoint
        return source[:boundary], source[boundary:]

    def run(self) -> SearchBatch:
        for run in self.batch.runs:
            if run.status == ChunkStatus.COMPLETE and not run.raw_response:
                self._notify(run, "ไม่มีข้อความในช่วงนี้ · ข้ามการเรียก API")
        pending = [
            run
            for run in self.batch.runs
            if run.status == ChunkStatus.PENDING
            and run.chunk.core_start != run.chunk.core_end
            and run.chunk.text.strip()
        ]
        if pending and not self.cancelled.is_set():
            with ThreadPoolExecutor(max_workers=min(10, len(pending)), thread_name_prefix="termflow-search") as pool:
                futures = [pool.submit(self._run_chunk, run) for run in pending]
                for future in as_completed(futures):
                    future.result()
        if self.cancelled.is_set():
            self.batch.cancel_pending()
            for run in self.batch.runs:
                if run.status == ChunkStatus.CANCELLED:
                    self._notify(run, "Cancelled")
        return self.batch


class _SplitCompleted(Exception):
    def __init__(self, responses: list[str]):
        self.responses = responses
