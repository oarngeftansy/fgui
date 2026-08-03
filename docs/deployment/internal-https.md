# Internal HTTPS deployment and Figma plugin release runbook

This is an internal deployment only. Its gateway token is a coarse reverse-proxy boundary, not SSO or role management. The production Figma flow has no public Figma-plugin distribution, Web Console, pairing code, server-address entry, or Windows local-agent prerequisite for designers.

## Release ownership and build

- The release owner owns one canonical origin, such as `https://fgui.internal.example`.
- Infrastructure owns internal DNS, a certificate trusted by intended Figma/Agent machines, the reverse proxy, and backups.
- The Figma publisher owns the numeric plugin ID and publishes only to the organization.
- The release owner injects the plugin deployment access token only during the release build and never records it in source, documentation, or a release ticket.

Build from an ASCII-only checkout. The frozen plugin verifier is known to fail in the Chinese-path checkout; use an ASCII clone/copy and leave build scripts unchanged. Set the deployment token only in the release shell; do not paste it into a command history, script, or support record.

```powershell
New-Item -ItemType Directory -Force 'C:\ProgramData\FigmaToFGUI' | Out-Null
if (-not (Test-Path 'C:\ProgramData\FigmaToFGUI\plugin-access-token.txt')) {
  [byte[]]$pluginTokenBytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($pluginTokenBytes)
  [System.IO.File]::WriteAllText('C:\ProgramData\FigmaToFGUI\plugin-access-token.txt', [Convert]::ToBase64String($pluginTokenBytes))
}
cd C:\src\figma-to-fgui
$env:FGUI_SERVER_ORIGIN = 'https://fgui.internal.example'
$env:FIGMA_PLUGIN_ID = '123456789'
$env:FGUI_PLUGIN_ACCESS_TOKEN = Get-Content -Raw 'C:\ProgramData\FigmaToFGUI\plugin-access-token.txt'
pnpm --dir apps/figma-plugin install --frozen-lockfile
pnpm --dir apps/figma-plugin test -- --run
pnpm --dir apps/figma-plugin typecheck
node apps/figma-plugin/scripts/build.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/figma-plugin/build-package.ps1
pnpm --dir apps/web-console install --frozen-lockfile
pnpm --dir apps/web-console build
Get-Content apps/figma-plugin/dist/manifest.json
Get-ChildItem packaging/figma-plugin/dist/Figma-to-FairyGUI-plugin.zip, packaging/figma-plugin/dist/checksums.sha256
```

Check `Test-Path apps/figma-plugin/node_modules/@esbuild/win32-x64/bin/esbuild.exe` after a fresh install. If pnpm reports ignored build scripts, use the release environment’s `pnpm approve-builds` process to approve only the lock-resolved `esbuild` build, then repeat the frozen install. Do not disable that supply-chain policy or replace the binary manually.

The release ZIP is the team-installable import artifact. It contains exactly `manifest.json`, `code.js`, `ui.html`, and `INSTALL.md`; its adjacent `checksums.sha256` records the ZIP hash. Verify the hash before pilot import or organization-private publishing. No npm package or signed Windows Agent installer is shipped. In a controlled release environment, the Python wheel is reproducible with isolated build dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir C:\release\figma-to-fgui-wheels .
Get-ChildItem C:\release\figma-to-fgui-wheels\figma_to_fgui_core-*.whl
```

This creates a wheel for audit or controlled installation; it does not turn the Agent into a signed installer.

## Figma import and private organization publishing

Use Figma desktop to import and publish. For a pilot, extract `Figma-to-FairyGUI-plugin.zip`; in a file, open **Plugins > Development > Import plugin from manifest** and choose its `manifest.json`. To distribute internally use **Plugins > Manage plugins > Development > Publish**, choose **Organization** in **Publish to**, and confirm the network-access display is restricted to the one canonical internal origin. Publish updates to the same private organization plugin after rebuilding with the same origin and plugin ID. Community/public publishing is out of scope.

Designers can save and use the private organization plugin in Figma desktop and browser Figma without entering infrastructure details. See Figma's [desktop import guide](https://help.figma.com/hc/en-us/articles/360042786733-Create-a-plugin-for-development) and [private-organization guide](https://help.figma.com/hc/en-us/articles/4404228629655-Create-private-plugins-for-an-organization). Any allowed-domain change requires security review and a matching server rollout.

## Server, secret, TLS, and proxy policy

Create persistent data outside the repository. It holds SQLite databases, selection resources, uploaded projects, and artifacts; do not use a shared writeable drive.

```powershell
New-Item -ItemType Directory -Force 'C:\ProgramData\FigmaToFGUI' | Out-Null
[byte[]]$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[System.IO.File]::WriteAllText('C:\ProgramData\FigmaToFGUI\gateway-secret.txt', [Convert]::ToBase64String($bytes))
```

Restrict both secret files and the data directory to the service account and administrators using the organization ACL baseline. The files must be different. Never put either secret in CLI arguments, logs, Git, browser or plugin storage, proxy configuration, a support ticket, or this acceptance record. Keep them during restart/rollback: replacing the plugin access token requires rebuilding and republishing the plugin with that exact replacement value; replacing the gateway secret requires the proxy and service to be changed together.

Build the web console, then bind the service to loopback behind an internal TLS proxy:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m figma_to_fgui.cli serve `
  --production `
  --data-dir 'C:\ProgramData\FigmaToFGUI\data' `
  --public-origin 'https://fgui.internal.example' `
  --plugin-access-token-file 'C:\ProgramData\FigmaToFGUI\plugin-access-token.txt' `
  --gateway-secret-file 'C:\ProgramData\FigmaToFGUI\gateway-secret.txt' `
  --web-dist apps/web-console/dist `
  --plugin-manifest apps/figma-plugin/dist/manifest.json `
  --trusted-proxy '127.0.0.1' `
  --host '127.0.0.1' --port 8765
```

Production rejects missing builds/manifests, non-HTTPS/multiple/wildcard origins, either short/same secret, and a manifest whose sole allowed domain differs from `--public-origin`; fixtures are disabled. CORS accepts credentials only from that exact origin. Every `/v1/*` request other than a no-state CORS `OPTIONS` preflight is rejected with generic 401 before endpoint handling unless the proxy injects the exact gateway secret. `/health` and static/plugin UI do not use this header.

Terminate TLS for one internal DNS name and proxy only to `127.0.0.1:8765`. Preserve `Host` and set `X-Forwarded-For`/`X-Forwarded-Proto` only at that proxy. Set a 500 MB request limit (largest compressed project ZIP), 120-second upstream read/send limits, and normal connection/request-header limits. The app also limits each selection resource to 25 MiB and a session to 200 MiB; do not raise proxy limits to bypass application rejection.

Forwarded headers are untrusted by default. Add `--trusted-proxy` only when the immediate proxy has one stable, explicit IP; this enables proxy-validated client-IP attribution for pairing rate limits. Never use `*`, a user header, a CIDR/range, or a public load-balancer address. If that cannot be guaranteed, omit the option and use direct-peer limiting.

### Nginx/IIS reverse-proxy control plane

Use the approved Nginx or IIS configuration to terminate TLS and enforce the corporate network allow-list, mTLS, or equivalent upstream identity policy **before** forwarding any `/v1/*` request. At that boundary, remove every client-supplied `X-Figma-Gateway-Token` header, read the gateway secret from the ACL-protected deployment secret, and inject exactly one replacement header upstream. Do not configure this header in browser JavaScript, Figma plugin code, an application config file, or a copied command line. The loopback ASGI listener is not an alternate API entrypoint: direct `/v1/*` calls without the injected header return generic 401. Let ordinary CORS `OPTIONS` preflight pass without an injected header; it has no endpoint side effect, while the browser’s later API request must traverse the protected proxy and receive injection.

## Backup, recovery, and rollback

Back up the entire data directory as one consistent unit while stopped or with an application-consistent snapshot. Store the secret in the disaster-recovery secret store, not ordinary backups. Test a restore with the unchanged secret in an isolated internal environment. Do not manually delete live SQLite rows, selection directories, or artifacts. Incomplete uploads expire during authenticated selection traffic; completed selections and job artifacts persist, so set a retention policy and purge only through approved maintenance after backup.

For server rollback: stop service, snapshot current data, deploy the previously verified application plus matching Web/Plugin build, retain the current secret, and restart. Do not cross an unreviewed schema change. If secret or origin changed, republish the matching private plugin build and re-pair devices.

Agent application keeps original affected files at `<project>\.figma-to-fgui\backups\<job-id>\`. To roll back locally, stop the Agent, restore affected files from that backup, then manually reopen/reload FairyGUI. `local_project_changed` means the Agent made no write or new backup: upload the current ZIP and create a new review.

## Legacy Windows Agent notes (not part of the plugin create/update flow)

On the owner’s Windows machine, source-install the project and run:

```powershell
cd C:\src\figma-to-fgui
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent register agent-1 'Design PC' --api-url 'https://fgui.internal.example'
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent bind <project-id> 'C:\FGUI\MyProject'
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent poll --once
```

The config is `%LOCALAPPDATA%\FigmaToFGUI\agent.json`, and only explicitly bound folders can change. The Agent’s HTTPS API traffic must use the same protected proxy; it never receives or stores the gateway token. Use `agent run --interval 5` only when continuous polling is intended. Ambiguous project matching is terminal `selection_required`; bind the intended folder and create a new approved job. There is no one-time folder picker, Windows service installer, or automatic FairyGUI refresh.

For the current create/update plugin release, designers do not use this legacy path. They start the private organization plugin in Figma, work from the current selection, and either create a project from an approved template or update an existing FairyGUI ZIP. The plugin returns the checked package for download without opening a Web Console, displaying or requesting a pairing code, asking for a server address, or involving a Windows local agent. Support records may include timestamp, origin, build commit, plugin ID, job ID, and safe UI code—never a deployment access token, credential, Authorization header, raw selection, project file, or secret.
