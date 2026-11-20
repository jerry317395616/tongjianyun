#Requires -RunAsAdministrator
param([Parameter(Mandatory=$true)][string]$ConfigPath, [Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$targetDir = 'C:\ProgramData\TongjianyunVideo'
$sourceConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$pythonExe = (Resolve-Path -LiteralPath $PythonPath).Path
$config = Get-Content -LiteralPath $sourceConfig -Raw | ConvertFrom-Json
if ($config.spool -ne 'C:\ProgramData\TongjianyunVideo\spool') { throw 'Use the dedicated ProgramData spool directory.' }
if (!(Test-Path -LiteralPath $config.ffmpeg -PathType Leaf)) { throw 'Install FFmpeg and set its absolute path first.' }
& $pythonExe -c 'import sys; assert sys.version_info >= (3, 11)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
& icacls.exe $targetDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not secure private configuration directory.' }
if ($sourceConfig -ne "$targetDir\config.json") { Copy-Item -LiteralPath $sourceConfig -Destination "$targetDir\config.json" }
Copy-Item -LiteralPath "$PSScriptRoot\collector.py" -Destination "$targetDir\collector.py" -Force
& $pythonExe "$targetDir\collector.py" --config "$targetDir\config.json" --check
if ($LASTEXITCODE -ne 0) { throw 'Collector configuration validation failed.' }
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument '"C:\ProgramData\TongjianyunVideo\collector.py" --config "C:\ProgramData\TongjianyunVideo\config.json"' -WorkingDirectory $targetDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'TongjianyunVideoCollector' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host 'Installed (not started). Verify teacher consent, camera point, recording hours and computer time zone before starting.'
Write-Host 'Start-ScheduledTask -TaskName TongjianyunVideoCollector'
