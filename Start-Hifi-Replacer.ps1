[CmdletBinding()]
param(
  [switch]$SkipInstall,
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$localRoot = Join-Path $repo '.local-hifi-run'
$venv = Join-Path $localRoot 'venv'
$data = Join-Path $localRoot 'data'
$tokenFile = Join-Path $localRoot 'access-token.txt'
$python = Join-Path $venv 'Scripts\python.exe'
$appUrl = 'http://localhost:8765'

function Refresh-ProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = "$machinePath;$userPath"
}

function Resolve-PythonLauncher {
  $py = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($py) { return @($py.Source, '-3.11') }
  $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($candidate -and $candidate.Source -notlike '*\WindowsApps\python.exe') {
    return @($candidate.Source)
  }
  return @()
}

function Install-Prerequisite([string]$Id, [string]$Label) {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "缺少 $Label，且系统没有 winget。请先安装 $Label 后重新运行。"
  }
  Write-Host "正在安装 $Label..." -ForegroundColor Cyan
  & $winget.Source install --id $Id --exact --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) { throw "$Label 安装失败（退出码 $LASTEXITCODE）" }
  Refresh-ProcessPath
}

function Invoke-Pnpm([string[]]$Arguments) {
  $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
  if ($pnpm) {
    & $pnpm.Source @Arguments
  } else {
    $corepack = Get-Command corepack.cmd -ErrorAction SilentlyContinue
    if ($corepack) {
      & $corepack.Source pnpm @Arguments
    } else {
      $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
      if (-not $npx) { throw 'Node.js 已安装，但未找到 pnpm、corepack 或 npx' }
      & $npx.Source --yes pnpm@10 @Arguments
    }
  }
  if ($LASTEXITCODE -ne 0) { throw "pnpm 执行失败（退出码 $LASTEXITCODE）" }
}

[IO.Directory]::CreateDirectory($localRoot) | Out-Null
[IO.Directory]::CreateDirectory($data) | Out-Null

$launcher = @(Resolve-PythonLauncher)
if ($launcher.Count -eq 0) {
  Install-Prerequisite 'Python.Python.3.11' 'Python 3.11'
  $launcher = @(Resolve-PythonLauncher)
}
if ($launcher.Count -eq 0) { throw 'Python 已安装，但当前终端仍无法找到它。请关闭窗口后重新双击启动脚本。' }

if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
  Install-Prerequisite 'OpenJS.NodeJS.LTS' 'Node.js LTS'
}
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
  throw 'Node.js 已安装，但当前终端仍无法找到它。请关闭窗口后重新双击启动脚本。'
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  Write-Host '正在创建本地应用环境...' -ForegroundColor Cyan
  $launcherExe = $launcher[0]
  $launcherArgs = @($launcher | Select-Object -Skip 1) + @('-m', 'venv', $venv)
  & $launcherExe @launcherArgs
  if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败' }
}

if (-not $SkipInstall) {
  Write-Host '正在安装/更新本地处理服务...' -ForegroundColor Cyan
  & $python -m pip install --disable-pip-version-check -e "$repo[server]"
  if ($LASTEXITCODE -ne 0) { throw '本地处理服务安装失败' }

  Write-Host '正在安装本地界面依赖...' -ForegroundColor Cyan
  Invoke-Pnpm @('--dir', (Join-Path $repo 'apps\web-console'), 'install', '--frozen-lockfile')
}

if (-not (Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
  [byte[]]$bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  [IO.File]::WriteAllText($tokenFile, [Convert]::ToBase64String($bytes), [Text.UTF8Encoding]::new($false))
}

Write-Host '正在构建 PSD 替换工具界面...' -ForegroundColor Cyan
Invoke-Pnpm @('--dir', (Join-Path $repo 'apps\web-console'), 'build')

Write-Host ''
Write-Host "PSD 替换工具正在 $appUrl 启动；关闭此窗口即可停止。" -ForegroundColor Green
if (-not $NoBrowser) {
  $openApp = "Start-Sleep -Seconds 2; Start-Process '$appUrl'"
  Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-Command', $openApp)
}

$env:PYTHONPATH = Join-Path $repo 'src'
& $python -m figma_to_fgui.cli serve `
  --local-app `
  --data-dir $data `
  --rules (Join-Path $repo 'rules\default\classification.yaml') `
  --fixtures-root (Join-Path $repo 'tests\fixtures') `
  --web-dist (Join-Path $repo 'apps\web-console\dist') `
  --plugin-access-token-file $tokenFile `
  --host 127.0.0.1 `
  --port 8765
