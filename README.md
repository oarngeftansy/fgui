# Figma to FGUI Conversion Core

This package converts offline Figma JSON fixtures into a validated FGUI staging tree. It never writes to the source project.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli convert tests/fixtures/figma/simple-frame.json tests/fixtures/fgui Sample .staging changeset.json
```

Exit code `0` means the changeset is applicable. Exit code `2` means at least one `ERROR` diagnostic blocked application.

The command writes only to `.staging` and `changeset.json`; `tests/fixtures/fgui` remains read-only.

## Local Server and Windows Agent

This repository also contains a local, fixture-backed vertical slice for testing the approval and safe-apply workflow. It is intentionally unauthenticated and must listen on `127.0.0.1` only.

### Install

```powershell
git clone https://github.com/oarngeftansy/fgui.git
cd fgui
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[dev,server]"
$env:PYTHONPATH = "src"
```

### Start the server

```powershell
.\.venv\Scripts\python.exe -m figma_to_fgui.cli serve
```

The API health check is `http://127.0.0.1:8765/health`; interactive API documentation is available at `http://127.0.0.1:8765/docs`.

### Register the Agent and bind a project

Open a second PowerShell window in the repository:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent register agent-1 "My Windows PC"
.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent bind project-1 "C:\FGUI\MyProject"
```

The binding is stored under `%LOCALAPPDATA%\FigmaToFGUI\agent.json`. Only directories explicitly bound there can be modified by the Agent.

### Create, approve, and apply a fixture job

```powershell
$job = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/v1/jobs -ContentType application/json -Body '{"version":1,"fixture_name":"simple-frame.json","project_id":"project-1","package_name":"Sample"}'
$job | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/v1/jobs/$($job.job_id)/preview" | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/v1/jobs/$($job.job_id)/approve" | ConvertTo-Json -Depth 10

.\.venv\Scripts\python.exe -m figma_to_fgui.cli agent poll --once
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/v1/jobs/$($job.job_id)" | ConvertTo-Json -Depth 10
```

Successful writes leave backups under `<project>\.figma-to-fgui\backups\<job-id>\`. A stale source hash, invalid XML, unsafe path, or interrupted write produces a failed result instead of overwriting unrecognized local changes. After a successful apply, reload the project in FairyGUI manually.

This local slice uses bundled Figma fixtures, SQLite, and local artifact files. Live Figma access, login, the Web Console, the Figma plugin, the .NET tray Agent, installer, and automatic FairyGUI refresh are later phases.
