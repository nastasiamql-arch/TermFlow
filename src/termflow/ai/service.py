import httpx
from pydantic import BaseModel, Field

from termflow.ai.base import AIProvider, GenerateRequest


class ProviderConfig(BaseModel):
    provider: str = "openai"
    model: str = ""
    base_url: str = ""
    timeout: int = Field(default=900, ge=30, le=1800)
    retries: int = Field(default=0, ge=0, le=10)
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
        self.last_request_meta = {"provider": self.kind, "model": self.model}
        self.finish_reason = ""
        self.request_count = 0
        for attempt in range(self.retries + 1):
            self.check_cancelled()
            try:
                self.request_count += 1
                return self._generate_once(request)
            except InterruptedError:
                raise
            except httpx.HTTPStatusError as exc:
                if attempt >= self.retries or exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise
                self._wait_before_retry(attempt)
            except httpx.ReadTimeout:
                # Generation may be billable even when the client times out. Never replay it.
                raise
            except (httpx.ConnectTimeout, httpx.ConnectError):
                if attempt >= self.retries:
                    raise
                self._wait_before_retry(attempt)
        raise RuntimeError("Request failed after retry limit")

    def _wait_before_retry(self, attempt: int) -> None:
        delay = min(2**attempt, 30)
        self.cancelled.wait(delay)
        self.check_cancelled()

    def _generate_once(self, request: GenerateRequest) -> str:
        user = "\n\n".join(
            x
            for x in (
                request.user_input,
                "SOURCE:\n" + request.source if request.source else "",
                "VOCAB (READ ONLY):\n" + request.vocab if request.vocab else "",
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
        timeout = httpx.Timeout(
            connect=min(float(self.timeout), 30.0),
            write=60.0,
            read=float(self.timeout),
            pool=30.0,
        )
        with httpx.Client(timeout=timeout) as client:
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
        self.last_usage = data.get("usageMetadata", {}) if self.kind == "gemini" else data.get("usage", {})
        self.last_request_meta = {"provider": self.kind, "model": self.model}
        self.finish_reason = self._finish_reason(data)
        try:
            if self.kind == "anthropic":
                return "".join(x["text"] for x in data["content"] if x.get("type") == "text")
            if self.kind == "gemini":
                return "".join(x["text"] for x in data["candidates"][0]["content"]["parts"])
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Provider returned an unsupported response format") from exc

    def normalized_usage(self) -> dict[str, int | None]:
        usage = self.last_usage or {}
        if self.kind == "gemini":
            source = {
                "input_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"),
                "cached_input_tokens": usage.get("cachedContentTokenCount"),
                "total_tokens": usage.get("totalTokenCount"),
            }
        else:
            source = {
                "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
                "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
                "cached_input_tokens": usage.get("cached_input_tokens", (usage.get("prompt_tokens_details") or {}).get("cached_tokens")),
                "total_tokens": usage.get("total_tokens"),
            }
        return {key: value if isinstance(value, int) else None for key, value in source.items()}

    def _finish_reason(self, data: dict) -> str:
        try:
            if self.kind == "gemini":
                return str(data["candidates"][0].get("finishReason", ""))
            if self.kind == "anthropic":
                return str(data.get("stop_reason", ""))
            return str(data["choices"][0].get("finish_reason", ""))
        except (KeyError, IndexError, TypeError):
            return ""

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
