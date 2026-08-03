# Internal live Figma workflow acceptance checklist

Use a clean release candidate and production internal HTTPS origin. Run desktop and browser Figma separately. Record only pass/fail and operational metadata: never record access tokens, credentials, headers, raw selection data, or secrets.

## Release record

| Field | Value |
|---|---|
| Date (local time) | |
| Tester | |
| Server commit/build | |
| Web build | |
| Plugin ID/build | |
| Internal HTTPS origin | |
| Plugin ZIP SHA-256 verified | |
| ZIP members are exactly manifest.json, code.js, ui.html, INSTALL.md | |

## Figma desktop

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Private organization plugin is available and has one restricted internal HTTPS domain | | |
| Plugin starts without a server URL, pairing code, or Web Console step | | |
| Select frame/component; preflight shows counts, resource estimate, warnings | | |
| Create from an approved template completes and returns a checked FairyGUI package | | |
| Update from an existing FairyGUI ZIP completes and returns a checked package | | |
| Downloaded package opens as expected in a clean test location | | |

## Figma browser

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Private organization plugin starts in browser Figma | | |
| Plugin starts without a server URL, pairing code, or Web Console step | | |
| Frame/component preflight and send complete | | |
| Create and update modes return checked downloadable packages | | |
| Downloaded package opens as expected in a clean test location | | |

## Safety and recovery

| Check | Pass/Fail | Safe notes |
|---|---|---|
| Server HTTPS origin matches the sole plugin manifest domain; fixture jobs are unavailable | | |
| `manifest.json` and `INSTALL.md` contain no deployment access token | | |
| Generated UI and main bundles contain no pairing endpoint, Web Console copy, or development React diagnostic | | |
| No access token, credentials, or codes were saved in this checklist or release notes | | |

Both Figma modes and safety checks must pass before rollout. On failure, stop rollout, preserve only safe logs/build IDs, revoke affected devices if necessary, and follow the deployment rollback procedure.
