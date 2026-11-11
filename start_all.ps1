# start_all.ps1 - Démarrage / Redémarrage des services SANS couper les tunnels 4G/5G (URL fixe conservée)
param([switch]$ResetTunnels = $false)
$ErrorActionPreference = "SilentlyContinue"
$BaseDir = $PSScriptRoot

if ($ResetTunnels) {
    Stop-Process -Name "filebrowser", "navidrome", "jellyfin", "cloudflared", "AdGuardHome" -Force -ErrorAction SilentlyContinue
    Remove-Item "$BaseDir\logs\cf_*.log" -Force -ErrorAction SilentlyContinue
} else {
    # On ne coupe PAS cloudflared pour que l'URL 4G/5G reste strictement identique !
    Stop-Process -Name "filebrowser", "navidrome", "jellyfin", "AdGuardHome" -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*hub.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Seconds 2

# Lance tous les services manquants de manière détachée via le Watchdog
& "$BaseDir\watchdog.ps1"

Start-Sleep -Seconds 6

# Auto-validation de l'assistant Jellyfin (mot de passe lu dans secrets.json)
$jfPw = ""
if (Test-Path "$BaseDir\secrets.json") { $jfPw = (Get-Content "$BaseDir\secrets.json" -Raw | ConvertFrom-Json).jellyfin_password }
try {
    $pub = Invoke-RestMethod -Uri "http://127.0.0.1:8096/System/Info/Public" -Method Get -TimeoutSec 5
    if (-not $pub.StartupWizardCompleted) {
        Invoke-RestMethod -Uri "http://127.0.0.1:8096/Startup/Configuration" -Method Post -ContentType "application/json" -Body '{"UICulture":"fr","MetadataCountryCode":"FR","PreferredMetadataLanguage":"fr"}' -TimeoutSec 5 | Out-Null
        Invoke-RestMethod -Uri "http://127.0.0.1:8096/Startup/User" -Method Get -TimeoutSec 5 | Out-Null
        Invoke-RestMethod -Uri "http://127.0.0.1:8096/Startup/User" -Method Post -ContentType "application/json" -Body ('{"Name":"hugo","Password":"' + $jfPw + '"}') -TimeoutSec 5 | Out-Null
        Invoke-RestMethod -Uri "http://127.0.0.1:8096/Startup/Complete" -Method Post -TimeoutSec 5 | Out-Null
    }
} catch {}
