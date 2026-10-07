import httpx
import pytest

from termflow.ai.base import GenerateRequest
from termflow.ai.service import HTTPProvider


def test_compatible_base_url_adds_v1_for_models_and_chat(monkeypatch):
    called = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "example-model"}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, headers):
            called.append((url, headers))
            return Response()

    monkeypatch.setattr("termflow.ai.service.httpx.Client", Client)
    provider = HTTPProvider("secret", "example-model", base_url="https://api.maxplus-ai.cc")
    provider.kind = "compatible"

    assert provider.list_models() == ["example-model"]
    assert called[0][0] == "https://api.maxplus-ai.cc/v1/models"
    assert provider.endpoint() == "https://api.maxplus-ai.cc/v1/chat/completions"


def test_compatible_pool_path_keeps_path_and_does_not_duplicate_v1():
    provider = HTTPProvider("secret", "model", base_url="https://api.example.test/pool/v1/")
    provider.kind = "compatible"

    assert provider.api_v1_base() == "https://api.example.test/pool/v1"
    assert provider.endpoint() == "https://api.example.test/pool/v1/chat/completions"


def test_provider_uses_exponential_backoff_for_rate_limit(monkeypatch):
    provider = HTTPProvider("secret", "model", retries=2)
    request = GenerateRequest(prompt="p")
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
    failure = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
    calls = iter([failure, failure, "ok"])
    waits = []

    def generate_once(_request):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(provider, "_generate_once", generate_once)
    monkeypatch.setattr(provider.cancelled, "wait", lambda seconds: waits.append(seconds) or False)

    assert provider.generate(request) == "ok"
    assert waits == [1, 2]


def test_provider_does_not_retry_non_retriable_status(monkeypatch):
    provider = HTTPProvider("secret", "model", retries=3)
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.test"))
    failure = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)
    calls = []

    def generate_once(_request):
        calls.append(True)
        raise failure

    monkeypatch.setattr(provider, "_generate_once", generate_once)
    with pytest.raises(httpx.HTTPStatusError):
        provider.generate(GenerateRequest(prompt="p"))
    assert len(calls) == 1


def test_new_provider_config_has_long_response_timeout_and_no_retries():
    from termflow.ai.service import ProviderConfig

    config = ProviderConfig()
    assert config.timeout == 900
    assert config.retries == 0


def test_usage_is_preserved_and_normalized_when_available(monkeypatch):
    observed = []
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
                          "prompt_tokens_details": {"cached_tokens": 3}},
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            }

    class Client:
        def __init__(self, **kwargs):
            self.timeout = kwargs["timeout"]
            observed.append(self.timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr("termflow.ai.service.httpx.Client", Client)
    provider = HTTPProvider("secret", "model")
    assert provider.generate(GenerateRequest(prompt="p")) == "ok"
    assert provider.last_usage["prompt_tokens"] == 12
    assert provider.normalized_usage() == {
        "input_tokens": 12, "output_tokens": 5, "cached_input_tokens": 3, "total_tokens": 17
    }
    assert provider.finish_reason == "stop"
    assert provider.request_count == 1
    assert observed[0].read == 900
    assert observed[0].connect == 30
    assert observed[0].write == 60
    assert observed[0].pool == 30


def test_provider_does_not_repeat_read_timeout_before_search_can_split(monkeypatch):
    provider = HTTPProvider("secret", "model", retries=2)
    calls = []

    def generate_once(_request):
        calls.append(True)
        raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(provider, "_generate_once", generate_once)
    with pytest.raises(httpx.ReadTimeout):
        provider.generate(GenerateRequest(prompt="p"))

    assert len(calls) == 1


def test_provider_cancellation_interrupts_retry_backoff(monkeypatch):
    provider = HTTPProvider("secret", "model", retries=2)
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
    failure = httpx.HTTPStatusError("rate limited", request=response.request, response=response)

    def generate_once(_request):
        raise failure

    def cancel_during_wait(_seconds):
        provider.cancelled.set()
        return True

    monkeypatch.setattr(provider, "_generate_once", generate_once)
    monkeypatch.setattr(provider.cancelled, "wait", cancel_during_wait)
    with pytest.raises(InterruptedError, match="Request cancelled"):
        provider.generate(GenerateRequest(prompt="p"))
