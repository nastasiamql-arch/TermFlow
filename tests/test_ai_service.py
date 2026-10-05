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
