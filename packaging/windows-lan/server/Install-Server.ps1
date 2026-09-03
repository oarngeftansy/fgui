[CmdletBinding()]
param(
  [string]$ServerAddress = '192.168.50.210',
  [int]$Port = 8780,
  [string]$PluginId = '123456789'
)
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Install-Server.ps1 from an administrator PowerShell' }
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($ServerAddress, [ref]$parsedAddress) -or $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'ServerAddress must be an IPv4 address' }
$bytes = $parsedAddress.GetAddressBytes()
$private = $bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
if (-not $private) { throw 'ServerAddress must be an RFC1918 private address' }
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port' }
if ($PluginId -notmatch '^\d+$') { throw 'PluginId must be numeric' }
$origin = "http://${ServerAddress}:$Port"
$bundle = $PSScriptRoot
$root = 'C:\ProgramData\FigmaToFGUI'
foreach ($directory in @($root, "$root\bin", "$root\data", "$root\logs", "$root\plugin", "$root\release", "$root\web-dist", "$root\rules")) { [IO.Directory]::CreateDirectory($directory) | Out-Null }

$pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { & $pythonCommand.Source -3 -m venv "$root\venv" } else {
  $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
  if (-not $pythonCommand) { throw 'Python 3.11+ is required on the server' }
  & $pythonCommand.Source -m venv "$root\venv"
}
$python = "$root\venv\Scripts\python.exe"
if ([Version](& $python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') -lt [Version]'3.11') { throw 'Python 3.11+ is required on the server' }
& $python -m pip install --upgrade pip
$wheel = @(Get-ChildItem -LiteralPath "$bundle\runtime" -Filter 'figma_to_fgui_core-*.whl' -File)
if ($wheel.Count -ne 1) { throw 'The package must contain exactly one application wheel' }
& $python -m pip install "$($wheel[0].FullName)[server]"

function New-RandomSecret([string]$Path) {
  if (Test-Path $Path) { return }
  [byte[]]$bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  [IO.File]::WriteAllText($Path, [Convert]::ToBase64String($bytes), [Text.UTF8Encoding]::new($false))
}
function Get-Sha256Hex([string]$Path) {
  $stream = [IO.File]::OpenRead($Path)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
  finally { $algorithm.Dispose(); $stream.Dispose() }
}
New-RandomSecret "$root\plugin-access-token.txt"
New-RandomSecret "$root\gateway-secret.txt"
[IO.File]::WriteAllText("$root\public-origin.txt", $origin, [Text.UTF8Encoding]::new($false))
Copy-Item -Path "$bundle\web-dist\*" -Destination "$root\web-dist" -Recurse -Force
Copy-Item -Path "$bundle\runtime\rules\*" -Destination "$root\rules" -Recurse -Force
Copy-Item -LiteralPath "$bundle\Start-Writer.ps1", "$bundle\Start-Gateway.ps1" -Destination $root -Force
$caddyConfig = (Get-Content -Raw "$bundle\Caddyfile").Replace(':8780 {', ":$Port {")
[IO.File]::WriteAllText("$root\Caddyfile", $caddyConfig, [Text.UTF8Encoding]::new($false))

$token = (Get-Content -Raw "$root\plugin-access-token.txt").Trim()
$ui = (Get-Content -Raw "$bundle\plugin-template\ui.html").Replace('https://fgui.corp.example', $origin).Replace('not-a-secret-public-test-placeholder-000000', $token)
[IO.File]::WriteAllText("$root\plugin\ui.html", $ui, [Text.UTF8Encoding]::new($false))
Copy-Item "$bundle\plugin-template\code.js" "$root\plugin\code.js" -Force
$manifest = Get-Content -Raw "$bundle\plugin-template\manifest.json" | ConvertFrom-Json
$manifest.id = $PluginId
$manifest.networkAccess = [ordered]@{ allowedDomains = @($origin); reasoning = "Connects to the organization's private LAN Figma-to-FairyGUI service." }
[IO.File]::WriteAllText("$root\plugin\manifest.json", ($manifest | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))

$releaseId = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$versionRoot = "$root\release\$releaseId"
[IO.Directory]::CreateDirectory($versionRoot) | Out-Null
$fileMap = [ordered]@{}
foreach ($name in @('manifest.json', 'code.js', 'ui.html')) {
  Copy-Item "$root\plugin\$name" "$versionRoot\$name" -Force
  $item = Get-Item "$versionRoot\$name"
  $fileMap[$name] = [ordered]@{ bytes = $item.Length; sha256 = Get-Sha256Hex $item.FullName }
}
$release = [ordered]@{ schemaVersion = 1; releaseId = $releaseId; serverOrigin = $origin; files = $fileMap }
[IO.File]::WriteAllText("$root\release\current.json.tmp", ($release | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
Move-Item "$root\release\current.json.tmp" "$root\release\current.json" -Force
$clientStage = "$root\release\client-$releaseId"
[IO.Directory]::CreateDirectory($clientStage) | Out-Null
Copy-Item -Path "$bundle\client\*" -Destination $clientStage -Recurse -Force
foreach ($clientScript in Get-ChildItem $clientStage -Filter '*.ps1' -File) {
  $clientText = (Get-Content -Raw $clientScript.FullName).Replace('http://192.168.50.210:8780', $origin)
  [IO.File]::WriteAllText($clientScript.FullName, $clientText, [Text.UTF8Encoding]::new($false))
}
Compress-Archive -Path "$clientStage\*" -DestinationPath "$root\release\FigmaToFGUI-Client.zip" -Force

$caddy = "$root\bin\caddy.exe"
if (-not (Test-Path $caddy)) {
  Invoke-WebRequest -UseBasicParsing 'https://caddyserver.com/api/download?os=windows&arch=amd64' -OutFile "$root\bin\caddy.zip"
  Expand-Archive "$root\bin\caddy.zip" "$root\bin\caddy-download" -Force
  Copy-Item "$root\bin\caddy-download\caddy.exe" $caddy -Force
}
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
foreach ($service in @('Writer', 'Gateway')) {
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\Start-$service.ps1`"" -WorkingDirectory $root
  Register-ScheduledTask -TaskName "FigmaToFGUI-$service" -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
}
if (-not (Get-NetFirewallRule -DisplayName 'FigmaToFGUI LAN' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'FigmaToFGUI LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Domain,Private | Out-Null
}
Start-ScheduledTask 'FigmaToFGUI-Writer'; Start-Sleep 3
Start-ScheduledTask 'FigmaToFGUI-Gateway'; Start-Sleep 3
if ((Invoke-WebRequest -UseBasicParsing "$origin/health" -TimeoutSec 15).StatusCode -ne 200) { throw 'LAN service health check failed' }
Write-Host "Server installed: $origin"
Write-Host "Client package: $root\release\FigmaToFGUI-Client.zip"
