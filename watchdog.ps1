# watchdog.ps1 - Maintien en vie intelligent (Zéro Down + Capot Fermé Ethernet + Publication URL 4G/5G)
$ErrorActionPreference = "SilentlyContinue"
$BaseDir = $PSScriptRoot

$dirs = @(
    "$BaseDir\logs",
    "$BaseDir\Medias\Animes",
    "$BaseDir\Medias\Films",
    "$BaseDir\Medias\Series",
    "$BaseDir\Medias\Musique",
    "$BaseDir\Medias\Musique\Albums",
    "$BaseDir\Medias\Musique\Singles"
)
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Write-WatchdogLog($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "$BaseDir\logs\watchdog.log" -Value "[$ts] $msg" -Encoding UTF8
}

$netstatOut = netstat -ano | Select-String "LISTENING" | Out-String
function Test-PortListening([int]$Port) {
    return ($netstatOut -match "[:\.]$Port\s+")
}

function Start-DetachedProcess([string]$CommandLine, [string]$WorkingDir = $BaseDir) {
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly
    $startup.ShowWindow = [uint16]0
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $CommandLine
        CurrentDirectory = $WorkingDir
        ProcessStartupInformation = $startup
    } | Out-Null
}

# 0. SSHD Service Check (Ports 22 & 8022)
$sshd = Get-Service -Name "sshd" -ErrorAction SilentlyContinue
if ($sshd -and $sshd.Status -ne "Running") {
    Start-Service -Name "sshd" -ErrorAction SilentlyContinue
    Write-WatchdogLog "Service sshd relancé."
}

# Resolve binaries
$pyExe = "C:\Users\ilian\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $pyExe)) {
    $pyExe = Get-ChildItem -Path "C:\Users\*\AppData\Local\Programs\Python\Python*", "C:\Users\*\AppData\Local\Python\pythoncore*", "C:\Python*", "C:\Program Files\Python*" -Filter "python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if (-not $pyExe) { $pyExe = "python" }
}

$jfExe = "C:\Program Files\Jellyfin\Server\jellyfin.exe"
if (-not (Test-Path $jfExe)) {
    $jfExe = Get-ChildItem -Path "$BaseDir\jellyfin", "C:\Program Files\Jellyfin" -Filter "jellyfin.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
}

$cfExe = if (Test-Path "$BaseDir\bin\cloudflared.exe") { "$BaseDir\bin\cloudflared.exe" } else { "cloudflared.exe" }

# 1. FileBrowser (Port 8080)
if (-not (Test-PortListening 8080)) {
    Stop-Process -Name "filebrowser" -Force -ErrorAction SilentlyContinue
    Start-DetachedProcess "`"$BaseDir\bin\filebrowser.exe`" -d `"$BaseDir\filebrowser.db`" -r `"$BaseDir\Medias`" --address 0.0.0.0 --port 8080" "$BaseDir"
    Write-WatchdogLog "FileBrowser (8080) relancé."
}

# 2. Navidrome (Port 4533)
if (-not (Test-PortListening 4533)) {
    Stop-Process -Name "navidrome" -Force -ErrorAction SilentlyContinue
    Start-DetachedProcess "`"$BaseDir\navidrome\navidrome.exe`" -c `"$BaseDir\navidrome\navidrome.toml`"" "$BaseDir\navidrome"
    Write-WatchdogLog "Navidrome (4533) relancé."
}

# 3. Jellyfin (Port 8096)
if (-not (Test-PortListening 8096)) {
    Stop-Process -Name "jellyfin" -Force -ErrorAction SilentlyContinue
    if ($jfExe) {
        $jfDir = Split-Path -Parent $jfExe
        Start-DetachedProcess "`"$jfExe`" --datadir `"$BaseDir\jellyfin_data`" --cachedir `"$BaseDir\jellyfin_cache`"" $jfDir
        Write-WatchdogLog "Jellyfin (8096) relancé."
    }
}

# 4. AdGuard Home (Port 8053 / 3000)
if (-not (Test-PortListening 8053) -and -not (Test-PortListening 3000)) {
    Stop-Process -Name "AdGuardHome" -Force -ErrorAction SilentlyContinue
    if (Test-Path "$BaseDir\adguard\AdGuardHome\AdGuardHome.exe") {
        Start-DetachedProcess "`"$BaseDir\adguard\AdGuardHome\AdGuardHome.exe`" -w `"$BaseDir\adguard\AdGuardHome`"" "$BaseDir\adguard\AdGuardHome"
        Write-WatchdogLog "AdGuardHome (8053) relancé."
    }
}

# 5. Hub Python (Port 5000)
if (-not (Test-PortListening 5000)) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*hub.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-DetachedProcess "`"$pyExe`" `"$BaseDir\hub.py`"" "$BaseDir"
    Write-WatchdogLog "Portail Hub Python (5000) relancé."
}

# 6. Tunnels Cloudflared (5000, 8096, 4533, 8080, 8053) - Ne relance QUE les tunnels manquants
if (Get-Command $cfExe -ErrorAction SilentlyContinue) {
    $cfProcs = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue)
    $tunnels = @(
        @{ Port = 5000; Log = "$BaseDir\logs\cf_hub.log" },
        @{ Port = 8096; Log = "$BaseDir\logs\cf_jf.log" },
        @{ Port = 4533; Log = "$BaseDir\logs\cf_nd.log" },
        @{ Port = 8080; Log = "$BaseDir\logs\cf_fb.log" },
        @{ Port = 8053; Log = "$BaseDir\logs\cf_ag.log" }
    )

    $startedNewHubTunnel = $false
    foreach ($t in $tunnels) {
        $urlTarget = "http://127.0.0.1:$($t.Port)"
        $running = $cfProcs | Where-Object { $_.CommandLine -like "*$urlTarget*" }
        if (-not $running) {
            Remove-Item $t.Log -Force -ErrorAction SilentlyContinue
            Start-DetachedProcess "`"$cfExe`" tunnel --edge-ip-version 4 --protocol http2 --logfile `"$($t.Log)`" --url $urlTarget" "$BaseDir"
            Write-WatchdogLog "Tunnel Cloudflared ($urlTarget) relancé."
            if ($t.Port -eq 5000) { $startedNewHubTunnel = $true }
            Start-Sleep -Seconds 1
        }
    }

    if ($startedNewHubTunnel) { Start-Sleep -Seconds 5 }
}

$ntfyTopic = ""
if (Test-Path "$BaseDir\secrets.json") { $ntfyTopic = (Get-Content "$BaseDir\secrets.json" -Raw | ConvertFrom-Json).ntfy_topic }

# 7. Synchronisation du lien fixe 4G/5G (canal ntfy défini dans secrets.json)
if (Test-Path "$BaseDir\logs\cf_hub.log") {
    $m = Select-String -Path "$BaseDir\logs\cf_hub.log" -Pattern "https://[a-zA-Z0-9-]+\.trycloudflare\.com" -AllMatches
    if ($m -and $m.Matches.Count -gt 0) {
        $currentHubUrl = $m.Matches[-1].Value
        $lastPubFile = "$BaseDir\logs\last_published_url.txt"
        $lastUrl = if (Test-Path $lastPubFile) { (Get-Content $lastPubFile -Raw).Trim() } else { "" }
        if ($currentHubUrl -and $currentHubUrl -ne $lastUrl) {
            Set-Content -Path $lastPubFile -Value $currentHubUrl -Encoding UTF8
            try {
                Invoke-RestMethod -Uri "https://ntfy.sh/$ntfyTopic" -Method Post -Body $currentHubUrl -Headers @{
                    Title = "Portail 4G/5G Serveur Ilian"
                    Click = $currentHubUrl
                    Tags = "computer,link"
                } -TimeoutSec 6 | Out-Null
            } catch {}
        }
    }
}
