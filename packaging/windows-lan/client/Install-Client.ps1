[CmdletBinding()]
param([string]$ServerOrigin = 'http://192.168.50.210:8780')
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'FigmaToFGUI'
[IO.Directory]::CreateDirectory($root) | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Sync-Plugin.ps1') -Destination (Join-Path $root 'Sync-Plugin.ps1') -Force
[IO.File]::WriteAllText((Join-Path $root 'server-origin.txt'), $ServerOrigin, [Text.UTF8Encoding]::new($false))
& (Join-Path $root 'Sync-Plugin.ps1') -ServerOrigin $ServerOrigin

$escapedRoot = $root.Replace('''', '''''')
$escapedOrigin = $ServerOrigin.Replace('''', '''''')
$command = "& '$escapedRoot\Sync-Plugin.ps1' -ServerOrigin '$escapedOrigin'"
try {
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$command`""
  $triggerLogon = New-ScheduledTaskTrigger -AtLogOn
  $triggerTimer = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
  Register-ScheduledTask -TaskName 'FigmaToFGUI-ClientSync' -Action $action -Trigger @($triggerLogon, $triggerTimer) -Settings $settings -Force | Out-Null
} catch {
  $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
  $runValue = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$command`""
  Set-ItemProperty -Path $runKey -Name 'FigmaToFGUIClientSync' -Value $runValue
  Write-Warning 'Scheduled sync was unavailable. Update sync will run at Windows sign-in.'
}

$manifest = Join-Path $root 'plugin\manifest.json'
Write-Host "Installed. Import this manifest once in Figma development plugins: $manifest"
Start-Process explorer.exe -ArgumentList "/select,`"$manifest`""
