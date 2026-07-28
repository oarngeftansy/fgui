# Figma to FairyGUI Local Console

This Windows-local pilot lets a designer upload a FairyGUI project ZIP, review one complete update in a browser, and send an approved update to a separately bound local project. The local Agent is the only process that can write a project folder.

The current source is a bundled Figma fixture (`simple-frame.json`), not a live Figma connection. Live Figma selection, sign-in, and automatic FairyGUI refresh are outside this pilot.

## Prerequisites

- Windows 10 or later with PowerShell
- Python 3.11+
- Node.js 20+ and pnpm 9+
- A project ZIP and a separate local FairyGUI working copy for the Agent

## Install reproducibly

```powershell
git clone https://github.com/oarngeftansy/fgui.git
cd fgui
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,server]"
pnpm --dir apps/web-console install --frozen-lockfile
$env:PYTHONPATH = "src"
```

Build the browser console whenever its source changes:

```powershell
pnpm --dir apps/web-console build
```

## Start one local server URL

Run this from the repository root after the build completes:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli serve --web-dist apps/web-console/dist
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The browser console and JSON service use this one URL. The server refuses to start with `--web-dist` when the build directory or its `index.html` is missing; run the build command above first. Built `/assets/*` files are immutable cached assets, while browser routes such as `/jobs/...` return the console shell. `/v1/*` and `/health` stay JSON endpoints.

Keep the default `127.0.0.1` host. This pilot is intentionally local-only and unauthenticated: do not expose it on a LAN, public IP, reverse proxy, or shared drive.

## Designer workflow

1. Open the local URL in a desktop browser.
2. Drag a FairyGUI project ZIP into the upload area. Unsafe, malformed, or oversized archives are rejected without creating a usable project.
3. Check the detected package and resource summary, choose the package, then select **查看本次更新**.
4. In the review workspace, inspect the change list and visual/component summary. **查看高级详情** is only for a support investigation; normal review does not require technical file details.
5. Select **确认更新到本地工程**, then confirm the complete update. The console reports that it is waiting for the local Agent; it does not write a project by itself.

Phone-sized views are deliberately view-only. Use a desktop browser to approve or defer an update.

## Register, bind, and poll the Windows Agent

Do this in a second PowerShell window on the computer that owns the local FairyGUI working copy:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent register agent-1 "Design PC"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent bind <project-id> "C:\FGUI\MyProject"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent poll --once
```

`<project-id>` is supplied during the team’s initial binding; keep it in the local setup record rather than asking a designer to copy technical identifiers from the review screen. The Agent configuration is stored at `%LOCALAPPDATA%\FigmaToFGUI\agent.json` and only explicitly bound folders can be changed.

Use `agent poll --once` for a manual delivery check, or keep the Agent running while testing:

```powershell
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent run --interval 5
```

An exact local project match is selected automatically. If the Agent cannot safely identify one matching bound folder, it returns `selection_required`; bind the intended folder once and retry rather than pointing it at an arbitrary directory.

## Safety, recovery, and local changes

Before a write, the Agent verifies that every affected local file still matches the uploaded version. If someone has edited a relevant file, it returns `local_project_changed` and makes no write or new backup. Upload the latest ZIP and review again.

For a successful update, the original affected files are copied to:

```text
<local project>\.figma-to-fgui\backups\<job-id>\
```

To recover, stop the Agent, copy the affected files from that backup directory over the local project, then reopen or reload the project in FairyGUI. If an interrupted write cannot roll back automatically, keep that backup directory and restore from it before making another approval.

## Verification for contributors

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python -m pytest -v
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src
$env:CI='true'
pnpm --dir apps/web-console test -- --run
Push-Location apps/web-console; .\node_modules\.bin\tsc.cmd --noEmit; Pop-Location
pnpm --dir apps/web-console build
Push-Location apps/web-console; .\node_modules\.bin\playwright.cmd test; Pop-Location
.\.venv\Scripts\python -m figma_to_fgui.cli --help
git diff --check
```

For browser-test setup only, install Chromium once:

```powershell
Push-Location apps/web-console; .\node_modules\.bin\playwright.cmd install chromium; Pop-Location
```

This downloads a test browser; it is not a runtime dependency of the local server or Agent.
