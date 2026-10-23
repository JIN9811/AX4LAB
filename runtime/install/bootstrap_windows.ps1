<# Legacy entry point retained for native Windows UTM bridge setup only.
   The main runtime's supported portable setup is bootstrap_linux.sh.
   No server, desktop automation, scheduled task, or firewall is started/registered.
#>
param(
  [switch]$DryRun,
  [string]$DataRoot = "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge",
  [string]$PythonLauncher = "py"
)
$ErrorActionPreference = "Stop"
$RuntimeRoot = Split-Path -Parent $PSScriptRoot
$Installer = Join-Path $RuntimeRoot "Pyautogui_server_for_window\scripts\install_bridge.ps1"
& $Installer -SetupOnly -DryRun:$DryRun -DataRoot $DataRoot -PythonLauncher $PythonLauncher
if (-not $?) { throw "Windows bridge setup failed." }
