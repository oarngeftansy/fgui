# Task 7 Report: End-to-End Proof, Configuration, and Redaction

## Status

Complete. The AI semantic service can now be configured explicitly, fails closed when enabled with incomplete or unsafe settings, stays entirely disabled by default, and degrades to deterministic packaging output when the AI service fails.

## Delivered

- Added formal environment assembly for enabled/provider/base URL/model/API key/timeout/confidence threshold.
- Enforced HTTPS for both `openai` and `openai_compatible`; disabled mode creates no analyzer and emits no warning.
- Injected the configured analyzer into the real FastAPI application and closed its client when server execution ends or startup fails.
- Added fake OpenAI-compatible structure and screenshot responses through `httpx.MockTransport`; no test can contact or bill a real model endpoint.
- Proved package validity, XML validity, source immutability, screenshot consent approval/decline, and fallback behavior through Python and plugin end-to-end tests.
- Added safe outcome-only request logging and redaction assertions covering success, 429, invalid JSON, and 500 responses. API keys, auth headers, node IDs/text, prompts, screenshot bytes (raw and encoded), and raw response bodies are forbidden from captured logs.
- Added `.env.example` and an administrator smoke procedure for approved internal HTTPS endpoints and non-sensitive fixtures.
- Added the plugin `build:check` script and refreshed the checked-in plugin UI bundle.

## TDD Evidence

- Configuration tests first failed because `semantic_config` did not exist, then passed after implementing the public configuration builder.
- End-to-end tests first failed on missing fake-service selection fixtures and Windows test paths, then passed after wiring the public HTTP APIs and deterministic fixtures.
- Plugin scenarios first failed on missing AI scenario options and screenshot export hooks, then passed against a real FastAPI child process.
- The CLI lifecycle regression test first failed with an unclosed analyzer (`closed == []`), then passed after the server invocation was wrapped in `try/finally`.
- Log tests were strengthened to reject both raw screenshot data and its base64 representation.

## Verification Matrix

- `python -m pytest -q`: **370 passed, 2 skipped** in 13.34s.
- `ruff check src tests`: **passed**.
- `mypy src`: **passed**, 37 source files checked.
- Plugin Vitest: **109 passed** across 7 files, including four real-FastAPI workflow cases.
- Plugin TypeScript `--noEmit`: **passed**.
- Web console Vitest: **21 passed** across 2 files; the existing JSDOM navigation warning remains non-failing.
- Web console TypeScript `--noEmit`: **passed**.
- Deterministic plugin build/package checks: **5 passed**. Because esbuild embeds source labels derived from the checkout path, the equality check cannot be run reliably from the non-ASCII/long worktree path. The same exact tree and lockfile dependencies were copied to a short ASCII checkout, the checked bundle was regenerated there, and all five build checks passed; the temporary checkout was then removed.
- `git diff --check`: **passed** (Git emitted only expected LF/CRLF conversion notices).

## Self-Review

Two review axes were applied manually because the available agent slots were already occupied:

1. Requirements and product behavior: configuration completeness, provider safety, default-off behavior, consent boundaries, fallback packaging, public API usage, and no-network test guarantees.
2. Engineering quality: lifecycle ownership, secret/log handling, harness isolation, deterministic output, type safety, and full-suite regression risk.

Findings fixed before handoff:

- The configured AI client was not guaranteed to close after Uvicorn returned or failed; a regression test and `finally` cleanup were added.
- The log test covered raw screenshot text but not its encoded wire representation; base64 redaction coverage was added.
- The plugin harness temporarily wrapped `postMessage`; it now uses a scoped active-message session and restores state cleanly.

No remaining actionable Task 7 defects were found.

## Deep User-Pain Audit

The primary job is: an administrator can safely opt in to AI analysis while a designer still receives a valid package when AI is unavailable or declined.

Remaining non-blocking product opportunities:

- Invalid non-secret fields currently collapse to a generic configuration error. A future safe diagnostic could name only the offending environment variable, never its value; acceptance should require every invalid field to be identifiable without exposing the key or URL credentials.
- Below-threshold model suggestions are intentionally ignored but not surfaced. A future sanitized diagnostic/count such as `semantic.low_confidence_ignored` could explain why deterministic analysis won without logging model content.
- Provider smoke validation is manual. A future administrator-only readiness check could report enabled/provider/connectivity state without transmitting project content or returning credentials, prompts, or model bodies.

Immediate high-risk pain—startup ambiguity, lifecycle leakage, sensitive logging, consent bypass, and packaging failure—has been addressed in this task.

## Commit

Planned subject: `test: verify AI semantic delivery fallback`.
