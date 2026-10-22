import pytest

from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.errors import ValidationError
from termflow.core.prompt_execution import (
    ensure_complete_finish,
    make_request,
    parse_v3_output,
    serialize_rows,
    snapshot_prompt,
    validate_v3_output,
)
from termflow.storage.settings import Settings

PROMPT = "# VOCAB EXTRACTOR V3 — SOURCE-ONLY\nCN<TAB>TH<TAB>SEX<TAB>NOTE"


def test_prompt_snapshot_v3_and_plain_modes():
    assert snapshot_prompt(PROMPT).kind == "source-only-v3"
    assert snapshot_prompt("Return a poem.").kind == "raw"


def test_source_only_request_has_no_vocab_or_injected_commands():
    request = make_request(snapshot_prompt(PROMPT), "林雪入城")
    assert request.prompt == PROMPT
    assert request.source == "林雪入城"
    assert request.vocab == ""
    assert request.user_input == ""


def test_v3_returns_only_four_columns_and_preserves_same_cn_separate_senses():
    raw = "```text\n林雪\tหลินเสวี่ย\tหญิง\tชื่อบุคคล\n林雪\tป่าหิมะ\t-\tชื่อสถานที่\n```"
    rows = validate_v3_output(raw, "林雪入城; 林雪")
    assert len(rows) == 2
    assert serialize_rows(rows).count("\n") == 2


@pytest.mark.parametrize("raw", [
    "=== คำศัพท์ใหม่ ===\n林雪\tหลินเสวี่ย\tหญิง\tชื่อบุคคล",
    "before\n```text\n林雪\tหลินเสวี่ย\tหญิง\tชื่อบุคคล\n```",
    "```text\n林雪\tหลินเสวี่ย\tยังไม่ยืนยัน\tชื่อบุคคล\n```",
    "```text\n林雪\tหลินเสวี่ย\tหญิง\n```",
    "```text\n不存在\tคำแปล\t-\tไม่อยู่ในต้นฉบับ\n```",
])
def test_v3_rejects_nonconforming_output(raw):
    with pytest.raises(ValidationError):
        validate_v3_output(raw, "林雪")


def test_output_truncation_is_not_complete():
    with pytest.raises(ValidationError):
        ensure_complete_finish("MAX_TOKENS")
    with pytest.raises(ValidationError):
        ensure_complete_finish("length")
    ensure_complete_finish("stop")


def test_settings_backwards_compatible_and_output_tokens_configurable():
    assert Settings.model_validate({"model": "test", "search_chunks": 3}).max_output_tokens == 8192
    assert ProviderConfig(max_output_tokens=20000).max_output_tokens == 20000


def test_provider_request_source_only_with_configurable_output(monkeypatch):
    from termflow.ai.base import GenerateRequest

    config = ProviderConfig(provider="openai", model="example", max_output_tokens=20000)
    provider = create_provider(config, "secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, _url, headers, json):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("termflow.ai.service.httpx.Client", FakeClient)
    assert provider.generate(GenerateRequest(prompt="Exact", source="你好")) == "ok"
    assert captured["json"]["messages"][0]["content"] == "Exact"
    assert "VOCAB" not in captured["json"]["messages"][1]["content"]
    assert captured["json"]["max_tokens"] == 20000


def test_parser_recovers_unfenced_complete_tsv_without_modifying_cells():
    raw = "林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n青云宗\tสำนักชิงอวิ๋น\t-\tชื่อสำนัก"
    rows, recovered = parse_v3_output(raw, "林雪 青云宗")
    assert recovered is True
    assert serialize_rows(rows).rstrip("\n") == raw
    assert len(rows) == 2


def test_parser_accepts_plaintext_fence_and_preserves_values():
    raw = "```plaintext\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n```"
    rows, recovered = parse_v3_output(raw, "林雪")
    assert recovered is True
    assert rows == [["林雪", "หลินเสวี่ย", "หญิง", "ตัวละคร"]]


def test_parser_keeps_correct_v3_response_unchanged():
    raw = "```text\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n```"
    rows, recovered = parse_v3_output(raw, "林雪")
    assert recovered is False
    assert rows[0][1] == "หลินเสวี่ย"


@pytest.mark.parametrize("raw", [
    "Here is the output:\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร",
    "林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\nExplanation:",
    "```text\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร",
    "```text\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n```\nExtra prose",
    "```text\n林雪\tหลินเสวี่ย\tหญิง\tตัวละคร\n```\n```text\n青云宗\tสำนัก\t-\tชื่อสำนัก\n```",
    "林雪\tหลินเสวี่ย\tยังไม่ยืนยัน\tตัวละคร",
    "不存在\tชื่อที่ไม่มี\t-\tผิด",
])
def test_parser_rejects_ambiguous_incomplete_or_semantically_invalid_tsv(raw):
    with pytest.raises(ValidationError):
        parse_v3_output(raw, "林雪 青云宗")
