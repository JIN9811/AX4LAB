param(
    [string]$DataRoot = "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge",
    [string]$PythonLauncher = "py",
    [string]$ControllerAddress = "",
    [switch]$SetupOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ($DataRoot -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
    throw "DataRoot must be an absolute Windows drive or UNC path, not a Linux or drive-relative path."
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
if ($SetupOnly -and $ControllerAddress) {
    throw "SetupOnly does not change firewall rules. Use the explicit bridge deployment installer separately."
}
Write-Host "Bridge package: $sourceRoot"
Write-Host "Data root: $DataRoot"
Write-Host "Network: Python bridge dependencies from PyPI (not a frozen portable wheelhouse). No server startup."
if ($DryRun) {
    Write-Host "Would create package-local .venv and install requirements-windows.txt."
    if (-not $SetupOnly) { Write-Host "Would also register a logon task, shortcuts, and user data-root setting." }
    return
}

$venvPython = Join-Path $sourceRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonLauncher -eq "py") { & py -3.11 -m venv (Join-Path $sourceRoot ".venv") }
    else { & $PythonLauncher -m venv (Join-Path $sourceRoot ".venv") }
    if ($LASTEXITCODE -ne 0) { throw "Dedicated bridge virtual environment creation failed." }
}
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Windows bridge pip upgrade failed." }
& $venvPython -m pip install -r (Join-Path $sourceRoot "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "Windows bridge dependency installation failed." }
if ($SetupOnly) {
    Write-Host "Dependencies prepared. No data import, environment setting, task, shortcut, firewall, or server startup."
    return
}

New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
[Environment]::SetEnvironmentVariable("WINDOWS_PYAUTOGUI_DATA_ROOT", $DataRoot, "User")

if ($ControllerAddress) {
    & (Join-Path $sourceRoot "scripts\firewall_allow_private.ps1") -RemoteAddress $ControllerAddress
}

$taskName = "ATR Windows PyAutoGUI Bridge"
$supervisorScript = Join-Path $sourceRoot "scripts\start_supervisor.ps1"
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$supervisorScript`" -DataRoot `"$DataRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null

function New-BridgeShortcut {
    param([string]$ShortcutPath, [string]$LauncherPath, [string]$Description)
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\cmd.exe"
    $shortcut.Arguments = "/c `"$LauncherPath`""
    $shortcut.WorkingDirectory = $sourceRoot
    $shortcut.Description = $Description
    $shortcut.Save()
}

$desktopFolder = [Environment]::GetFolderPath("Desktop")
$startMenuFolder = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\ATR"
New-Item -ItemType Directory -Path $startMenuFolder -Force | Out-Null
$startLauncher = Join-Path $sourceRoot "START_WINDOWS_BRIDGE.cmd"
$uninstallLauncher = Join-Path $sourceRoot "UNINSTALL_WINDOWS_BRIDGE.cmd"
New-BridgeShortcut -ShortcutPath (Join-Path $desktopFolder "ATR Windows Bridge.lnk") -LauncherPath $startLauncher -Description "Start ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $desktopFolder "Uninstall ATR Windows Bridge.lnk") -LauncherPath $uninstallLauncher -Description "Remove ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $startMenuFolder "ATR Windows Bridge.lnk") -LauncherPath $startLauncher -Description "Start ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $startMenuFolder "Uninstall ATR Windows Bridge.lnk") -LauncherPath $uninstallLauncher -Description "Remove ATR Windows PyAutoGUI Bridge"
Write-Host "Desktop and Start Menu shortcuts created."

Write-Host "Prepared Windows PyAutoGUI Bridge in package folder: $sourceRoot"
Write-Host "Data root: $DataRoot"
Write-Host "Start: powershell -ExecutionPolicy Bypass -File `"$sourceRoot\scripts\start_supervisor.ps1`""
