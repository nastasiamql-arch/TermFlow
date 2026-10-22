# TermFlow — Prompt-driven Edition

TermFlow is a Windows desktop application for Chinese-to-Thai terminology extraction and running user-provided prompt files. The interface is a single workspace (no novel profiles, NEW/UPDATE lanes or required polishing step).

## Modes

- **หาศัพท์จาก SOURCE:** Uses the included SOURCE-ONLY V3 glossary prompt. Supply Chinese SOURCE, then Run. Validates one code block containing `CN<TAB>TH<TAB>SEX<TAB>NOTE`. Save as UTF-8 TSV without Markdown fences, or copy all/selected rows.
- **รันตามไฟล์ Prompt:** Select any UTF-8 `.md` or `.txt` prompt; the selected file content is sent verbatim as the system prompt for that run. General prompts produce raw responses rather than being coerced into the old STEP A schema. If a selected prompt matches the supported SOURCE-ONLY V3 contract, V3 structure validation still applies.

A SOURCE must be provided in both modes. It can be loaded from `.txt` / `.md` or pasted in the editor. No old vocabulary file is used. Prompt file and SOURCE are never written by the application.

## Usage

1. Open **ตั้งค่า API**. Choose OpenAI, Anthropic, Gemini or OpenAI-compatible provider; set model ID, API key, timeout, output tokens and context window.
2. Select the desired mode and prompt. The user's uploaded **VOCAB EXTRACTOR V3 — SOURCE-ONLY** is bundled as the default prompt.
3. Open/paste Chinese SOURCE and click **เริ่มทำงาน**.
4. Inspect the terminology table or raw model response; use Copy or Save.

The program sends the *complete* SOURCE and chosen prompt in one request. If its conservative estimated token budget exceeds the configured context window, it stops **before** sending and asks for a larger model context or smaller SOURCE. It does not secretly split the novel; independent chunks would violate the prompt's read-before-extraction contract. Exact provider limits differ; output truncation (length/MAX_TOKENS) prevents marking the run complete.

The V3 validator checks structure, SEX codes, the presence of each CN string in SOURCE, and identical duplicate rows. It does **not** claim to automatically validate all semantic translation decisions. Raw responses remain visible for inspection if validation fails.

## History, settings, and upgrades

API keys are stored via OS keyring/Windows Credential Manager. Validated outputs may be cached using prompt/source/model identity. History snapshots include exact prompt text and SHA-256, plus raw response. Legacy history and profile files are not deleted during upgrade; profile workflow is simply unused by the new UI.

The app checks for stable GitHub Releases and can download `TermFlow-Setup-x64.exe`, verify its `.sha256` asset, and launch the installer **after closing the app**. Installation remains interactive and user-level. Releases build via GitHub Actions on version-matched `v*` tags. A normal git push to main does **not** publish a Windows installer; a tagged release is required.

## Build

Requires Windows, Python 3.12+, and Inno Setup 6 for packaging:

```powershell
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
ruff check src tests
pytest -q
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/package.ps1
```

Output: `dist/TermFlow.exe` and `installer/output/TermFlow-Setup-x64.exe`.

## Safety

No automatic writes to SOURCE, prompt files or vocabulary data. Save refuses to overwrite a selected SOURCE or prompt path. Changing SOURCE or Prompt invalidates the prior result. Cache and history remain local. Provider API calls transmit the selected prompt and SOURCE to the chosen service.

## Release process

Bump `src/termflow/version.py`, `pyproject.toml` and `installer/TermFlow.iss` together. Run CI, then push an annotated tag matching the app version, e.g. `v1.2.0`. The release workflow tests, builds Windows installer, generates SHA-256 and publishes the release.
