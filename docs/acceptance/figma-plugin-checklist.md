# AI semantic Figma workflow release evidence

This record separates reproducible automated evidence from administrator and desktop acceptance. It contains no access tokens, prompts, node text, screenshots, raw provider responses, or other fixture content. A `PASS (automated)` entry is not evidence that a real provider, Figma Desktop, or FairyGUI was exercised.

## Release candidate

| Field | Recorded value |
|---|---|
| Evidence date/time zone | 2026-08-03, Asia/Shanghai |
| Candidate source commit | `a7630c8130a46eb05db56383ea578a7c5b3b268b` (`test: prove semantic AI delivery output`) |
| Evidence operator | Codex automated verification only; no administrator or desktop tester |
| Automated artifact | `packaging/figma-plugin/dist/Figma-to-FairyGUI-plugin.zip` (local ignored evidence artifact, 118405 bytes) |
| Automated artifact SHA-256 | `74e5ea8dc53d139956a2295f2943839f6d196ddbb22191c5b03c5e042f7ab359` |
| ZIP members | Exactly `INSTALL.md`, `code.js`, `manifest.json`, `ui.html` |
| Automated build configuration | Public test placeholders: `https://fgui.corp.example`, plugin ID `123456789`, and the non-secret test token marker used by `build.check.mjs` |
| Deployment build | **PENDING** - the automated artifact is not built with an approved internal origin, production plugin ID, or deployment token and must not be rolled out |

## Automated evidence

| Check | Status | Reproducible evidence |
|---|---|---|
| Python suite | PASS (automated) | `python -m pytest -q --basetemp <local ASCII temp>`: **372 passed, 2 skipped** in 14.01s |
| Python lint | PASS (automated) | `python -m ruff check src tests`: all checks passed |
| Python types | PASS (automated) | `python -m mypy src`: no issues in **37 source files** |
| Figma plugin tests | PASS (automated) | Vitest: **7 files, 109 tests passed** |
| Figma plugin types | PASS (automated) | `tsc --noEmit`: exit 0 |
| Web console tests | PASS (automated) | Vitest: **2 files, 21 tests passed**; the non-failing JSDOM navigation notice remains |
| Web console types | PASS (automated) | `tsc --noEmit`: exit 0 |
| Deterministic plugin build/package | PASS (automated) | Underlying `build:check` Node suite in isolated short-ASCII checkout `C:\Users\momoca\AppData\Local\Temp\f8-20260803231606\repo`: **5 passed, 0 failed**; fresh distribution equality, deterministic ZIP bytes, exact members, fixed timestamps, and adjacent checksum were checked |
| Evidence-file whitespace | PASS (automated) | `git diff --check`: exit 0; this check is repeated after every evidence edit and before commit |

The short-ASCII checkout is required because esbuild embeds source labels affected by the physical Windows checkout and dependency-link paths. The Codex pnpm wrapper also attempted dependency reconciliation instead of executing the script directly, so the successful evidence ran the exact package script body, `node --test scripts/build.check.mjs`, with lockfile-installed dependencies. This is evidence for the five build checks, not a claim that the wrapper command itself passed in this environment.

### Fake-provider scenarios

| Scenario | Status | What the automated harness proves |
|---|---|---|
| `structure_success` | PASS (automated fake) | A fake compatible response applies an observable semantic name and produces a valid XML/ZIP package through the public HTTP workflow |
| `screenshot_success`, consent approved | PASS (automated fake) | Consent causes only the selected-fixture PNG to be exported/uploaded; the second fake response is observable in package output |
| `screenshot_declined` | PASS (automated fake) | No screenshot export/upload occurs and the package is byte-for-byte equal to the deterministic rules-only baseline |
| `ai_failure` | PASS (automated fake) | A forced fake provider failure emits safe fallback diagnostics and returns the rules-only baseline package |
| Safe request logging | PASS (automated fake) | Success, HTTP 429, invalid JSON, and HTTP 500 cases assert that credentials, authorization headers, prompts, node data, screenshot bytes/base64, and raw response bodies are absent |

All AI client tests use `httpx.MockTransport`; plugin end-to-end tests use only a loopback FastAPI child process and the fake semantic service. The default suite received no real AI credential, contacted no real provider, and could not incur a provider charge.

## Administrator provider smoke checks

These checks are release blockers. No real AI credential or administrator-approved company endpoint was available during this evidence run.

| Check | Status | Required next evidence |
|---|---|---|
| Official OpenAI, structure-only, non-sensitive test file | **BLOCKED / PENDING** | Administrator supplies a short-lived least-privilege key and approved model, records only pass/fail plus build ID, confirms a valid package and redacted logs, then disables the credential |
| Company OpenAI-compatible endpoint | **BLOCKED / PENDING** | Administrator supplies the approved HTTPS endpoint and runs structure-only, screenshot-approved, screenshot-declined, and forced-provider-failure deliveries |
| Real-provider log redaction | **BLOCKED / PENDING** | Administrator confirms outcome-only logs without recording keys, prompts, node text, screenshots, headers, or raw responses |
| Credentials disabled after smoke | **BLOCKED / PENDING** | Administrator disables/removes both smoke credentials and records completion without recording their values |

## Figma Desktop and FairyGUI acceptance

Figma Desktop 126.7.10 was observed running, but this session exposes no verifiable desktop-control/import interface or approved test file. No common-path FairyGUI installation was found. No desktop action below was performed.

| Check | Status | Required next evidence |
|---|---|---|
| Import the deployment build in Figma Desktop and verify its single approved HTTPS domain | **PENDING** | Desktop tester records pass/fail, tester, date, deployment build ID, and ZIP SHA-256 |
| Structure-only delivery | **PENDING** | Run with a non-sensitive selection and record outcome only |
| Consented screenshot delivery | **PENDING** | Approve the current test selection only; record outcome only |
| Declined screenshot delivery | **PENDING** | Decline once and confirm completion without screenshot upload |
| Disconnected-provider fallback without credentials | **PENDING** | Disable/disconnect the provider, confirm a safe fallback package, then restore only after the check |
| Create ZIP opens in the supported FairyGUI editor | **BLOCKED / PENDING** | FairyGUI must be installed and a desktop tester must open the generated create package |
| Update ZIP opens and original ZIP remains unchanged | **BLOCKED / PENDING** | Open the generated update package and compare the source ZIP SHA-256 before/after |
| Safe distinct create/update filenames | **PENDING** | Record pass/fail from the actual desktop downloads |

## Rollout decision

**NOT READY FOR ROLLOUT.** Automated evidence passes, but the produced ZIP is a public-placeholder test build and all real-provider and manual Figma/FairyGUI acceptance remains pending. Rollout may proceed only after an administrator replaces the automated artifact with a verified deployment build, records its new SHA-256, and every pending row above has an accountable pass result.
