import httpx
from pydantic import BaseModel, Field

from termflow.ai.base import AIProvider, GenerateRequest
from termflow.core.errors import ValidationError
from termflow.core.result_cache import cache_key, read_result, write_result
from termflow.validators.step_a_validator import validate_step_a
from termflow.validators.step_b_validator import validate_step_b


class ProviderConfig(BaseModel):
    provider: str = "openai"
    model: str = ""
    base_url: str = ""
    timeout: int = Field(default=90, ge=5, le=600)
    retries: int = Field(default=2, ge=0, le=10)
    reuse_results: bool = True


class HTTPProvider(AIProvider):
    kind = "openai"

    def endpoint(self) -> str:
        return self.api_v1_base() + "/chat/completions"

    def api_v1_base(self) -> str:
        base = self.base_url or {"openai": "https://api.openai.com/v1", "compatible": "http://localhost:11434/v1"}.get(self.kind, "")
        base = base.rstrip("/")
        if not base.rsplit("/", 1)[-1].lower() == "v1":
            base += "/v1"
        return base

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.kind == "anthropic":
            return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", **h}
        return {"Authorization": f"Bearer {self.api_key}", **h}

    def generate(self, request: GenerateRequest) -> str:
        self.last_usage = {}
        self.cache_hit = False
        self.finish_reason = ""
        self.check_cancelled()
        key = cache_key(request, self)
        if request.validation_step and request.reuse_result:
            cached = read_result(key)
            if cached is not None:
                try:
                    self._validate(cached, request)
                except (ValueError, ValidationError):
                    pass
                else:
                    self.cache_hit = True
                    return cached
        for attempt in range(self.retries + 1):
            self.check_cancelled()
            try:
                raw = self._generate_once(request)
                self.check_cancelled()
                if request.validation_step:
                    try:
                        self._validate(raw, request)
                    except (ValueError, ValidationError):
                        pass
                    else:
                        if self.api_key and self.api_key not in raw and self.api_key not in request.model_dump_json():
                            write_result(key, raw)
                return raw
            except InterruptedError:
                raise
            except httpx.HTTPStatusError as exc:
                if attempt >= self.retries or exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise
                self._wait_before_retry(attempt)
            except httpx.ReadTimeout:
                # Replaying a large SOURCE payload rarely fixes a slow response.
                # Let the workflow split this one part and retry smaller inputs.
                raise
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt >= self.retries:
                    raise
                self._wait_before_retry(attempt)
        raise RuntimeError("Request failed after retry limit")

    @staticmethod
    def _validate(raw, request):
        if request.validation_step == "A":
            validate_step_a(raw)
        elif request.validation_step == "B":
            validate_step_b(raw, request.expected_rows)

    def _wait_before_retry(self, attempt: int) -> None:
        delay = min(2**attempt, 30)
        self.cancelled.wait(delay)
        self.check_cancelled()

    def _generate_once(self, request: GenerateRequest) -> str:
        user = "\n\n".join(
            x
            for x in (
                "VOCAB (READ ONLY):\n" + request.vocab if request.vocab else "",
                request.user_input,
                "SOURCE:\n" + request.source if request.source else "",
            )
            if x
        )
        payload = {"model": self.model, "messages": [{"role": "system", "content": request.prompt}, {"role": "user", "content": user}]}
        if self.kind == "anthropic":
            payload = {"model": self.model, "max_tokens": 8192, "system": request.prompt, "messages": [{"role": "user", "content": user}]}
            url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
        elif self.kind == "gemini":
            url = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip(
                "/"
            ) + f"/models/{self.model}:generateContent"
            payload = {"systemInstruction": {"parts": [{"text": request.prompt}]}, "contents": [{"parts": [{"text": user}]}]}
        else:
            url = self.endpoint()
        with httpx.Client(timeout=self.timeout) as client:
            self._active_client = client
            headers = self.headers() if self.kind != "gemini" else {"x-goog-api-key": self.api_key}
            try:
                response = client.post(url, headers=headers, json=payload)
            except httpx.HTTPError:
                if self.cancelled.is_set():
                    raise InterruptedError("Request cancelled")
                raise
            finally:
                self._active_client = None
            response.raise_for_status()
            data = response.json()
            self.last_usage = data.get("usage", data.get("usageMetadata", {}))
        try:
            if self.kind == "anthropic":
                self.finish_reason = data.get("stop_reason", "")
                return "".join(x["text"] for x in data["content"] if x.get("type") == "text")
            if self.kind == "gemini":
                self.finish_reason = data["candidates"][0].get("finishReason", "")
                return "".join(x["text"] for x in data["candidates"][0]["content"]["parts"])
            self.finish_reason = data["choices"][0].get("finish_reason", "")
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Provider returned an unsupported response format") from exc

    def test_connection(self) -> bool:
        self.generate(GenerateRequest(prompt="Reply with OK only.", user_input="OK"))
        return True

    def list_models(self) -> list[str]:
        if self.kind not in {"openai", "compatible"}:
            return []
        base = self.api_v1_base()
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(base.rstrip("/") + "/models", headers=self.headers())
            response.raise_for_status()
            return sorted(x["id"] for x in response.json().get("data", []))


def create_provider(config: ProviderConfig, api_key: str) -> AIProvider:
    cls = type("ConfiguredProvider", (HTTPProvider,), {"kind": config.provider})
    return cls(api_key, config.model, config.timeout, config.base_url, config.retries)
