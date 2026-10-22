"""Prompt-owned execution contract. Never append output instructions to the user's prompt."""
import re
from dataclasses import dataclass
from hashlib import sha256

from termflow.ai.base import GenerateRequest
from termflow.core.errors import ValidationError

V3_TITLE = "VOCAB EXTRACTOR V3 — SOURCE-ONLY"
TRUNCATED_REASONS = {"length", "max_tokens", "max_output_tokens", "max_output", "MAX_TOKENS", "maxOutputTokens"}


@dataclass(frozen=True)
class PromptSnapshot:
    text: str
    digest: str
    kind: str


def snapshot_prompt(text: str) -> PromptSnapshot:
    if not text.strip():
        raise ValueError("Prompt file is empty")
    # Only the known bundled V3 specification activates the strict V3 serializer.
    # Other prompt files remain prompt-owned, and are not forced into NEW/UPDATE or TSV.
    kind = "source-only-v3" if V3_TITLE in text and "CN<TAB>TH<TAB>SEX<TAB>NOTE" in text else "raw"
    return PromptSnapshot(text=text, digest=sha256(text.encode("utf-8")).hexdigest(), kind=kind)


def make_request(prompt: PromptSnapshot, source: str) -> GenerateRequest:
    if not source.strip():
        raise ValueError("SOURCE is empty")
    return GenerateRequest(prompt=prompt.text, source=source, vocab="", user_input="")


def ensure_complete_finish(finish_reason: str) -> None:
    if finish_reason in TRUNCATED_REASONS:
        raise ValidationError(["AI output reached a token limit and is incomplete. View raw response; do not export as complete."])


def validate_v3_output(raw: str, source: str) -> list[list[str]]:
    """Strict V3 structure; no invented or modified translations, no NEW/UPDATE headings."""
    if not raw.strip():
        raise ValidationError(["AI returned an empty response"])
    match = re.fullmatch(r"\s*```(?:text|tsv)?[ \t]*\r?\n([\s\S]*?)\r?\n```\s*", raw, re.IGNORECASE)
    if not match:
        raise ValidationError(["Expected exactly one fenced code block with TSV rows and no surrounding prose"])
    body = match.group(1)
    if not body.strip():
        return []
    rows = []
    seen = set()
    for line_number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            raise ValidationError([f"Line {line_number}: empty line inside TSV"])
        if "```" in line or line.startswith(("- ", "* ")) or line.startswith("==="):
            raise ValidationError([f"Line {line_number}: unexpected heading or Markdown"])
        fields = line.split("\t")
        if len(fields) != 4 or any(not value.strip() for value in fields):
            raise ValidationError([f"Line {line_number}: expected four nonempty fields separated by three real TABs"])
        cn, th, sex, note = fields
        if sex not in {"ชาย", "หญิง", "-"}:
            raise ValidationError([f"Line {line_number}: SEX must be ชาย, หญิง or -"])
        if cn not in source:
            raise ValidationError([f"Line {line_number}: Chinese term is not found verbatim in SOURCE: {cn}"])
        if any(s in line for s in ("【", "】")):
            raise ValidationError([f"Line {line_number}: citation marker contamination"])
        if tuple(fields) in seen:
            raise ValidationError([f"Line {line_number}: identical duplicate TSV row"])
        seen.add(tuple(fields))
        rows.append(fields)
    # Same CN with separately evidenced senses is allowed; do NOT collapse by CN.
    return rows




def parse_v3_output(raw: str, source: str) -> tuple[list[list[str]], bool]:
    """Validate V3, repairing only unambiguous presentation wrappers.

    Return (rows, recovered). The original raw reply is never rewritten.
    Missing closing fences, extra prose and mixed/invalid TSV are never
    silently repaired because they can indicate lost or changed content.
    """
    try:
        return validate_v3_output(raw, source), False
    except ValidationError as original_error:
        if not original_error.details[0].startswith("Expected exactly one fenced code block"):
            raise

    stripped = raw.strip()
    if not stripped:
        raise original_error
    if "```" not in stripped:
        # Unfenced pure TSV is uniquely reparable if all rows validate.
        if "\t" not in stripped:
            raise original_error
        body = stripped
    else:
        # Recognize only equivalent plaintext fence labels, with no extra text.
        match = re.fullmatch(
            r"```(?:plain(?:text)?|txt)[ \t]*\r?\n([\s\S]*?)\r?\n```",
            stripped,
            re.IGNORECASE,
        )
        if not match:
            raise original_error
        body = match.group(1)
    rows = validate_v3_output("```text\n" + body + "\n```", source)
    return rows, True

def serialize_rows(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(row) for row in rows) + ("\n" if rows else "")
