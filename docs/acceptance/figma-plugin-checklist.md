# Internal plugin-only Figma workflow acceptance checklist

Use a clean release candidate and production internal HTTPS origin. Record only pass/fail and operational metadata: never record access tokens, credentials, headers, raw selection data, or secrets. All entries below require real Figma desktop evidence; leave them blank until that evidence exists.

## Release record

| Field | Value |
|---|---|
| Date (local time) | |
| Tester | |
| Server commit/build | |
| Plugin ID/build | |
| Internal HTTPS origin | |
| Plugin ZIP SHA-256 verified | |
| ZIP members are exactly manifest.json, code.js, ui.html, INSTALL.md | |

## Figma desktop (manual acceptance required)

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Private organization plugin is available and has one restricted internal HTTPS domain | | |
| Plugin starts without a server URL, pairing code, or browser-console step | | |
| Select frame/component, refresh current selection; preflight shows new counts, resource estimate, and warnings | | |
| Create from an approved template completes and its downloaded FairyGUI ZIP opens in a clean test location | | |
| Update from one existing FairyGUI ZIP completes, its downloaded ZIP opens in a clean test location, and the original ZIP SHA-256 is unchanged | | |
| Disconnect/reconnect the internal service; retry reports a safe offline error and can complete after reconnect | | |
| Both create and update downloads have distinct, safe ZIP filenames | | |

## Safety and recovery

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Server HTTPS origin matches the sole plugin manifest domain; fixture jobs are unavailable | | |
| `manifest.json` and `INSTALL.md` contain no deployment access token | | |
| Generated UI and main bundles contain no pairing, browser-console copy, `clientStorage`, `/v1/agents/`, or development React diagnostic | | |
| No access token, credentials, or codes were saved in this checklist or release notes | | |

Desktop and safety checks must pass before rollout. On failure, stop rollout, preserve only safe logs/build IDs, and follow the deployment rollback procedure.
