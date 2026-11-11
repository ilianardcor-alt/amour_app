import base64
import codecs
import collections
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from urllib.parse import quote, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, send_from_directory

try:
    import cloudscraper
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
except Exception:
    scraper = requests.Session()

scraper.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
)

try:
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError
    from mutagen.mp3 import MP3
    HAS_MUTAGEN = True
except Exception:
    HAS_MUTAGEN = False

try:
    from ytmusicapi import YTMusic
    YTM = YTMusic()
except Exception:
    YTM = None

BASE_DIR = os.environ.get("SERVEUR_DIR", os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static", template_folder=TEMPLATES_DIR)

BIN_DIR = os.path.join(BASE_DIR, "bin")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MEDIAS_DIR = os.path.join(BASE_DIR, "Medias")
MUSIC_DIR = os.path.join(MEDIAS_DIR, "Musique")
MUSIC_ALBUMS_DIR = os.path.join(MUSIC_DIR, "Albums")
MUSIC_SINGLES_DIR = os.path.join(MUSIC_DIR, "Singles")
OFFLINE_CACHE_DIR = os.path.join(MUSIC_DIR, ".offline_cache")
SINGLES_M3U = os.path.join(MUSIC_DIR, "Singles_En_Vrac.m3u")
SPOTIFY_SYNC_FILE = os.path.join(BASE_DIR, "spotify_sync.json")
ANIME_DIR = os.path.join(MEDIAS_DIR, "Animes")
FILMS_DIR = os.path.join(MEDIAS_DIR, "Films")
SERIES_DIR = os.path.join(MEDIAS_DIR, "Series")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "hub_activity.log")
HTML_FILE = os.path.join(BASE_DIR, "index.html")
ILIANTIFY_HTML_FILE = os.path.join(BASE_DIR, "music_app.html")
FAVORITES_FILE = os.path.join(BASE_DIR, "music_favorites.json")
SOURCES_CONFIG_FILE = os.path.join(BASE_DIR, "sources_config.json")
TAILSCALE_EXE = r"C:\Program Files\Tailscale\tailscale.exe"
def _load_secrets():
    """Charge les secrets locaux (non versionnés) : secrets.json ou variables d'environnement."""
    data = {}
    try:
        with open(os.path.join(BASE_DIR, "secrets.json"), encoding="utf-8-sig") as _f:
            data = json.load(_f)
    except Exception:
        pass
    return data


_SECRETS = _load_secrets()
JF_PASSWORD = os.environ.get("JF_PASSWORD") or _SECRETS.get("jellyfin_password", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or _SECRETS.get("ntfy_topic", "")

for _d in [
    STATIC_DIR,
    BIN_DIR,
    BACKUP_DIR,
    MEDIAS_DIR,
    MUSIC_DIR,
    MUSIC_SINGLES_DIR,
    OFFLINE_CACHE_DIR,
    ANIME_DIR,
    FILMS_DIR,
    SERIES_DIR,
    LOG_DIR,
]:
    os.makedirs(_d, exist_ok=True)

try:
    open(os.path.join(OFFLINE_CACHE_DIR, ".ndignore"), "a", encoding="utf-8").close()
except Exception:
    pass

STATUS = {
    "active": False,
    "title": "Aucun téléchargement actif",
    "step": "Prêt.",
    "percent": 0,
    "speed": "-",
    "error": "",
    "stop": False,
    "queue_count": 0,
}
CURRENT_PROC = None
TERM_CWD = BASE_DIR

# ==============================================================================
# FILE D'ATTENTE MULTI-TÉLÉCHARGEMENTS (ANTI-BUG SI CLICS MULTIPLES)
# ==============================================================================
DOWNLOAD_QUEUE = collections.deque()
QUEUE_LOCK = threading.Lock()
QUEUE_WORKER_RUNNING = False


def write_log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="ignore") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def enqueue_download(label, func, *args, **kwargs):
    """Ajoute un téléchargement dans la file d'attente pour permettre de cliquer sur
    autant de films, épisodes ou musiques qu'on veut en même temps sans aucun bug."""
    global QUEUE_WORKER_RUNNING
    with QUEUE_LOCK:
        STATUS["stop"] = False
        DOWNLOAD_QUEUE.append((label, func, args, kwargs))
        STATUS["queue_count"] = len(DOWNLOAD_QUEUE)
        q_len = len(DOWNLOAD_QUEUE)
        if not STATUS["active"] and q_len == 1:
            STATUS["active"] = True
            STATUS["title"] = label
            STATUS["step"] = "⏳ Démarrage du téléchargement..."
            STATUS["percent"] = 0
            STATUS["speed"] = "-"
            STATUS["error"] = ""
        else:
            write_log(f"➕ Ajouté à la file d'attente ({q_len} en attente) : {label}")

        if not QUEUE_WORKER_RUNNING:
            QUEUE_WORKER_RUNNING = True
            threading.Thread(target=_queue_worker_loop, daemon=True).start()


def _queue_worker_loop():
    global QUEUE_WORKER_RUNNING
    while True:
        with QUEUE_LOCK:
            if not DOWNLOAD_QUEUE:
                QUEUE_WORKER_RUNNING = False
                STATUS["queue_count"] = 0
                break
            label, func, args, kwargs = DOWNLOAD_QUEUE.popleft()
            STATUS["queue_count"] = len(DOWNLOAD_QUEUE)
        try:
            func(*args, **kwargs)
        except Exception as e:
            write_log(f"❌ Erreur tâche ({label}): {e}")


def get_env():
    env = os.environ.copy()
    env["PATH"] = BIN_DIR + ";" + env.get("PATH", "")
    return env


def clean_name(s):
    s = re.sub(r"(Anime\s*·.*|Scans\s*·.*)", "", str(s or ""))
    s = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", s).strip()
    s = re.sub(r"\s+", " ", s).strip(". ")
    return s[:75] or "Media"


def strip_html(text):
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", str(text)).strip()


def folder_size_mb(path):
    total = 0
    if not os.path.exists(path):
        return 0.0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return round(total / 1048576, 1)


def get_tunnel_url(log_name):
    p = os.path.join(LOG_DIR, log_name)
    if os.path.exists(p):
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
            m = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", txt)
            if m:
                return m[-1]
        except Exception:
            pass
    return ""


def get_local_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if (
                ":" not in ip
                and not ip.startswith("127.")
                and not ip.startswith("169.254.")
                and ip not in ips
            ):
                ips.append(ip)
    except Exception:
        pass
    ips.sort(key=lambda x: (0 if x.startswith("192.168.") else (1 if not x.startswith("100.") else 2), x))
    return ", ".join(ips) if ips else "192.168.1.160"


def get_ag_port():
    return (
        8053
        if os.path.exists(os.path.join(BASE_DIR, "adguard", "AdGuardHome", "AdGuardHome.yaml"))
        else 3000
    )


# ==============================================================================
# SYSTÈME DE SAUVEGARDE & RESTAURATION (SNAPSHOTS)
# ==============================================================================
BACKUP_FILES = [
    "hub.py",
    "index.html",
    "music_app.html",
    "sources_config.json",
    "TUTO_VPN_TAILSCALE.md",
    "watchdog.ps1",
    "start_all.ps1",
    "filebrowser.db",
    r"navidrome\navidrome.toml",
]


def create_snapshot(label="auto"):
    safe_lbl = re.sub(r"[^a-zA-Z0-9_-]", "_", str(label or "snapshot"))[:30]
    ts = time.strftime("%Y%m%d_%H%M%S")
    snap_name = f"{ts}_{safe_lbl}"
    snap_dir = os.path.join(BACKUP_DIR, snap_name)
    os.makedirs(snap_dir, exist_ok=True)
    for rel in BACKUP_FILES:
        src = os.path.join(BASE_DIR, rel)
        if os.path.exists(src):
            dst = os.path.join(snap_dir, os.path.basename(rel))
            shutil.copy2(src, dst)
    write_log(f"💾 Sauvegarde créée : {snap_name}")
    return snap_name


# ==============================================================================
# JELLYFIN AUTO-CONFIG & AUTO-REFRESH (PORT 8096)
# ==============================================================================
def get_jellyfin_headers(token=None):
    base_h = (
        'MediaBrowser Client="ServeurHub", Device="PChugo", '
        'DeviceId="pchugo-srv", Version="2.0.0"'
    )
    if token:
        base_h += f', Token="{token}"'
    return {"Authorization": base_h}


def get_jellyfin_token():
    base = "http://127.0.0.1:8096"
    r = requests.post(
        f"{base}/Users/AuthenticateByName",
        json={"Username": "hugo", "Pw": JF_PASSWORD},
        headers=get_jellyfin_headers(),
        timeout=5,
    )
    if r.status_code == 200:
        return r.json().get("AccessToken")
    return None


def ensure_jellyfin_configured():
    base = "http://127.0.0.1:8096"
    try:
        pub = requests.get(f"{base}/System/Info/Public", timeout=4).json()
        if not pub.get("StartupWizardCompleted"):
            requests.post(
                f"{base}/Startup/Configuration",
                json={
                    "UICulture": "fr",
                    "MetadataCountryCode": "FR",
                    "PreferredMetadataLanguage": "fr",
                },
                timeout=5,
            )
            requests.get(f"{base}/Startup/User", timeout=5)
            requests.post(
                f"{base}/Startup/User",
                json={"Name": "hugo", "Password": JF_PASSWORD},
                timeout=5,
            )
            requests.post(f"{base}/Startup/Complete", timeout=5)

        tok = get_jellyfin_token()
        if not tok:
            return
        headers = get_jellyfin_headers(tok)
        vf = requests.get(
            f"{base}/Library/VirtualFolders", headers=headers, timeout=6
        ).json()

        for f in vf:
            if f.get("Name") == "Séries" and ANIME_DIR in f.get("Locations", []):
                requests.delete(
                    f"{base}/Library/VirtualFolders",
                    params={"name": f["Name"], "refreshLibrary": "false"},
                    headers=headers,
                    timeout=6,
                )

        vf = requests.get(
            f"{base}/Library/VirtualFolders", headers=headers, timeout=6
        ).json()
        existing_paths = {
            loc.lower(): f.get("Name")
            for f in vf
            for loc in f.get("Locations", [])
        }

        desired = [
            ("Animes", "tvshows", ANIME_DIR),
            ("Séries (Disney+ / HBO / TV)", "tvshows", SERIES_DIR),
            ("Films", "movies", FILMS_DIR),
        ]
        created_any = False
        for name, ctype, path in desired:
            if path.lower() not in existing_paths:
                requests.post(
                    f"{base}/Library/VirtualFolders",
                    params={
                        "name": name,
                        "collectionType": ctype,
                        "paths": path,
                        "refreshLibrary": "false",
                    },
                    json={
                        "LibraryOptions": {
                            "EnableRealtimeMonitor": True,
                            "PreferredMetadataLanguage": "fr",
                            "MetadataCountryCode": "FR",
                        }
                    },
                    headers=headers,
                    timeout=10,
                )
                created_any = True
        if created_any:
            requests.post(f"{base}/Library/Refresh", headers=headers, timeout=5)
    except Exception:
        pass


def refresh_jellyfin_library():
    try:
        tok = get_jellyfin_token()
        if tok:
            requests.post(
                "http://127.0.0.1:8096/Library/Refresh",
                headers=get_jellyfin_headers(tok),
                timeout=5,
            )
            write_log("🔄 Médiathèque Jellyfin rafraîchie automatiquement.")
    except Exception:
        pass


# ==============================================================================
# ADGUARD HOME : CONTRÔLE, STATS EN DIRECT & AUTO-LOGIN
# ==============================================================================
def get_adguard_session():
    s = requests.Session()
    try:
        s.post(
            f"http://127.0.0.1:{get_ag_port()}/control/login",
            json={"name": "hugo", "password": JF_PASSWORD},
            timeout=3,
        )
    except Exception:
        pass
    return s


@app.route("/api/adguard_status")
def api_adguard_status():
    port = get_ag_port()
    base = f"http://127.0.0.1:{port}"
    try:
        s = get_adguard_session()
        st = s.get(f"{base}/control/status", timeout=3).json()
        stats = s.get(f"{base}/control/stats", timeout=3).json()
        return jsonify(
            {
                "ok": True,
                "running": st.get("running", True),
                "protection_enabled": st.get("protection_enabled", True),
                "dns_port": st.get("dns_port", 53),
                "http_port": port,
                "dns_ip": get_local_ips().split(",")[0].strip(),
                "num_dns_queries": stats.get("num_dns_queries", 0),
                "num_blocked_filtering": stats.get("num_blocked_filtering", 0),
                "avg_processing_time": round(
                    (stats.get("avg_processing_time") or 0) * 1000, 1
                ),
                "ag_url": get_tunnel_url("cf_ag.log"),
            }
        )
    except Exception as e:
        return jsonify(
            {
                "ok": False,
                "running": False,
                "protection_enabled": False,
                "dns_ip": get_local_ips().split(",")[0].strip(),
                "error": str(e),
            }
        )


@app.route("/api/adguard_toggle", methods=["POST"])
def api_adguard_toggle():
    port = get_ag_port()
    enabled = request.form.get("enabled", "true").lower() == "true"
    try:
        s = get_adguard_session()
        s.post(
            f"http://127.0.0.1:{port}/control/dns_config",
            json={"protection_enabled": enabled},
            timeout=4,
        )
        return jsonify({"ok": True, "protection_enabled": enabled})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/go/adguard")
def go_adguard():
    port = get_ag_port()
    ag_tunnel = get_tunnel_url("cf_ag.log")
    host_only = request.host.split(":")[0]
    if "trycloudflare.com" in host_only and ag_tunnel:
        target = ag_tunnel
    else:
        target = f"http://{host_only}:{port}/"

    resp = redirect(target)
    try:
        r = requests.post(
            f"http://127.0.0.1:{port}/control/login",
            json={"name": "hugo", "password": JF_PASSWORD},
            timeout=3,
        )
        agh_cookie = r.cookies.get("agh_session")
        if agh_cookie:
            resp.set_cookie(
                "agh_session",
                agh_cookie,
                max_age=3600 * 24 * 365,
                path="/",
                httponly=True,
                samesite="Lax",
            )
    except Exception:
        pass
    return resp


@app.route("/api/permanent_bookmark")
def api_permanent_bookmark():
    """Génère une page HTML autonome à ajouter en favori / écran d'accueil sur iPhone ou Mac.
    Même si le serveur redémarre et change de tunnel Cloudflare, ce fichier redirige
    automatiquement vers le nouveau tunnel actif !"""
    local_ip = get_local_ips().split(",")[0].strip()
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portail Serveur Hugo (Lien Fixe Permanent)</title>
<style>
body{{background:#090d16;color:#f8fafc;font-family:-apple-system,Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:20px}}
.box{{background:#1e293b;border:1px solid #38bdf8;border-radius:16px;padding:24px;max-width:420px;width:100%}}
a{{display:block;background:#0284c7;color:#fff;padding:12px;border-radius:10px;text-decoration:none;font-weight:700;margin-top:10px}}
</style>
</head>
<body>
<div class="box">
<h2 style="color:#38bdf8;margin-top:0">🚀 Connexion au Serveur de Hugo...</h2>
<p id="st" style="color:#94a3b8;font-size:13px">Recherche automatique du lien 4G/5G ou Wi-Fi actif...</p>
<div id="links"></div>
</div>
<script>
async function connectNow() {{
    // 1. Test rapide si on est à la maison en Wi-Fi
    try {{
        const c = new AbortController();
        setTimeout(() => c.abort(), 1200);
        const rLocal = await fetch("http://{local_ip}:5000/api/status", {{signal: c.signal, mode: "no-cors"}});
        window.location.replace("http://{local_ip}:5000");
        return;
    }} catch(e) {{}}

    // 2. Récupération du dernier tunnel 4G/5G publié par le serveur
    try {{
        const r = await fetch("https://ntfy.sh/{NTFY_TOPIC}/json?poll=1&since=48h");
        const txt = await r.text();
        const lines = txt.trim().split("\\n").filter(Boolean);
        for (let i = lines.length - 1; i >= 0; i--) {{
            const obj = JSON.parse(lines[i]);
            const m = (obj.message || obj.click || "").match(/https:\\/\\/[a-zA-Z0-9-]+\\.trycloudflare\\.com/);
            if (m) {{
                document.getElementById("st").textContent = "Redirection vers " + m[0] + "...";
                window.location.replace(m[0]);
                return;
            }}
        }}
    }} catch(e) {{}}
    document.getElementById("st").textContent = "Choisis le mode d'accès :";
    document.getElementById("links").innerHTML = '<a href="http://{local_ip}:5000">🏠 Ouvrir en Wi-Fi Maison ({local_ip})</a>';
}}
connectNow();
</script>
</body>
</html>"""
    mem = io.BytesIO(html.encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem,
        mimetype="text/html",
        as_attachment=True,
        download_name="Portail_Serveur_4G_Permanent.html",
    )


# ==============================================================================
# AUTO-RÉPARATEUR DES SOURCES DE STREAMING ("STREAM HEALER")
# ==============================================================================
DEFAULT_SOURCES_CONFIG = {
    "last_check": "",
    "last_status": "Opérationnel",
    "sources": {
        "anime_sama": {
            "label": "Anime-Sama (Animés & Scans)",
            "active_domain": "https://anime-sama.to",
            "base_name": "anime-sama",
            "test_path": "/",
            "fallback_extensions": ["to", "fr", "si", "org", "pe", "re", "gg", "lol", "sbs", "hair"],
            "search_query": "anime-sama site officiel catalogue",
            "status": "ok",
            "latency_ms": 0,
        },
        "frembed": {
            "label": "Frembed (Films & Séries VF/VOSTFR)",
            "active_domain": "https://frembed.pro",
            "base_name": "frembed",
            "test_path": "/",
            "fallback_extensions": ["pro", "lol", "sbs", "hair", "to", "cc", "fun", "cfd", "live"],
            "search_query": "frembed officiel streaming api",
            "status": "ok",
            "latency_ms": 0,
        },
        "vidsrc": {
            "label": "VidSrc Multi-Langues (VF/VOSTFR/VO)",
            "active_domain": "https://vidsrc.pm",
            "base_name": "vidsrc",
            "test_path": "/",
            "fallback_extensions": ["pm", "xyz", "me", "net", "to", "in", "vc", "cc"],
            "search_query": "vidsrc embed api",
            "status": "ok",
            "latency_ms": 0,
        },
        "autoembed": {
            "label": "AutoEmbed HD (Films & Séries)",
            "active_domain": "https://autoembed.co",
            "base_name": "autoembed",
            "test_path": "/",
            "fallback_extensions": ["co", "cc", "to", "pro"],
            "search_query": "autoembed movie imdb",
            "status": "ok",
            "latency_ms": 0,
        },
        "multiembed": {
            "label": "MultiEmbed / SuperEmbed",
            "active_domain": "https://multiembed.mov",
            "base_name": "multiembed",
            "test_path": "/",
            "fallback_extensions": ["mov", "cc", "to", "pro"],
            "search_query": "multiembed superembed video_id",
            "status": "ok",
            "latency_ms": 0,
        },
    },
}


def load_sources_config():
    try:
        if os.path.exists(SOURCES_CONFIG_FILE):
            with open(SOURCES_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "sources" in data:
                    return data
    except Exception:
        pass
    save_sources_config(DEFAULT_SOURCES_CONFIG)
    return json.loads(json.dumps(DEFAULT_SOURCES_CONFIG))


def save_sources_config(cfg):
    try:
        with open(SOURCES_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_active_domain(source_key, default_domain):
    try:
        cfg = load_sources_config()
        dom = ((cfg.get("sources") or {}).get(source_key) or {}).get("active_domain")
        if dom and dom.startswith("http"):
            return dom.rstrip("/")
    except Exception:
        pass
    return default_domain.rstrip("/")


def _probe_domain_fast(base_url, test_path="/", timeout=4):
    """Teste si un domaine répond en moins de 4 secondes sans blocage FAI/DNS."""
    u = base_url.rstrip("/") + (test_path if test_path.startswith("/") else "/" + test_path)
    t0 = time.time()
    try:
        r = scraper.get(u, timeout=timeout, allow_redirects=True)
        ms = int(round((time.time() - t0) * 1000))
        if r.status_code < 400 and len(r.text or "") > 40:
            low = (r.text or "")[:1500].lower()
            if "domain for sale" not in low and "parked" not in low:
                return True, ms, r.url.rstrip("/")
    except Exception:
        pass
    return False, 0, ""


def run_stream_healer(single_key=None):
    """Vérifie chaque source de streaming et répare automatiquement les domaines bloqués ou déplacés."""
    cfg = load_sources_config()
    sources = cfg.get("sources") or {}
    healed_count = 0
    ok_count = 0
    keys_to_check = [single_key] if (single_key and single_key in sources) else list(sources.keys())

    for k in keys_to_check:
        info = sources[k]
        cur_dom = (info.get("active_domain") or "").rstrip("/")
        t_path = info.get("test_path") or "/"
        base_name = info.get("base_name") or k.replace("_", "-")

        ok, ms, _ = _probe_domain_fast(cur_dom, t_path, timeout=4)
        if ok:
            info["status"] = "ok"
            info["latency_ms"] = ms
            ok_count += 1
            continue

        # Domaine actuel inaccessible -> recherche automatique d'un miroir/nouvelle extension
        write_log(f"🛠️ Stream Healer : {cur_dom} ne répond pas, test des extensions de secours...")
        found_new = False
        for ext in (info.get("fallback_extensions") or info.get("extensions") or []):
            cand_dom = f"https://{base_name}.{ext.lstrip('.')}"
            if cand_dom.lower() == cur_dom.lower():
                continue
            ok_c, ms_c, _ = _probe_domain_fast(cand_dom, t_path, timeout=4)
            if ok_c:
                old_dom = cur_dom
                info["active_domain"] = cand_dom
                info["status"] = "healed"
                info["latency_ms"] = ms_c
                info["healed_from"] = old_dom
                healed_count += 1
                ok_count += 1
                found_new = True
                write_log(f"✅ Stream Healer : {base_name} réparé automatiquement ({old_dom} -> {cand_dom} en {ms_c}ms)")
                break

        # En dernier recours : recherche DuckDuckGo HTML pour découvrir la nouvelle extension officielle
        if not found_new:
            try:
                q_ddg = info.get("search_query") or f"{base_name} site officiel"
                r_ddg = scraper.get(
                    f"https://html.duckduckgo.com/html/?q={quote_plus(q_ddg)}",
                    timeout=5,
                )
                rx = re.compile(
                    rf"https?://(?:www\.)?({re.escape(base_name)}\.[a-z]{{2,6}})",
                    re.IGNORECASE,
                )
                seen_hosts = set()
                for m_h in rx.finditer(r_ddg.text or ""):
                    cand_dom = f"https://{m_h.group(1).lower()}"
                    if cand_dom in seen_hosts:
                        continue
                    seen_hosts.add(cand_dom)
                    ok_d, ms_d, _ = _probe_domain_fast(cand_dom, t_path, timeout=4)
                    if ok_d:
                        old_dom = cur_dom
                        info["active_domain"] = cand_dom
                        info["status"] = "healed"
                        info["latency_ms"] = ms_d
                        info["healed_from"] = old_dom
                        healed_count += 1
                        ok_count += 1
                        found_new = True
                        write_log(f"✅ Stream Healer (DDG) : {base_name} découvert sur {cand_dom} ({ms_d}ms)")
                        break
            except Exception as e:
                write_log(f"Stream Healer DDG info ({base_name}): {e}")

        if not found_new:
            info["status"] = "degraded"
            info["latency_ms"] = 0

    cfg["last_check"] = time.strftime("%d/%m/%Y %H:%M:%S")
    cfg["last_status"] = (
        f"Opérationnel ({ok_count}/{len(sources)} sources actives"
        + (f", {healed_count} réparée(s)" if healed_count else "")
        + ")"
    )
    save_sources_config(cfg)
    return cfg


# ==============================================================================
# DÉCODEURS MULTI-HÉBERGEURS & VÉRIFICATEUR VIDÉO ANTI-TRAILER / ANTI-ERREUR
# ==============================================================================
def normalize_as_url(u):
    u = (u or "").strip()
    as_dom = get_active_domain("anime_sama", "https://anime-sama.to")
    if u.startswith("/"):
        u = as_dom + u
    u = re.sub(r"https?://(www\.)?anime-sama\.[a-z]+", as_dom, u)
    return u.rstrip("/") + "/"


def unpack_p_a_c_k_e_d(text):
    """Décompresse les scripts JS offusqués eval(function(p,a,c,k,e,d){...})
    utilisés par Uqload, Smoothpre, VidMoly, Ansembed, OneUpload, FileLions, StreamWish."""
    out = []
    pattern = re.compile(
        r"eval\(function\(p,a,c,k,e,[dr]\)\{.*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)",
        re.DOTALL,
    )

    def baseN(num, b):
        chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if num == 0:
            return "0"
        res = ""
        while num > 0:
            res = chars[num % b] + res
            num //= b
        return res

    for m in pattern.finditer(text or ""):
        try:
            p, a, c, k = (
                m.group(1),
                int(m.group(2)),
                int(m.group(3)),
                m.group(4).split("|"),
            )
            for i in range(c - 1, -1, -1):
                if i < len(k) and k[i]:
                    token = baseN(i, a)
                    p = re.sub(r"\b" + re.escape(token) + r"\b", lambda _, val=k[i]: val, p)
            out.append(p)
        except Exception:
            pass
    return "\n".join(out)


def decode_voe_payload(html_text):
    """Décode le flux HLS réel des domaines rotatifs VOE (/e/xxxx) et ignore le faux BigBuckBunny."""
    try:
        m_json = re.search(
            r'<script type="application/json">\s*\["([^"]+)"\]\s*</script>', html_text
        )
        if m_json:
            enc = m_json.group(1)
            step1 = codecs.decode(enc, "rot_13")
            for sym in ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]:
                step1 = step1.replace(sym, "")
            step2 = base64.b64decode(step1).decode("utf-8", errors="ignore")
            step3 = "".join(chr(ord(c) - 3) for c in step2)[::-1]
            step4 = json.loads(
                base64.b64decode(step3).decode("utf-8", errors="ignore")
            )
            if step4.get("source"):
                return step4["source"]
    except Exception:
        pass
    return None


def verify_downloaded_video(file_path, media_type="episode", min_duration_sec=180):
    """
    Vérifie avec FFmpeg que la vidéo téléchargée est bien un épisode/film complet :
    - Rejette les vidéos "Sendvid - This video is temporarily unavailable" (5s à 30s, < 3 Mo)
    - Rejette les bandes-annonces / trailers (1 à 3 min pour un film ou une série dramatique)
    - Supprime automatiquement le fichier invalide pour que le serveur passe à la source suivante !
    """
    if not os.path.exists(file_path):
        return False, "Fichier introuvable"

    size_bytes = os.path.getsize(file_path)
    min_bytes = 25 * 1048576 if media_type == "movie" else 3 * 1048576
    if size_bytes < min_bytes:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return (
            False,
            f"Fichier trop petit ({size_bytes / 1048576:.2f} Mo = vidéo indisponible ou erreur)",
        )

    ffmpeg_bin = os.path.join(BIN_DIR, "ffmpeg.exe")
    if not os.path.exists(ffmpeg_bin):
        return True, "OK"

    try:
        r = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=15,
        )
        info = (r.stdout or "") + "\n" + (r.stderr or "")
        if "Video:" not in info:
            os.remove(file_path)
            return False, "Aucune piste vidéo valide détectée"

        m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if m_dur:
            hh, mm, ss = (
                int(m_dur.group(1)),
                int(m_dur.group(2)),
                float(m_dur.group(3)),
            )
            total_sec = hh * 3600 + mm * 60 + ss
            required_sec = 1500 if media_type == "movie" else min_duration_sec
            if total_sec < required_sec:
                os.remove(file_path)
                return (
                    False,
                    f"Durée trop courte ({int(total_sec)}s < {required_sec}s : bande-annonce ou vidéo indisponible rejetée)",
                )
            return True, f"{int(total_sec // 60)}m{int(total_sec % 60):02d}s ({size_bytes / 1048576:.1f} Mo)"
    except Exception as e:
        write_log(f"Info vérificateur ffmpeg: {e}")

    return True, f"{size_bytes / 1048576:.1f} Mo"


def is_sendvid_placeholder(mp4_url, referer="https://sendvid.com/"):
    """Détecte avant même le téléchargement si Sendvid renvoie son clip de 36 Ko
    'This video is temporarily unavailable'."""
    try:
        rh = requests.head(
            mp4_url,
            headers={"Referer": referer, "User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
            timeout=8,
        )
        cl = int(rh.headers.get("Content-Length", 0) or 0)
        if 0 < cl < 3500000:
            write_log(
                f"⚠️ Sendvid : vidéo indisponible détectée ({cl // 1024} Ko) -> ignorée."
            )
            return True
        if "unavailable" in rh.url.lower() or "error" in rh.url.lower():
            return True
    except Exception:
        pass
    return False


def resolve_direct_stream(embed_url):
    u = (embed_url or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    origin_m = re.match(r"(https?://[^/]+/)", u)
    default_ref = origin_m.group(1) if origin_m else "https://anime-sama.to/"
    u_low = u.lower()

    try:
        # 1. Sendvid (avec détection anti-"This video is temporarily unavailable")
        if "sendvid.com" in u_low:
            r = scraper.get(u, headers={"Referer": default_ref}, timeout=12)
            if "temporarily unavailable" in r.text.lower() or "video not found" in r.text.lower():
                write_log("⚠️ Sendvid : page indique vidéo indisponible -> passage au suivant.")
                return "", ""
            m = re.search(r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)', r.text)
            if m:
                mp4_u = m.group(1)
                if is_sendvid_placeholder(mp4_u, u):
                    return "", ""
                return mp4_u, u
            return "", ""

        # 2. VidMoly & Ansembed (lecteur principal Anime-Sama 1080p)
        if any(h in u_low for h in ["vidmoly.", "ansembed."]):
            u_target = u.replace("vidmoly.to", "vidmoly.net")
            r = scraper.get(u_target, headers={"Referer": "https://anime-sama.to/"}, timeout=12)
            combined = r.text + "\n" + unpack_p_a_c_k_e_d(r.text)
            m = re.search(
                r'(https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*)', combined
            )
            if m:
                ref_host = re.match(r"(https?://[^/]+/)", u_target).group(1)
                return m.group(1), ref_host

        # 3. Uqload (.vc, .to, .io, .net, .co) avec décompresseur JS p,a,c,k,e,d
        if "uqload." in u_low:
            r = scraper.get(u, headers={"Referer": "https://anime-sama.to/"}, timeout=12)
            combined = r.text + "\n" + unpack_p_a_c_k_e_d(r.text)
            m = re.search(
                r'(https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*)', combined
            )
            if m:
                ref_host = re.match(r"(https?://[^/]+/)", r.url).group(1)
                return m.group(1), ref_host
            return "", ""

        # 4. Smoothpre / Movearnpre / VidHide / FileLions / StreamWish / OneUpload / LuluStream
        if any(
            h in u_low
            for h in [
                "smoothpre.",
                "movearnpre.",
                "vidhide",
                "filelions",
                "streamwish",
                "oneupload.",
                "lulustream.",
                "luluvdo.",
                "lulu.st",
            ]
        ):
            r = scraper.get(u, headers={"Referer": "https://anime-sama.to/"}, timeout=12)
            combined = r.text + "\n" + unpack_p_a_c_k_e_d(r.text)
            m = re.search(
                r'(https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*)', combined
            )
            if m:
                ref_host = re.match(r"(https?://[^/]+/)", r.url).group(1)
                return m.group(1), ref_host
            return "", ""

        # 5. VOE & tous ses domaines miroirs rotatifs (ex: https://xxx.com/e/wzcwigavv5el)
        if any(h in u_low for h in ["voe.sx", "voe.", "voe-network", "launchreleas"]) or re.search(
            r"^https?://[^/]+/e/[a-zA-Z0-9]{10,14}$", u
        ):
            r = scraper.get(u, headers={"Referer": default_ref}, timeout=12)
            m_redir = re.search(
                r"window\.location\.href\s*=\s*['\"](https?://[^'\"]+)['\"]", r.text
            )
            if m_redir:
                u = m_redir.group(1)
                r = scraper.get(u, headers={"Referer": default_ref}, timeout=12)

            voe_src = decode_voe_payload(r.text)
            if voe_src:
                ref_host = re.match(r"(https?://[^/]+/)", r.url).group(1)
                return voe_src, ref_host

            m_hls = re.search(r"['\"]hls['\"]\s*:\s*['\"]([^'\"]+)['\"]", r.text)
            if m_hls:
                val = m_hls.group(1)
                if val.startswith("http"):
                    return val, u
                try:
                    dec = base64.b64decode(val).decode("utf-8", errors="ignore")
                    if dec.startswith("http"):
                        return dec, u
                except Exception:
                    pass
            for m_m3u8 in re.findall(
                r'(https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*)', r.text
            ):
                if "bigbuckbunny" not in m_m3u8.lower() and "test-videos" not in m_m3u8.lower():
                    return m_m3u8, u
            return "", ""

        # 6. Sibnet.ru
        if "sibnet.ru" in u_low:
            r = requests.get(
                u,
                headers={
                    "Referer": "https://video.sibnet.ru/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                },
                timeout=10,
            )
            m = re.search(r'(/v/[^"\']+\.mp4)', r.text)
            if m:
                return "https://video.sibnet.ru" + m.group(1), "https://video.sibnet.ru/"
            return "", ""

        # 7. Doodstream
        if any(
            h in u_low for h in ["dood.", "d000d.", "ds2play.", "doods.", "doodstream."]
        ):
            u_emb = u.replace("/d/", "/e/")
            r = scraper.get(u_emb, headers={"Referer": default_ref}, timeout=12)
            host_root = re.match(r"(https?://[^/]+)", r.url).group(1)
            m_pass = re.search(r"(/pass_md5/[^'\"]+)", r.text)
            if m_pass:
                pass_url = host_root + m_pass.group(1)
                r_token = scraper.get(
                    pass_url, headers={"Referer": r.url}, timeout=10
                )
                if r_token.status_code == 200 and r_token.text.startswith("http"):
                    token_str = m_pass.group(1).split("/")[-1]
                    direct = (
                        f"{r_token.text.strip()}1234567890"
                        f"?token={token_str}&expiry={int(time.time() * 1000)}"
                    )
                    return direct, r.url
            return "", ""

        # 8. Vidoza
        if any(h in u_low for h in ["vidoza.", "videzz."]):
            r = scraper.get(u, headers={"Referer": default_ref}, timeout=12)
            m = re.search(
                r'src\s*:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']', r.text
            ) or re.search(
                r'<source\s+src=["\'](https?://[^"\']+\.mp4[^"\']*)["\']', r.text
            )
            if m:
                return m.group(1), u
            return "", ""

        # 9. Autre page générique (avec unpacker JS)
        if not u_low.endswith((".mp4", ".m3u8", ".mkv")) and not any(
            yt in u_low
            for yt in [
                "youtube.com",
                "youtu.be",
                "dailymotion.com",
                "ytsearch",
                "vk.com",
                "vkvideo.ru",
            ]
        ):
            r = scraper.get(u, headers={"Referer": default_ref}, timeout=10)
            combined = r.text + "\n" + unpack_p_a_c_k_e_d(r.text)
            for m_u in re.findall(
                r'["\'](https?://[^"\'\s<>]+\.(?:mp4|m3u8)[^"\'\s<>]*)["\']',
                combined,
            ):
                if "bigbuckbunny" not in m_u.lower():
                    return m_u, u
    except Exception as e:
        write_log(f"Resolve info ({u[:45]}): {e}")

    return u, default_ref


def download_with_progress(embed_url, out_path, media_type="episode", min_duration_sec=180):
    global CURRENT_PROC
    if STATUS["stop"]:
        return False
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    direct_url, referer = resolve_direct_stream(embed_url)
    if not direct_url:
        return False

    # Téléchargement direct HTTP si lien .mp4 direct
    if ".mp4" in direct_url and ".m3u8" not in direct_url and not direct_url.startswith("ytsearch"):
        try:
            r = scraper.get(
                direct_url,
                headers={"Referer": referer},
                stream=True,
                timeout=20,
                allow_redirects=True,
            )
            cl = int(r.headers.get("content-length", 0) or 0)
            ctype = r.headers.get("content-type", "").lower()
            # Rejette immédiatement les vidéos < 3 Mo (ex: Sendvid "temporarily unavailable")
            if 0 < cl < 3000000:
                write_log(
                    f"⚠️ Flux rejeté avant téléchargement ({cl // 1024} Ko = vidéo indisponible)"
                )
                return False
            if r.status_code == 200 and (cl >= 3000000 or "video" in ctype or "octet-stream" in ctype):
                downloaded, t0, tmp_path = 0, time.time(), out_path + ".part"
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=262144):
                        if STATUS["stop"]:
                            f.close()
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if cl > 0:
                                STATUS["percent"] = round((downloaded / cl) * 100, 1)
                                spd = (downloaded / 1048576) / max(time.time() - t0, 0.1)
                                STATUS["speed"] = (
                                    f"{downloaded/1048576:.1f}/{cl/1048576:.1f} Mo "
                                    f"({spd:.1f} Mo/s)"
                                )
                            else:
                                spd = (downloaded / 1048576) / max(time.time() - t0, 0.1)
                                STATUS["speed"] = f"{downloaded/1048576:.1f} Mo ({spd:.1f} Mo/s)"
                if os.path.exists(tmp_path):
                    os.replace(tmp_path, out_path)
                    ok_v, msg_v = verify_downloaded_video(
                        out_path, media_type=media_type, min_duration_sec=min_duration_sec
                    )
                    if ok_v:
                        write_log(f"✔️ Vérification vidéo OK : {msg_v}")
                        return True
                    else:
                        write_log(f"⚠️ Vérificateur a rejeté la vidéo : {msg_v}")
                        return False
        except Exception as e:
            write_log(f"Direct stream fallback to yt-dlp: {e}")

    # Nettoyage d'un éventuel fichier partiel précédent
    for p_clean in (out_path, out_path + ".part"):
        if os.path.exists(p_clean):
            try:
                os.remove(p_clean)
            except Exception:
                pass

    ytdlp_bin = os.path.join(BIN_DIR, "yt-dlp.exe")
    cmd = [
        ytdlp_bin,
        "--no-playlist",
        "--no-check-certificate",
        "--geo-bypass",
        "--concurrent-fragments",
        "4",
        "-S",
        "res:1080,codec:h264:m4a",
        "--merge-output-format",
        "mp4",
        "--newline",
        "-o",
        out_path,
    ]
    # Filtre anti-bande-annonce directement dans yt-dlp si c'est une recherche !
    if direct_url.startswith("ytsearch"):
        cmd.extend(["--match-filter", f"duration >= {min_duration_sec} & !is_live"])
    elif referer:
        cmd.extend(["--referer", referer])
    cmd.append(direct_url)

    CURRENT_PROC = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        env=get_env(),
    )
    last_err = ""
    for line in CURRENT_PROC.stdout:
        if STATUS["stop"]:
            CURRENT_PROC.kill()
            return False
        line_s = line.strip()
        if "[download]" in line_s and "%" in line_s:
            m_pct = re.search(r"(\d+(?:\.\d+)?)%", line_s)
            m_spd = re.search(r"at\s+([0-9.]+[a-zA-Z/]+)", line_s)
            if m_pct:
                STATUS["percent"] = float(m_pct.group(1))
            if m_spd:
                STATUS["speed"] = m_spd.group(1)
        elif "ERROR:" in line_s:
            last_err = line_s
            write_log(f"[YT-DLP] {line_s}")
    CURRENT_PROC.wait()

    if not os.path.exists(out_path) or last_err:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        return False

    ok_v, msg_v = verify_downloaded_video(
        out_path, media_type=media_type, min_duration_sec=min_duration_sec
    )
    if ok_v:
        write_log(f"✔️ Vérification vidéo OK : {msg_v}")
        return True
    else:
        write_log(f"⚠️ Vérificateur a rejeté le fichier : {msg_v}")
        return False


def parse_episodes_js(js_url):
    try:
        season_page = js_url.rsplit("/", 1)[0] + "/"
        r = scraper.get(js_url, headers={"Referer": season_page}, timeout=10)
        if r.status_code != 200 or "eps" not in r.text:
            rp = scraper.get(season_page, timeout=10)
            m_src = re.search(r'src=["\']([^"\']*episodes\.js[^"\']*)["\']', rp.text)
            if m_src:
                r = scraper.get(
                    urljoin(season_page, m_src.group(1)),
                    headers={"Referer": season_page},
                    timeout=10,
                )
        text = re.sub(r"/\*.*?\*/", "", r.text, flags=re.DOTALL)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        arrays = re.findall(
            r"(?:var|let|const)?\s*eps\w*\s*=\s*\[(.*?)\]", text, flags=re.DOTALL
        )
        players = [re.findall(r'["\']((?:https?:)?//[^"\']+)["\']', arr) for arr in arrays]
        players = [p for p in players if p]
        if not players:
            return []
        max_len = max(len(p) for p in players)
        episodes = []
        # Priorité aux lecteurs HD fiables avec décodeur intégré (Ansembed/Vidmoly, Uqload, Smoothpre, VOE)
        # et relégation de Sendvid / Sibnet en dernier secours
        host_prio = {
            "ansembed": 0,
            "vidmoly": 1,
            "uqload": 2,
            "smoothpre": 3,
            "movearnpre": 3,
            "oneupload": 4,
            "lulu": 5,
            "vidoza": 6,
            "dood": 7,
            "sibnet": 9,
            "sendvid": 10,
        }
        for i in range(max_len):
            ep_urls = []
            for p in players:
                if i < len(p) and p[i]:
                    u = (
                        ("https:" + p[i].strip())
                        if p[i].strip().startswith("//")
                        else p[i].strip()
                    )
                    if "myvi.tv" not in u:
                        ep_urls.append(u)
            ep_urls.sort(
                key=lambda u: next(
                    (rank for h, rank in host_prio.items() if h in u.lower()),
                    5 if "/e/" in u.lower() else 8,
                )
            )
            episodes.append(list(dict.fromkeys(ep_urls)))
        return episodes
    except Exception:
        return []


def season_download_worker(title, season_name, js_url, start_ep, end_ep, target_root=None):
    STATUS["active"], STATUS["stop"], STATUS["error"] = True, False, ""
    clean_t = clean_name(title)
    m_snum = re.search(r"(\d+)", str(season_name))
    s_num = int(m_snum.group(1)) if m_snum else 1
    base_folder = target_root if target_root else ANIME_DIR
    safe_dir = os.path.join(base_folder, clean_t, f"Season {s_num:02d}")
    os.makedirs(safe_dir, exist_ok=True)
    STATUS["title"] = f"{clean_t} - Saison {s_num:02d}"
    try:
        episodes = parse_episodes_js(js_url)
        # Récupère aussi l'autre langue (VOSTFR <-> VF) en secours si un lecteur est mort
        alt_js_url = (
            js_url.replace("/vf/", "/vostfr/")
            if "/vf/" in js_url
            else js_url.replace("/vostfr/", "/vf/")
        )
        alt_episodes = parse_episodes_js(alt_js_url) if alt_js_url != js_url else []

        s_idx = max(int(start_ep) - 1, 0)
        e_idx = min(int(end_ep), len(episodes))
        for idx in range(s_idx, e_idx):
            if STATUS["stop"]:
                break
            ep_num = idx + 1
            out_file = os.path.join(
                safe_dir, f"{clean_t} - S{s_num:02d}E{ep_num:02d}.mp4"
            )
            if os.path.exists(out_file):
                ok_existing, _ = verify_downloaded_video(out_file, "anime", 180)
                if ok_existing:
                    continue

            candidate_embeds = list(episodes[idx])
            if idx < len(alt_episodes):
                for alt_u in alt_episodes[idx]:
                    if alt_u not in candidate_embeds:
                        candidate_embeds.append(alt_u)

            ep_ok = False
            for p_i, embed in enumerate(candidate_embeds, 1):
                if STATUS["stop"]:
                    break
                host = re.sub(r"^https?://(www\.)?", "", embed).split("/")[0]
                STATUS["step"] = f"S{s_num:02d}E{ep_num:02d} • Lecteur {p_i}/{len(candidate_embeds)} ({host})"
                STATUS["percent"] = 0
                if download_with_progress(embed, out_file, media_type="anime", min_duration_sec=180):
                    write_log(f"✅ {clean_t} S{s_num:02d}E{ep_num:02d} téléchargé et vérifié !")
                    refresh_jellyfin_library()
                    ep_ok = True
                    break
            if not ep_ok and not STATUS["stop"]:
                write_log(f"❌ Tous les lecteurs ont échoué pour {clean_t} S{s_num:02d}E{ep_num:02d}")
        if STATUS["stop"]:
            STATUS["title"] = "Aucun téléchargement actif"
            STATUS["step"] = "⏹️ Téléchargement arrêté par l'utilisateur."
            STATUS["percent"] = 0
            STATUS["speed"] = "-"
        else:
            refresh_jellyfin_library()
            STATUS["step"] = "✅ Terminé ! Épisodes vérifiés et disponibles dans Jellyfin."
            STATUS["percent"] = 100
    except Exception as e:
        STATUS["error"] = str(e)
        write_log(f"❌ Erreur téléchargement saison: {e}")
    finally:
        STATUS["active"] = False


# ==============================================================================
# CATALOGUE UNIVERSEL : TENDANCES, DISNEY+, HBO MAX, ANIMÉS, FILMS & SÉRIES
# ==============================================================================
CURATED_DISNEY = [
    {"q": "The Mandalorian", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Loki", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Andor", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Daredevil: Born Again", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Ahsoka", "type": "series", "badge": "🏰 Disney+"},
    {"q": "X-Men '97", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Moon Knight", "type": "series", "badge": "🏰 Disney+"},
    {"q": "WandaVision", "type": "series", "badge": "🏰 Disney+"},
    {"q": "Deadpool & Wolverine", "type": "movie", "badge": "🏰 Disney+"},
    {"q": "Vice-Versa 2", "type": "movie", "badge": "🏰 Disney+"},
    {"q": "Avatar : La Voie de l'eau", "type": "movie", "badge": "🏰 Disney+"},
]

CURATED_HBO = [
    {"q": "House of the Dragon", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "The Last of Us", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "The Penguin", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "Game of Thrones", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "Succession", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "Euphoria", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "The White Lotus", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "True Detective", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "Chernobyl", "type": "series", "badge": "🐉 HBO Max"},
    {"q": "Dune : Deuxième Partie", "type": "movie", "badge": "🐉 HBO Max"},
    {"q": "The Batman", "type": "movie", "badge": "🐉 HBO Max"},
]

CURATED_ANIMES = [
    "Solo Leveling",
    "One Piece",
    "Jujutsu Kaisen",
    "Demon Slayer",
    "Attack on Titan",
    "Chainsaw Man",
    "Bleach",
    "Hunter x Hunter",
    "Blue Lock",
    "Dandadan",
    "Frieren",
    "Naruto Shippuden",
]

CATALOG_CACHE = {}


def search_anime_sama_items(query_str, limit=10):
    res = []
    as_dom = get_active_domain("anime_sama", "https://anime-sama.to")
    try:
        try:
            r = scraper.post(
                f"{as_dom}/template-php/defaut/fetch.php",
                data={"query": query_str},
                timeout=6,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")
        except Exception:
            run_stream_healer("anime_sama")
            as_dom = get_active_domain("anime_sama", "https://anime-sama.to")
            r = scraper.post(
                f"{as_dom}/template-php/defaut/fetch.php",
                data={"query": query_str},
                timeout=8,
            )
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            if "/catalogue/" in a["href"]:
                full_u = normalize_as_url(a["href"])
                if full_u in seen:
                    continue
                seen.add(full_u)
                title = (
                    clean_name(a.get_text(" | ", strip=True).split(" | ")[0])
                    or full_u.split("/")[-2].replace("-", " ").title()
                )
                img = a.find("img")["src"] if a.find("img") else ""
                res.append(
                    {
                        "id": f"anime:{full_u}",
                        "url": full_u,
                        "imdb_id": "",
                        "media_type": "anime",
                        "title": title,
                        "year": "VF/VOSTFR",
                        "badge": "🎌 Animé",
                        "image": img,
                        "synopsis": f"Catalogue Anime-Sama • Saisons VF & VOSTFR disponibles ({title}).",
                    }
                )
                if len(res) >= limit:
                    break
    except Exception as e:
        write_log(f"Anime search err: {e}")
    return res


def fetch_tvmaze_show(query_str, badge_override=None):
    try:
        r = requests.get(
            "https://api.tvmaze.com/singlesearch/shows",
            params={"q": query_str},
            timeout=6,
        )
        if r.status_code != 200:
            return None
        sh = r.json()
        img = (sh.get("image") or {}).get("original") or (sh.get("image") or {}).get("medium") or ""
        wc = (sh.get("webChannel") or {}).get("name") or (sh.get("network") or {}).get("name") or "Série TV"
        badge = badge_override or (
            "🏰 Disney+"
            if "disney" in wc.lower()
            else ("🐉 HBO Max" if "hbo" in wc.lower() or wc.lower() == "max" else f"📺 {wc}")
        )
        year = (sh.get("premiered") or "")[:4] or "2024"
        imdb_id = (sh.get("externals") or {}).get("imdb") or ""
        return {
            "id": f"tvmaze:{sh['id']}",
            "tvmaze_id": sh["id"],
            "imdb_id": imdb_id,
            "media_type": "series",
            "title": sh.get("name", query_str),
            "year": year,
            "badge": badge,
            "image": img,
            "synopsis": strip_html(sh.get("summary") or "Série disponible en streaming et téléchargement HD."),
        }
    except Exception:
        return None


def fetch_itunes_movies(query_str, limit=8, badge_override=None):
    items = []
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={
                "term": query_str,
                "country": "FR",
                "lang": "fr_fr",
                "entity": "movie",
                "limit": limit,
            },
            timeout=6,
        )
        for m in r.json().get("results", []):
            art = (m.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
            year = (m.get("releaseDate") or "")[:4] or "2024"
            title = m.get("trackName") or query_str
            items.append(
                {
                    "id": f"itunes:{m.get('trackId', title)}",
                    "imdb_id": "",
                    "media_type": "movie",
                    "title": title,
                    "year": year,
                    "badge": badge_override or f"🍿 {m.get('primaryGenreName', 'Film HD')}",
                    "image": art,
                    "synopsis": m.get("longDescription")
                    or m.get("shortDescription")
                    or f"Film HD ({year}) disponible pour Jellyfin.",
                }
            )
    except Exception:
        pass
    return items


def discover_embed_candidates(
    title, year="", media_type="movie", season=1, episode=1, imdb_id="", lang="vf"
):
    """Recherche multi-sources élargie avec priorité stricte de langue (VF, VOSTFR, VO)
    et 0 bande-annonce."""
    candidates = []
    lang = (lang or "vf").lower().strip()
    if lang not in ("vf", "vostfr", "vo"):
        lang = "vf"

    if lang == "vf":
        as_langs = ["vf", "vostfr", "vj"]
    elif lang == "vostfr":
        as_langs = ["vostfr", "vf", "vj"]
    else:
        as_langs = ["vj", "vostfr", "vf"]

    norm_target = re.sub(r"[^a-z0-9]", "", title.lower())

    # 1. Vérification stricte sur Anime-Sama selon la langue choisie (VF / VOSTFR / VO)
    try:
        as_dom = get_active_domain("anime_sama", "https://anime-sama.to")
        r_as = scraper.post(
            f"{as_dom}/template-php/defaut/fetch.php",
            data={"query": title},
            timeout=6,
        )
        soup = BeautifulSoup(r_as.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "/catalogue/" in a["href"]:
                slug_part = a["href"].rstrip("/").split("/")[-1]
                norm_slug = re.sub(r"[^a-z0-9]", "", slug_part.lower())
                if norm_target and (norm_target in norm_slug or norm_slug in norm_target):
                    cat_url = normalize_as_url(a["href"])
                    if media_type == "movie":
                        for l_code in as_langs:
                            js_u = f"{cat_url}film/{l_code}/episodes.js"
                            eps = parse_episodes_js(js_u)
                            if eps and eps[0]:
                                candidates.extend(eps[0])
                    else:
                        for l_code in as_langs:
                            js_u = f"{cat_url}saison{int(season)}/{l_code}/episodes.js"
                            eps = parse_episodes_js(js_u)
                            ep_idx = max(int(episode) - 1, 0)
                            if eps and ep_idx < len(eps):
                                candidates.extend(eps[ep_idx])
                    break
    except Exception:
        pass

    # 2. Résolution de l'identifiant IMDb exact si absent
    if not imdb_id:
        try:
            q_clean = re.sub(r"[^a-zA-Z0-9 ]", "", title).strip().lower()
            first_c = q_clean[0] if q_clean else "a"
            r_im = requests.get(
                f"https://v3.sg.media-imdb.com/suggestion/{first_c}/{quote_plus(q_clean[:25])}.json",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            ).json()
            for d in r_im.get("d", []):
                if str(d.get("id", "")).startswith("tt"):
                    imdb_id = d["id"]
                    break
        except Exception:
            pass

    # 3. Agrégateurs Multi-Hébergeurs ordonnés selon la langue (VF / VOSTFR / VO)
    if imdb_id:
        frembed_dom = get_active_domain("frembed", "https://frembed.pro")
        vidsrc_dom = get_active_domain("vidsrc", "https://vidsrc.pm")
        autoembed_dom = get_active_domain("autoembed", "https://autoembed.co")
        multiembed_dom = get_active_domain("multiembed", "https://multiembed.mov")
        if media_type == "movie":
            if lang == "vf":
                embed_pages = [
                    f"{frembed_dom}/api/film.php?id={imdb_id}",
                    f"{vidsrc_dom}/embed/movie?imdb={imdb_id}&ds_lang=fr",
                    f"{autoembed_dom}/movie/imdb/{imdb_id}",
                    f"{multiembed_dom}/?video_id={imdb_id}",
                    f"https://www.2embed.cc/embed/{imdb_id}",
                ]
            elif lang == "vostfr":
                embed_pages = [
                    f"{vidsrc_dom}/embed/movie?imdb={imdb_id}&ds_lang=fr",
                    f"{frembed_dom}/api/film.php?id={imdb_id}",
                    f"{autoembed_dom}/movie/imdb/{imdb_id}",
                    f"{multiembed_dom}/?video_id={imdb_id}",
                    f"https://www.2embed.cc/embed/{imdb_id}",
                ]
            else:
                embed_pages = [
                    f"{vidsrc_dom}/embed/movie?imdb={imdb_id}",
                    f"{autoembed_dom}/movie/imdb/{imdb_id}",
                    f"https://www.2embed.cc/embed/{imdb_id}",
                    f"{multiembed_dom}/?video_id={imdb_id}",
                ]
        else:
            if lang == "vf":
                embed_pages = [
                    f"{frembed_dom}/api/serie.php?id={imdb_id}&sa={int(season)}&epi={int(episode)}",
                    f"{vidsrc_dom}/embed/tv?imdb={imdb_id}&season={int(season)}&episode={int(episode)}&ds_lang=fr",
                    f"{autoembed_dom}/tv/imdb/{imdb_id}-{int(season)}-{int(episode)}",
                    f"{multiembed_dom}/?video_id={imdb_id}&s={int(season)}&e={int(episode)}",
                    f"https://www.2embed.cc/embedtv/{imdb_id}&s={int(season)}&e={int(episode)}",
                ]
            elif lang == "vostfr":
                embed_pages = [
                    f"{vidsrc_dom}/embed/tv?imdb={imdb_id}&season={int(season)}&episode={int(episode)}&ds_lang=fr",
                    f"{frembed_dom}/api/serie.php?id={imdb_id}&sa={int(season)}&epi={int(episode)}",
                    f"{autoembed_dom}/tv/imdb/{imdb_id}-{int(season)}-{int(episode)}",
                    f"{multiembed_dom}/?video_id={imdb_id}&s={int(season)}&e={int(episode)}",
                    f"https://www.2embed.cc/embedtv/{imdb_id}&s={int(season)}&e={int(episode)}",
                ]
            else:
                embed_pages = [
                    f"{vidsrc_dom}/embed/tv?imdb={imdb_id}&season={int(season)}&episode={int(episode)}",
                    f"{autoembed_dom}/tv/imdb/{imdb_id}-{int(season)}-{int(episode)}",
                    f"https://www.2embed.cc/embedtv/{imdb_id}&s={int(season)}&e={int(episode)}",
                    f"{multiembed_dom}/?video_id={imdb_id}&s={int(season)}&e={int(episode)}",
                ]

        for ep_u in embed_pages:
            try:
                resp = scraper.get(ep_u, timeout=7)
                combined_txt = resp.text + "\n" + unpack_p_a_c_k_e_d(resp.text)
                found_hosts = re.findall(
                    r'(https?://(?:uqload|vidmoly|ansembed|smoothpre|movearnpre|oneupload|voe|vidoza|videzz|lulustream|luluvdo|dood|ds2play|sendvid|video\.sibnet)[^"\'\s<>]+)',
                    combined_txt,
                    flags=re.IGNORECASE,
                )
                candidates.extend(found_hosts)
                for m_stream in re.findall(
                    r'["\'](https?://[^"\'\s<>]+\.(?:m3u8|mp4)[^"\'\s<>]*)["\']',
                    combined_txt,
                ):
                    if "bigbuckbunny" not in m_stream.lower():
                        candidates.append(m_stream)
            except Exception:
                pass

    # 4. Recherche d'épisodes/films COMPLETS ordonnée selon la langue choisie (VF / VOSTFR / VO)
    if media_type == "movie":
        if lang == "vf":
            candidates.append(f"ytsearch3:{title} {year} film complet VF")
            candidates.append(f"ytsearch3:{title} {year} film complet francais")
            candidates.append(f"ytsearch3:{title} {year} full movie")
        elif lang == "vostfr":
            candidates.append(f"ytsearch3:{title} {year} film complet VOSTFR")
            candidates.append(f"ytsearch3:{title} {year} film complet VF")
            candidates.append(f"ytsearch3:{title} {year} full movie")
        else:
            candidates.append(f"ytsearch3:{title} {year} full movie")
            candidates.append(f"ytsearch3:{title} {year} film complet VF")
    else:
        if lang == "vf":
            candidates.append(
                f"ytsearch3:{title} Saison {int(season)} Episode {int(episode)} VF complet"
            )
            candidates.append(
                f"ytsearch3:{title} S{int(season):02d}E{int(episode):02d} VF"
            )
            candidates.append(
                f"ytsearch3:{title} S{int(season):02d}E{int(episode):02d} full episode"
            )
        elif lang == "vostfr":
            candidates.append(
                f"ytsearch3:{title} Saison {int(season)} Episode {int(episode)} VOSTFR complet"
            )
            candidates.append(
                f"ytsearch3:{title} S{int(season):02d}E{int(episode):02d} VOSTFR"
            )
            candidates.append(
                f"ytsearch3:{title} S{int(season):02d}E{int(episode):02d} full episode"
            )
        else:
            candidates.append(
                f"ytsearch3:{title} S{int(season):02d}E{int(episode):02d} full episode"
            )
            candidates.append(
                f"ytsearch3:{title} Saison {int(season)} Episode {int(episode)} VF complet"
            )

    return list(dict.fromkeys(candidates))


def media_download_worker(
    media_type,
    title,
    year="",
    season=1,
    start_ep=1,
    end_ep=1,
    imdb_id="",
    custom_url="",
    lang="vf",
):
    STATUS["active"], STATUS["stop"], STATUS["error"] = True, False, ""
    clean_t = clean_name(title)
    clean_y = re.sub(r"\D", "", str(year or ""))[:4]
    lang = (lang or "vf").lower().strip()
    if lang not in ("vf", "vostfr", "vo"):
        lang = "vf"
    lang_tag = lang.upper()

    # Détermine la durée minimale attendue (via TVMaze pour les séries, ex: Kaamelott = 180s, The Last of Us = 1200s)
    min_ep_duration = 600
    if media_type != "movie":
        if "kaamelott" in clean_t.lower():
            min_ep_duration = 180
        else:
            try:
                r_tv = requests.get(
                    "https://api.tvmaze.com/singlesearch/shows",
                    params={"q": clean_t},
                    timeout=4,
                )
                if r_tv.status_code == 200:
                    rt = int(r_tv.json().get("averageRuntime") or r_tv.json().get("runtime") or 30)
                    min_ep_duration = 180 if rt <= 12 else 900
            except Exception:
                min_ep_duration = 600

    try:
        if media_type == "movie":
            folder_label = f"{clean_t} ({clean_y})" if clean_y else clean_t
            target_dir = os.path.join(FILMS_DIR, folder_label)
            os.makedirs(target_dir, exist_ok=True)
            out_file = os.path.join(target_dir, f"{clean_t} [{lang_tag}].mp4")
            STATUS["title"] = f"🍿 Film ({lang_tag}) : {folder_label}"
            STATUS["percent"] = 0

            sources = (
                [custom_url.strip()]
                if custom_url and custom_url.strip()
                else discover_embed_candidates(
                    clean_t, clean_y, "movie", imdb_id=imdb_id, lang=lang
                )
            )
            success = False
            for idx, src in enumerate(sources, 1):
                if STATUS["stop"]:
                    break
                label_src = (
                    f"Recherche Film Complet {lang_tag} (>25 min)"
                    if src.startswith("ytsearch")
                    else re.sub(r"^https?://(www\.)?", "", src).split("/")[0]
                )
                STATUS["step"] = f"[{lang_tag}] Source {idx}/{len(sources)} ({label_src})..."
                if download_with_progress(src, out_file, media_type="movie", min_duration_sec=1500):
                    success = True
                    write_log(f"✅ Film complet ({lang_tag}) vérifié et classé dans Jellyfin : {out_file}")
                    break
            if STATUS["stop"]:
                STATUS["title"] = "Aucun téléchargement actif"
                STATUS["step"] = "⏹️ Téléchargement arrêté par l'utilisateur."
                STATUS["percent"] = 0
                STATUS["speed"] = "-"
            elif not success:
                STATUS["error"] = f"Aucune source complète {lang_tag} trouvée (bandes-annonces ignorées)."
                STATUS["step"] = f"⚠️ Aucune source complète {lang_tag} trouvée."
                write_log(f"⚠️ Aucune source complète validée pour {folder_label} ({lang_tag}).")
            else:
                refresh_jellyfin_library()
                STATUS["step"] = f"✅ Film complet ({lang_tag}) vérifié et disponible dans Jellyfin !"
                STATUS["percent"] = 100
        else:
            s_num = max(int(season or 1), 1)
            ep_s = max(int(start_ep or 1), 1)
            ep_e = max(int(end_ep or ep_s), ep_s)
            target_dir = os.path.join(SERIES_DIR, clean_t, f"Season {s_num:02d}")
            os.makedirs(target_dir, exist_ok=True)
            STATUS["title"] = f"📺 {clean_t} - Saison {s_num:02d} ({lang_tag})"

            for ep_num in range(ep_s, ep_e + 1):
                if STATUS["stop"]:
                    break
                out_file = os.path.join(
                    target_dir, f"{clean_t} - S{s_num:02d}E{ep_num:02d} [{lang_tag}].mp4"
                )
                if os.path.exists(out_file):
                    ok_ex, _ = verify_downloaded_video(out_file, "series", min_ep_duration)
                    if ok_ex:
                        continue
                sources = (
                    [custom_url.strip()]
                    if (custom_url and custom_url.strip() and ep_s == ep_e)
                    else discover_embed_candidates(
                        clean_t,
                        clean_y,
                        "series",
                        season=s_num,
                        episode=ep_num,
                        imdb_id=imdb_id,
                        lang=lang,
                    )
                )
                ep_done = False
                for idx, src in enumerate(sources, 1):
                    if STATUS["stop"]:
                        break
                    label_src = (
                        f"Recherche Épisode {lang_tag} (>{min_ep_duration//60} min)"
                        if src.startswith("ytsearch")
                        else re.sub(r"^https?://(www\.)?", "", src).split("/")[0]
                    )
                    STATUS["step"] = (
                        f"[{lang_tag}] S{s_num:02d}E{ep_num:02d} • Source {idx}/{len(sources)} ({label_src})"
                    )
                    STATUS["percent"] = 0
                    if download_with_progress(
                        src, out_file, media_type="series", min_duration_sec=min_ep_duration
                    ):
                        write_log(
                            f"✅ Épisode complet ({lang_tag}) vérifié : {clean_t} S{s_num:02d}E{ep_num:02d}"
                        )
                        refresh_jellyfin_library()
                        ep_done = True
                        break
                if not ep_done and not STATUS["stop"]:
                    write_log(
                        f"⚠️ Aucun épisode complet ({lang_tag}) trouvé pour {clean_t} S{s_num:02d}E{ep_num:02d}."
                    )
            if STATUS["stop"]:
                STATUS["title"] = "Aucun téléchargement actif"
                STATUS["step"] = "⏹️ Téléchargement arrêté par l'utilisateur."
                STATUS["percent"] = 0
                STATUS["speed"] = "-"
            else:
                refresh_jellyfin_library()
                STATUS["step"] = f"✅ Terminé ! Épisodes ({lang_tag}) vérifiés dans Jellyfin."
                STATUS["percent"] = 100
    except Exception as e:
        STATUS["error"] = str(e)
        write_log(f"❌ Erreur téléchargement média: {e}")
    finally:
        STATUS["active"] = False


# ==============================================================================
# MUSIQUE : POCHETTES HD (1000x1000 DEEZER), PHOTOS D'ARTISTES & TRI NAVIDROME / AMPERFY
# ==============================================================================
def download_image_file(img_url, dest_path, overwrite=False):
    """Télécharge une image HD (cover_xl ou picture_xl 1000x1000) sur le disque."""
    if not img_url:
        return None
    try:
        if (
            not overwrite
            and os.path.exists(dest_path)
            and os.path.getsize(dest_path) > 2000
        ):
            with open(dest_path, "rb") as f:
                return f.read()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        r = requests.get(img_url, timeout=10)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(dest_path, "wb") as f:
                f.write(r.content)
            return r.content
    except Exception as e:
        write_log(f"Info image HD ({dest_path}): {e}")
    return None


def fetch_deezer_hd_info(artist_str="", title_str="", album_str="", track_id=None, artist_id=None):
    """Récupère systématiquement cover_xl (1000x1000) et picture_xl (1000x1000) via l'API Deezer."""
    info = {
        "cover_xl": "",
        "artist_xl": "",
        "artist_name": (artist_str or "").strip(),
        "album_title": (album_str or "").strip(),
        "title": (title_str or "").strip(),
    }
    try:
        art_id_found = artist_id
        # 1. Si on a un ID de piste Deezer numérique
        if track_id and str(track_id).isdigit():
            tr = requests.get(f"https://api.deezer.com/track/{track_id}", timeout=8).json()
            if not tr.get("error"):
                alb_obj = tr.get("album") or {}
                art_obj = tr.get("artist") or {}
                info["cover_xl"] = (
                    alb_obj.get("cover_xl")
                    or alb_obj.get("cover_big")
                    or alb_obj.get("cover_medium")
                    or ""
                )
                info["artist_xl"] = (
                    art_obj.get("picture_xl")
                    or art_obj.get("picture_big")
                    or art_obj.get("picture_medium")
                    or ""
                )
                art_id_found = art_id_found or art_obj.get("id")
                if not info["artist_name"] and art_obj.get("name"):
                    info["artist_name"] = art_obj["name"]
                if not info["album_title"] and alb_obj.get("title"):
                    info["album_title"] = alb_obj["title"]

        # 2. Recherche par Artiste + Titre si cover_xl pas encore trouvée
        if not info["cover_xl"] and (artist_str or title_str):
            q_parts = [p for p in [artist_str, title_str] if p and p.lower() != "artiste"]
            q_str = " ".join(q_parts).strip()
            if q_str:
                sr = requests.get(
                    "https://api.deezer.com/search",
                    params={"q": q_str, "limit": 5},
                    timeout=8,
                ).json()
                data = sr.get("data") or []
                best = None
                for cand in data:
                    c_art = ((cand.get("artist") or {}).get("name") or "").lower()
                    if artist_str and artist_str.lower() in c_art:
                        best = cand
                        break
                if not best and data:
                    best = data[0]
                if best:
                    alb_obj = best.get("album") or {}
                    art_obj = best.get("artist") or {}
                    info["cover_xl"] = (
                        alb_obj.get("cover_xl")
                        or alb_obj.get("cover_big")
                        or alb_obj.get("cover_medium")
                        or ""
                    )
                    info["artist_xl"] = (
                        info["artist_xl"]
                        or art_obj.get("picture_xl")
                        or art_obj.get("picture_big")
                        or ""
                    )
                    art_id_found = art_id_found or art_obj.get("id")

        # 3. Récupération directe de la photo d'artiste picture_xl (1000x1000)
        if not info["artist_xl"]:
            if art_id_found:
                ar = requests.get(f"https://api.deezer.com/artist/{art_id_found}", timeout=6).json()
                info["artist_xl"] = (
                    ar.get("picture_xl")
                    or ar.get("picture_big")
                    or ar.get("picture_medium")
                    or ""
                )
            elif artist_str and artist_str.lower() not in ("artiste", "divers artistes", "singles"):
                ar_s = requests.get(
                    "https://api.deezer.com/search/artist",
                    params={"q": artist_str, "limit": 1},
                    timeout=6,
                ).json()
                a_list = ar_s.get("data") or []
                if a_list:
                    info["artist_xl"] = (
                        a_list[0].get("picture_xl")
                        or a_list[0].get("picture_big")
                        or a_list[0].get("picture_medium")
                        or ""
                    )
    except Exception as e:
        write_log(f"Info Deezer HD metadata: {e}")
    return info


def ensure_artist_and_album_art(artist_name, album_dir=None, cover_url="", artist_pic_url=""):
    """Enregistre systématiquement artist.jpg dans C:\\Serveur\\Medias\\Musique\\<Nom Artiste>\\artist.jpg
    et cover.jpg dans le dossier de l'album pour Navidrome et Amperfy."""
    art_clean = clean_name(artist_name or "")
    if art_clean and art_clean.lower() not in ("artiste", "divers artistes", "singles"):
        artist_dir = os.path.join(MUSIC_DIR, art_clean)
        artist_jpg = os.path.join(artist_dir, "artist.jpg")
        if not artist_pic_url and not os.path.exists(artist_jpg):
            hd = fetch_deezer_hd_info(artist_str=artist_name)
            artist_pic_url = hd.get("artist_xl") or ""
        if artist_pic_url:
            download_image_file(artist_pic_url, artist_jpg)

    if album_dir and cover_url:
        cover_jpg = os.path.join(album_dir, "cover.jpg")
        download_image_file(cover_url, cover_jpg)


def trigger_navidrome_scan():
    """Déclenche un scan rapide de Navidrome pour rafraîchir Amperfy immédiatement."""
    try:
        requests.get(
            "http://127.0.0.1:4533/rest/startScan.view?u=hugo&v=1.16.1&c=hub&f=json",
            headers={"X-ND-Client-Unique-Id": "hub"},
            timeout=3,
        )
    except Exception:
        pass


def apply_id3_tags(
    mp3_path,
    title,
    artist,
    album,
    album_artist,
    track_num=None,
    cover_url=None,
    cover_bytes=None,
):
    if not HAS_MUTAGEN or not os.path.exists(mp3_path):
        return
    try:
        try:
            tags = ID3(mp3_path)
        except ID3NoHeaderError:
            tags = ID3()

        for frame in ["TIT2", "TPE1", "TALB", "TPE2", "TRCK"]:
            tags.delall(frame)

        tags.add(TIT2(encoding=3, text=str(title)))
        tags.add(TPE1(encoding=3, text=str(artist)))
        tags.add(TALB(encoding=3, text=str(album)))
        tags.add(TPE2(encoding=3, text=str(album_artist)))
        if track_num is not None:
            tags.add(TRCK(encoding=3, text=str(track_num)))

        img_data = cover_bytes
        if not img_data and cover_url:
            try:
                # Force cover_xl 1000x1000 sur les URLs Deezer si c'était cover_medium (250x250)
                hi_url = re.sub(r"/\d+x\d+-000000-", "/1000x1000-000000-", str(cover_url))
                img_r = requests.get(hi_url, timeout=10)
                if img_r.status_code == 200 and len(img_r.content) > 800:
                    img_data = img_r.content
                elif hi_url != cover_url:
                    img_r2 = requests.get(cover_url, timeout=10)
                    if img_r2.status_code == 200 and len(img_r2.content) > 800:
                        img_data = img_r2.content
            except Exception:
                pass

        if img_data and len(img_data) > 800:
            tags.delall("APIC")
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=img_data,
                )
            )

        tags.save(mp3_path, v2_version=3)
    except Exception as e:
        write_log(f"Info tag ID3 ({os.path.basename(mp3_path)}): {e}")


def rebuild_singles_playlist():
    try:
        os.makedirs(MUSIC_SINGLES_DIR, exist_ok=True)
        lines = ["#EXTM3U"]
        for fname in sorted(os.listdir(MUSIC_SINGLES_DIR)):
            if fname.lower().endswith(".mp3"):
                lines.append(f"Singles/{fname}")
        with open(SINGLES_M3U, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        write_log(f"Info playlist Singles: {e}")


def cleanup_existing_music():
    """Maintient l'organisation par Artiste (<Nom Artiste>/<Nom Album>) et le dossier Singles
    sans écraser les pochettes HD APIC ni déplacer les dossiers d'artistes."""
    try:
        os.makedirs(MUSIC_DIR, exist_ok=True)
        os.makedirs(MUSIC_SINGLES_DIR, exist_ok=True)

        # Déplace uniquement les fichiers .mp3 isolés à la racine de Musique vers Singles
        for entry in os.listdir(MUSIC_DIR):
            full_p = os.path.join(MUSIC_DIR, entry)
            if os.path.isfile(full_p) and entry.lower().endswith(".mp3"):
                dest = os.path.join(MUSIC_SINGLES_DIR, entry)
                if not os.path.exists(dest):
                    shutil.move(full_p, dest)

        # Vérifie que chaque Single dans Singles possède les tags TALB/TPE2 + une vraie pochette APIC HD
        for fname in os.listdir(MUSIC_SINGLES_DIR):
            if fname.lower().endswith(".mp3"):
                fpath = os.path.join(MUSIC_SINGLES_DIR, fname)
                stem = fname[:-4]
                if " - " in stem:
                    art_p, tit_p = stem.split(" - ", 1)
                else:
                    art_p, tit_p = "Artiste", stem
                art_p, tit_p = art_p.strip(), tit_p.strip()

                has_apic = False
                if HAS_MUTAGEN:
                    try:
                        t_existing = ID3(fpath)
                        has_apic = len(t_existing.getall("APIC")) > 0
                    except Exception:
                        has_apic = False

                cov_url = None
                if not has_apic:
                    hd = fetch_deezer_hd_info(artist_str=art_p, title_str=tit_p)
                    cov_url = hd.get("cover_xl") or None
                    if hd.get("artist_xl"):
                        ensure_artist_and_album_art(art_p, artist_pic_url=hd["artist_xl"])

                apply_id3_tags(
                    fpath,
                    title=tit_p,
                    artist=art_p,
                    album="⚡ Singles & Sons en vrac",
                    album_artist="Singles",
                    cover_url=cov_url,
                )
        rebuild_singles_playlist()
    except Exception as e:
        write_log(f"Cleanup musique info: {e}")


def search_ytmusic_official_songs(query_str, limit=12):
    """Catalogue officiel de chansons YouTube Music (filter='songs')."""
    results = []
    if not YTM or not query_str:
        return results
    try:
        songs = YTM.search(query_str, filter="songs", limit=limit)
        for s in songs:
            vid_id = s.get("videoId")
            if not vid_id:
                continue
            title = s.get("title") or "Morceau"
            artists_list = [a.get("name", "") for a in (s.get("artists") or []) if a.get("name")]
            artist = ", ".join(artists_list) if artists_list else "Artiste"
            album = (s.get("album") or {}).get("name") or "Single"
            dur = s.get("duration") or ""
            thumbs = s.get("thumbnails") or []
            img = thumbs[-1].get("url", "") if thumbs else ""
            img = re.sub(r"=w\d+-h\d+.*", "=w500-h500-l90-rj", img)
            results.append(
                {
                    "id": vid_id,
                    "type": "ytmusic",
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "subtitle": f"🎵 {artist} • {album}" + (f" ({dur})" if dur else ""),
                    "image": img,
                    "preview": "",
                    "yt_id": vid_id,
                }
            )
    except Exception as e:
        write_log(f"YTMusic songs search err: {e}")
    return results


def search_youtube_all_videos(query_str, limit=14):
    """Recherche sur TOUT YouTube (en privilégiant la musique, les exclusivités, freestyles,
    remixes, lives et sons introuvables ailleurs) via yt-dlp."""
    results = []
    if not query_str:
        return results
    try:
        # 1. On inclut d'abord les vidéos musicales de YouTube Music (filter="videos") + Songs
        seen_ids = set()
        if YTM:
            try:
                vids = YTM.search(query_str, filter="videos", limit=6)
                for v in vids:
                    vid_id = v.get("videoId")
                    if not vid_id or vid_id in seen_ids:
                        continue
                    seen_ids.add(vid_id)
                    title = v.get("title") or "Vidéo YouTube"
                    artists_list = [a.get("name", "") for a in (v.get("artists") or []) if a.get("name")]
                    artist = ", ".join(artists_list) if artists_list else "YouTube"
                    dur = v.get("duration") or ""
                    thumbs = v.get("thumbnails") or []
                    img = thumbs[-1].get("url", "") if thumbs else f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                    results.append(
                        {
                            "id": vid_id,
                            "type": "youtube_all",
                            "title": title,
                            "artist": artist,
                            "subtitle": f"▶️ YouTube • {artist}" + (f" ({dur})" if dur else ""),
                            "image": img,
                            "preview": "",
                            "yt_id": vid_id,
                        }
                    )
            except Exception:
                pass

        # 2. Recherche complète sur tout YouTube via yt-dlp --flat-playlist --dump-json
        ytdlp_bin = os.path.join(BIN_DIR, "yt-dlp.exe")
        r = subprocess.run(
            [
                ytdlp_bin,
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                f"ytsearch{limit}:{query_str}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=12,
            env=get_env(),
        )
        for line in (r.stdout or "").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                vid_id = obj.get("id")
                if not vid_id or vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)
                title = obj.get("title") or "YouTube"
                uploader = obj.get("uploader") or obj.get("channel") or "YouTube"
                dur_s = int(obj.get("duration") or 0)
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
                thumbs = obj.get("thumbnails") or []
                img = (
                    thumbs[-1].get("url")
                    if thumbs
                    else f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                )
                results.append(
                    {
                        "id": vid_id,
                        "type": "youtube_all",
                        "title": title,
                        "artist": uploader,
                        "subtitle": f"▶️ YouTube • {uploader}" + (f" ({dur_str})" if dur_str else ""),
                        "image": img,
                        "preview": "",
                        "yt_id": vid_id,
                    }
                )
                if len(results) >= limit:
                    break
            except Exception:
                pass
    except Exception as e:
        write_log(f"YouTube all search err: {e}")
    return results


def resolve_official_ytmusic_id(artist, title):
    if not YTM:
        return None
    try:
        songs = YTM.search(f"{artist} {title}", filter="songs", limit=2)
        if songs and songs[0].get("videoId"):
            return songs[0]["videoId"]
    except Exception:
        pass
    return None


def load_spotify_sync_data():
    if os.path.exists(SPOTIFY_SYNC_FILE):
        try:
            return json.load(open(SPOTIFY_SYNC_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {
        "account_url": "",
        "account_name": "Non connecté",
        "playlists": [],
        "favorite_artists": ["Damso", "Daft Punk", "The Weeknd", "Gazo", "Tiakola", "Ninho"],
    }


def save_spotify_sync_data(data):
    with open(SPOTIFY_SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_deezer_playlist_or_album(entity_type, entity_id):
    """Récupère une playlist ou un album Deezer complet via l'API publique officielle Deezer."""
    try:
        r = requests.get(f"https://api.deezer.com/{entity_type}/{entity_id}", timeout=8).json()
        if r.get("error"):
            return None
        name = r.get("title") or f"Deezer {entity_type.title()}"
        owner = (
            (r.get("creator") or {}).get("name")
            or (r.get("artist") or {}).get("name")
            or "Deezer"
        )
        cover = (
            r.get("picture_big")
            or r.get("picture_medium")
            or r.get("cover_big")
            or r.get("cover_medium")
            or ""
        )
        tracks_data = (r.get("tracks") or {}).get("data") or []
        tracks = []
        for idx, t in enumerate(tracks_data, 1):
            t_title = t.get("title") or f"Titre {idx}"
            t_art = (t.get("artist") or {}).get("name") or owner
            dur_s = int(t.get("duration") or 0)
            dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
            t_cov = (t.get("album") or {}).get("cover_medium") or cover
            tracks.append(
                {
                    "id": str(t.get("id") or f"dz:{idx}"),
                    "type": "track",
                    "title": t_title,
                    "artist": t_art,
                    "subtitle": f"💜 {t_art}" + (f" ({dur_str})" if dur_str else ""),
                    "image": t_cov,
                    "preview": t.get("preview") or "",
                }
            )
        return {
            "id": f"dz_{entity_type}_{entity_id}",
            "entity_type": f"deezer_{entity_type}",
            "name": name,
            "owner": owner,
            "image": cover,
            "tracks_count": len(tracks),
            "tracks": tracks,
        }
    except Exception as e:
        write_log(f"Deezer entity err ({entity_type}/{entity_id}): {e}")
        return None


def fetch_spotify_embed_entity(entity_type, entity_id):
    try:
        u = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        r = requests.get(
            u,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
            timeout=8,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        sc = soup.find("script", id="__NEXT_DATA__")
        if not sc or not sc.string:
            return None
        d = json.loads(sc.string)
        entity = (
            d.get("props", {})
            .get("pageProps", {})
            .get("state", {})
            .get("data", {})
            .get("entity", {})
        )
        if not entity:
            return None
        name = entity.get("name") or entity.get("title") or f"Playlist {entity_type.title()}"
        owner = entity.get("subtitle") or "Spotify"
        cov_sources = (entity.get("coverArt") or {}).get("sources") or (
            (entity.get("visualIdentity") or {}).get("image") or []
        )
        cover = cov_sources[0].get("url", "") if cov_sources else ""
        tracks = []
        for idx, t in enumerate(entity.get("trackList", []), 1):
            t_title = t.get("title") or f"Titre {idx}"
            t_art = t.get("subtitle") or owner
            dur_ms = int(t.get("duration") or 0)
            dur_s = dur_ms // 1000
            dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
            prev_url = (t.get("audioPreview") or {}).get("url") or ""
            tracks.append(
                {
                    "id": t.get("uri", f"sp:{idx}").split(":")[-1],
                    "type": "spotify_track",
                    "title": t_title,
                    "artist": t_art,
                    "subtitle": f"🎵 {t_art}" + (f" ({dur_str})" if dur_str else ""),
                    "image": cover,
                    "preview": prev_url,
                }
            )
        return {
            "id": entity_id,
            "entity_type": entity_type,
            "name": name,
            "owner": owner,
            "image": cover,
            "tracks_count": len(tracks),
            "tracks": tracks,
        }
    except Exception as e:
        write_log(f"Spotify embed err ({entity_type}/{entity_id}): {e}")
        return None


@app.route("/api/spotify_sync", methods=["POST"])
@app.route("/api/deezer_sync", methods=["POST"])
def api_spotify_sync():
    """Synchronise un compte ou une playlist Deezer (ex: https://www.deezer.com/fr/profile/...,
    https://link.deezer.com/..., https://www.deezer.com/fr/playlist/...) ou Spotify !"""
    raw_input = (request.form.get("url") or "").strip()
    if not raw_input:
        return jsonify({"ok": False, "error": "Entre un lien de compte ou de playlist Deezer (ou Spotify)."})

    # Résolution des liens courts de partage (ex:deezer.page.link ou link.deezer.com)
    if any(short_d in raw_input.lower() for short_d in ["link.deezer.com", "deezer.page.link", "spotify.link"]):
        try:
            r_short = requests.get(
                raw_input,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
                timeout=8,
            )
            raw_input = r_short.url
        except Exception:
            pass

    sync_data = load_spotify_sync_data()
    playlists_added = 0
    artists_counter = {}

    try:
        # --- CAS DEEZER (Profil Utilisateur, Playlist, Album ou Artiste) ---
        m_dz = re.search(
            r"deezer\.com/(?:[a-z]{2}/)?(profile|user|playlist|album|artist)/(\d+)",
            raw_input,
            re.IGNORECASE,
        )
        if m_dz or raw_input.isdigit():
            dz_type = m_dz.group(1).lower() if m_dz else "profile"
            dz_id = m_dz.group(2) if m_dz else raw_input

            if dz_type in ("playlist", "album"):
                ent = fetch_deezer_playlist_or_album(dz_type, dz_id)
                if ent:
                    sync_data["playlists"] = [
                        p for p in sync_data.get("playlists", []) if p.get("id") != ent["id"]
                    ]
                    sync_data["playlists"].insert(0, ent)
                    playlists_added += 1
                    if sync_data.get("account_name") == "Non connecté":
                        sync_data["account_name"] = f"{ent.get('owner', 'Deezer')}"
                    sync_data["account_url"] = raw_input
            else:
                # Compte Utilisateur Deezer (profile / user)
                u_info = requests.get(f"https://api.deezer.com/user/{dz_id}", timeout=8).json()
                profile_name = u_info.get("name") or f"Deezer #{dz_id}"
                profile_pic = u_info.get("picture_medium") or ""
                sync_data["account_url"] = f"https://www.deezer.com/fr/profile/{dz_id}"
                sync_data["account_name"] = f"{profile_name} (Deezer)"

                # 1. Coups de cœur (Loved tracks) de l'utilisateur Deezer
                fav_tr = (
                    requests.get(f"https://api.deezer.com/user/{dz_id}/tracks?limit=50", timeout=8)
                    .json()
                    .get("data", [])
                )
                if fav_tr:
                    loved_tracks = []
                    for idx, t in enumerate(fav_tr, 1):
                        t_art = (t.get("artist") or {}).get("name") or "Artiste"
                        dur_s = int(t.get("duration") or 0)
                        dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
                        loved_tracks.append(
                            {
                                "id": str(t.get("id")),
                                "type": "track",
                                "title": t.get("title") or f"Titre {idx}",
                                "artist": t_art,
                                "subtitle": f"💜 {t_art}" + (f" ({dur_str})" if dur_str else ""),
                                "image": (t.get("album") or {}).get("cover_medium") or profile_pic,
                                "preview": t.get("preview") or "",
                            }
                        )
                    loved_id = f"dz_loved_{dz_id}"
                    sync_data["playlists"] = [
                        p for p in sync_data.get("playlists", []) if p.get("id") != loved_id
                    ]
                    sync_data["playlists"].insert(
                        0,
                        {
                            "id": loved_id,
                            "entity_type": "deezer_playlist",
                            "name": f"💜 Coups de cœur de {profile_name}",
                            "owner": profile_name,
                            "image": profile_pic,
                            "tracks_count": len(loved_tracks),
                            "tracks": loved_tracks,
                        },
                    )
                    playlists_added += 1

                # 2. Toutes les playlists publiques du compte Deezer
                u_pls = (
                    requests.get(
                        f"https://api.deezer.com/user/{dz_id}/playlists?limit=15", timeout=8
                    )
                    .json()
                    .get("data", [])
                )
                for pl_meta in u_pls[:10]:
                    pid = str(pl_meta.get("id") or "")
                    if not pid:
                        continue
                    ent = fetch_deezer_playlist_or_album("playlist", pid)
                    if ent and ent.get("tracks"):
                        sync_data["playlists"] = [
                            p for p in sync_data.get("playlists", []) if p.get("id") != ent["id"]
                        ]
                        sync_data["playlists"].append(ent)
                        playlists_added += 1

                # 3. Artistes favoris du compte Deezer
                u_arts = (
                    requests.get(
                        f"https://api.deezer.com/user/{dz_id}/artists?limit=12", timeout=8
                    )
                    .json()
                    .get("data", [])
                )
                for a_obj in u_arts:
                    if a_obj.get("name"):
                        artists_counter[a_obj["name"]] = artists_counter.get(a_obj["name"], 0) + 5

        # --- CAS SPOTIFY (Playlist, Album ou Profil Spotify en compatibilité) ---
        elif "spotify.com" in raw_input.lower():
            m_direct = re.search(
                r"open\.spotify\.com/(?:intl-[a-z]+/)?(playlist|album|artist|track)/([a-zA-Z0-9]+)",
                raw_input,
            )
            if m_direct:
                etype, eid = m_direct.group(1), m_direct.group(2)
                ent = fetch_spotify_embed_entity(etype, eid)
                if ent:
                    sync_data["playlists"] = [
                        p for p in sync_data.get("playlists", []) if p.get("id") != eid
                    ]
                    sync_data["playlists"].insert(0, ent)
                    playlists_added += 1
            else:
                m_user = re.search(
                    r"open\.spotify\.com/(?:intl-[a-z]+/)?user/([^/?#&]+)", raw_input
                )
                user_id = m_user.group(1) if m_user else re.sub(r"[^a-zA-Z0-9._-]", "", raw_input)
                user_url = f"https://open.spotify.com/user/{user_id}"
                r_u = requests.get(
                    user_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                    timeout=8,
                )
                soup_u = BeautifulSoup(r_u.text, "html.parser")
                og_title = soup_u.find("meta", property="og:title")
                profile_name = (
                    og_title["content"].replace(" on Spotify", "").replace(" sur Spotify", "").strip()
                    if og_title and og_title.get("content")
                    else user_id
                )
                sync_data["account_url"] = user_url
                sync_data["account_name"] = profile_name

                pids = list(dict.fromkeys(re.findall(r"/playlist/([a-zA-Z0-9]{22})", r_u.text)))
                for pid in pids[:8]:
                    ent = fetch_spotify_embed_entity("playlist", pid)
                    if ent and ent.get("tracks"):
                        sync_data["playlists"] = [
                            p for p in sync_data.get("playlists", []) if p.get("id") != pid
                        ]
                        sync_data["playlists"].append(ent)
                        playlists_added += 1
        else:
            return jsonify(
                {
                    "ok": False,
                    "error": "Colle un lien Deezer valide (ex: https://www.deezer.com/fr/profile/... ou /playlist/...).",
                }
            )

        # Recalcul des artistes favoris à partir des playlists synchronisées
        for pl in sync_data.get("playlists", []):
            for tr in pl.get("tracks", []):
                main_art = (tr.get("artist") or "").split(",")[0].strip()
                if main_art and main_art.lower() not in ("spotify", "deezer"):
                    artists_counter[main_art] = artists_counter.get(main_art, 0) + 1

        if artists_counter:
            sorted_arts = sorted(
                artists_counter.keys(), key=lambda k: artists_counter[k], reverse=True
            )
            sync_data["favorite_artists"] = sorted_arts[:10]

        save_spotify_sync_data(sync_data)
        SPOTIFY_HOME_CACHE["ts"] = 0
        write_log(
            f"💜 Compte musical synchronisé : {sync_data.get('account_name')} ({len(sync_data.get('playlists', []))} playlists)"
        )
        return jsonify(
            {
                "ok": True,
                "playlists_added": playlists_added,
                "account_name": sync_data.get("account_name"),
                "total_playlists": len(sync_data.get("playlists", [])),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


SPOTIFY_HOME_CACHE = {"ts": 0, "data": None}


@app.route("/api/spotify_home")
@app.route("/api/deezer_home")
def api_spotify_home():
    force = request.args.get("refresh") == "1"
    sync_data = load_spotify_sync_data()

    recent_server = []
    for root, _, fnames in os.walk(MUSIC_DIR):
        for f in sorted(fnames):
            if f.lower().endswith(".mp3"):
                fp = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(fp)
                except Exception:
                    mtime = 0
                stem = f[:-4]
                if " - " in stem:
                    p1, p2 = stem.split(" - ", 1)
                    if p1.isdigit():
                        art_s = os.path.basename(root).split(" - ")[0]
                        tit_s = p2
                    else:
                        art_s, tit_s = p1, p2
                else:
                    art_s, tit_s = "Serveur Local", stem
                recent_server.append(
                    {
                        "mtime": mtime,
                        "title": tit_s,
                        "artist": art_s,
                        "subtitle": f"💾 Sur ton serveur • {art_s}",
                        "path": fp,
                        "stream_url": f"/stream?path={quote_plus(fp)}",
                    }
                )
    recent_server.sort(key=lambda x: x["mtime"], reverse=True)
    recent_server = recent_server[:12]

    now = time.time()
    if not force and SPOTIFY_HOME_CACHE["data"] and (now - SPOTIFY_HOME_CACHE["ts"] < 600):
        cached = SPOTIFY_HOME_CACHE["data"]
        return jsonify(
            {
                "account_name": sync_data.get("account_name", "Non connecté"),
                "account_url": sync_data.get("account_url", ""),
                "favorite_artists": sync_data.get("favorite_artists", []),
                "playlists": sync_data.get("playlists", []),
                "recommendations": cached.get("recommendations", []),
                "top_albums": cached.get("top_albums", []),
                "recent_server": recent_server,
            }
        )

    fav_artists = sync_data.get("favorite_artists") or [
        "Damso",
        "Daft Punk",
        "The Weeknd",
        "Gazo",
        "Tiakola",
        "Ninho",
    ]
    recommendations = []
    top_albums = []

    for art in fav_artists[:6]:
        try:
            r_tr = requests.get(
                "https://api.deezer.com/search/track",
                params={"q": art, "limit": 2},
                timeout=4,
            ).json()
            for item in r_tr.get("data", []):
                dur_s = int(item.get("duration") or 0)
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
                recommendations.append(
                    {
                        "id": item["id"],
                        "type": "track",
                        "title": item["title"],
                        "artist": item.get("artist", {}).get("name", art),
                        "subtitle": f"🎧 {item.get('artist', {}).get('name', art)} • {(item.get('album') or {}).get('title', '')} ({dur_str})",
                        "image": (item.get("album") or {}).get("cover_medium", ""),
                        "preview": item.get("preview", ""),
                    }
                )
            r_al = requests.get(
                "https://api.deezer.com/search/album",
                params={"q": art, "limit": 1},
                timeout=4,
            ).json()
            for alb in r_al.get("data", []):
                top_albums.append(
                    {
                        "id": alb["id"],
                        "type": "album",
                        "title": alb["title"],
                        "artist": (alb.get("artist") or {}).get("name", art),
                        "subtitle": f"💿 Album • {(alb.get('artist') or {}).get('name', art)}",
                        "image": alb.get("cover_medium", ""),
                        "preview": "",
                    }
                )
        except Exception:
            pass

    SPOTIFY_HOME_CACHE["ts"] = now
    SPOTIFY_HOME_CACHE["data"] = {
        "recommendations": recommendations[:12],
        "top_albums": top_albums[:8],
    }

    return jsonify(
        {
            "account_name": sync_data.get("account_name", "Non connecté"),
            "account_url": sync_data.get("account_url", ""),
            "favorite_artists": fav_artists,
            "playlists": sync_data.get("playlists", []),
            "recommendations": recommendations[:12],
            "top_albums": top_albums[:8],
            "recent_server": recent_server,
        }
    )


def spotify_playlist_download_worker(playlist_id):
    sync_data = load_spotify_sync_data()
    target_pl = next(
        (p for p in sync_data.get("playlists", []) if p.get("id") == playlist_id), None
    )
    if not target_pl:
        return
    STATUS["active"], STATUS["stop"], STATUS["error"] = True, False, ""
    pl_name = clean_name(target_pl.get("name", "Playlist Deezer"))
    owner_name = clean_name(target_pl.get("owner") or "Deezer")
    STATUS["title"] = f"💜 Playlist : {pl_name}"
    target_folder = os.path.join(MUSIC_DIR, owner_name, pl_name)
    os.makedirs(target_folder, exist_ok=True)
    if target_pl.get("image"):
        download_image_file(target_pl["image"], os.path.join(target_folder, "cover.jpg"))
    ytdlp_bin = os.path.join(BIN_DIR, "yt-dlp.exe")
    env = get_env()
    tracks = target_pl.get("tracks", [])
    total_t = max(len(tracks), 1)
    try:
        for idx, tr in enumerate(tracks, 1):
            if STATUS["stop"]:
                break
            art_raw = tr.get("artist") or "Artiste"
            t_raw = tr.get("title") or f"Piste {idx}"
            fname = f"{idx:02d} - {clean_name(t_raw)}.mp3"
            out_f = os.path.join(target_folder, fname)
            if os.path.exists(out_f) and os.path.getsize(out_f) > 500000:
                continue
            STATUS["step"] = f"Piste {idx}/{total_t} : {art_raw} - {t_raw}"
            STATUS["percent"] = round(((idx - 1) / total_t) * 100, 1)
            vid_id = resolve_official_ytmusic_id(art_raw, t_raw)
            dl_target = (
                f"https://music.youtube.com/watch?v={vid_id}"
                if vid_id
                else f"ytsearch1:{art_raw} - {t_raw} Audio Topic"
            )
            subprocess.run(
                [
                    ytdlp_bin,
                    "-x",
                    "--audio-format",
                    "mp3",
                    "--audio-quality",
                    "0",
                    "--no-playlist",
                    "--ignore-errors",
                    "-o",
                    out_f[:-4] + ".%(ext)s",
                    dl_target,
                ],
                env=env,
            )
            if os.path.exists(out_f):
                hd = fetch_deezer_hd_info(
                    artist_str=art_raw,
                    title_str=t_raw,
                    track_id=tr.get("id"),
                )
                cov_xl = hd.get("cover_xl") or tr.get("image") or target_pl.get("image")
                ensure_artist_and_album_art(art_raw, artist_pic_url=hd.get("artist_xl", ""))
                apply_id3_tags(
                    out_f,
                    title=t_raw,
                    artist=art_raw,
                    album=pl_name,
                    album_artist=owner_name,
                    track_num=idx,
                    cover_url=cov_xl,
                )
        trigger_navidrome_scan()
        STATUS["percent"] = 100
        STATUS["step"] = f"✅ Playlist '{pl_name}' téléchargée dans Navidrome !"
    except Exception as e:
        STATUS["error"] = str(e)
    finally:
        STATUS["active"] = False


@app.route("/api/spotify_download_playlist", methods=["POST"])
def api_spotify_download_playlist():
    pid = request.form.get("id", "").strip()
    enqueue_download(f"Playlist {pid}", spotify_playlist_download_worker, pid)
    return jsonify({"ok": True})


def music_download_worker(m_type, item_id, label, artist_hint="", image_hint=""):
    global CURRENT_PROC
    STATUS["active"], STATUS["stop"], STATUS["error"] = True, False, ""
    STATUS["title"] = f"🎵 {label}"
    STATUS["step"] = "⏳ Préparation du téléchargement musical..."
    STATUS["percent"] = 5
    STATUS["speed"] = "-"
    env = get_env()
    ytdlp_bin = os.path.join(BIN_DIR, "yt-dlp.exe")
    try:
        tracks_to_dl = []
        if m_type == "album":
            alb = requests.get(
                f"https://api.deezer.com/album/{item_id}", timeout=10
            ).json()
            art_obj = alb.get("artist") or {}
            art_raw = art_obj.get("name") or artist_hint or "Artiste"
            alb_raw = alb.get("title") or label
            art_name = clean_name(art_raw)
            alb_title = clean_name(alb_raw)
            cover_url = (
                alb.get("cover_xl")
                or alb.get("cover_big")
                or alb.get("cover_medium")
                or image_hint
                or ""
            )
            artist_pic_url = (
                art_obj.get("picture_xl")
                or art_obj.get("picture_big")
                or art_obj.get("picture_medium")
                or ""
            )
            if not artist_pic_url and art_obj.get("id"):
                hd_art = fetch_deezer_hd_info(artist_str=art_raw, artist_id=art_obj.get("id"))
                artist_pic_url = hd_art.get("artist_xl") or ""

            # Structure : C:\Serveur\Medias\Musique\<Nom Artiste>\<Nom Album>\<01 - Titre>.mp3
            artist_folder = os.path.join(MUSIC_DIR, art_name)
            target_folder = os.path.join(artist_folder, alb_title)
            os.makedirs(target_folder, exist_ok=True)
            ensure_artist_and_album_art(
                art_raw,
                album_dir=target_folder,
                cover_url=cover_url,
                artist_pic_url=artist_pic_url,
            )

            for idx, t in enumerate(alb.get("tracks", {}).get("data", []), 1):
                t_raw = t.get("title", f"Piste {idx}")
                t_art = (t.get("artist") or {}).get("name") or art_raw
                t_title = clean_name(t_raw)
                fname = f"{idx:02d} - {t_title}.mp3"
                tracks_to_dl.append(
                    {
                        "vid_id": resolve_official_ytmusic_id(t_art, t_raw),
                        "query": f"{t_art} - {t_raw}",
                        "out_path": os.path.join(target_folder, fname),
                        "title": t_raw,
                        "artist": t_art,
                        "album": alb_raw,
                        "album_artist": art_raw,
                        "track_num": idx,
                        "cover_url": cover_url,
                    }
                )
        elif m_type == "artist":
            art = requests.get(
                f"https://api.deezer.com/artist/{item_id}", timeout=10
            ).json()
            art_raw = art.get("name") or label
            art_name = clean_name(art_raw)
            alb_label = "Top Titres"
            artist_pic_url = (
                art.get("picture_xl")
                or art.get("picture_big")
                or art.get("picture_medium")
                or ""
            )
            # Structure : C:\Serveur\Medias\Musique\<Nom Artiste>\Top Titres\<01 - Titre>.mp3
            artist_folder = os.path.join(MUSIC_DIR, art_name)
            target_folder = os.path.join(artist_folder, "Top Titres")
            os.makedirs(target_folder, exist_ok=True)
            ensure_artist_and_album_art(
                art_raw,
                album_dir=target_folder,
                cover_url=artist_pic_url,
                artist_pic_url=artist_pic_url,
            )

            top = (
                requests.get(
                    f"https://api.deezer.com/artist/{item_id}/top?limit=10",
                    timeout=10,
                )
                .json()
                .get("data", [])
            )
            for idx, t in enumerate(top, 1):
                t_raw = t.get("title", f"Top {idx}")
                t_title = clean_name(t_raw)
                t_cov = (
                    (t.get("album") or {}).get("cover_xl")
                    or (t.get("album") or {}).get("cover_big")
                    or artist_pic_url
                )
                fname = f"{idx:02d} - {t_title}.mp3"
                tracks_to_dl.append(
                    {
                        "vid_id": resolve_official_ytmusic_id(art_raw, t_raw),
                        "query": f"{art_raw} - {t_raw}",
                        "out_path": os.path.join(target_folder, fname),
                        "title": t_raw,
                        "artist": art_raw,
                        "album": alb_label,
                        "album_artist": art_raw,
                        "track_num": idx,
                        "cover_url": t_cov,
                    }
                )
        else:
            # Titre seul (Single) : C:\Serveur\Medias\Musique\Singles\<Artiste> - <Titre>.mp3
            # avec TALB = "⚡ Singles & Sons en vrac" et TPE2 = "Singles" + cover_xl 1000x1000 APIC
            art_raw = (artist_hint or "Artiste").strip()
            t_raw = (label or "Morceau").strip()
            hd = fetch_deezer_hd_info(
                artist_str=art_raw,
                title_str=t_raw,
                track_id=item_id if m_type == "track" else None,
            )
            if hd.get("artist_name") and art_raw.lower() in ("artiste", "youtube", ""):
                art_raw = hd["artist_name"]
            cover_url = hd.get("cover_xl") or image_hint or ""
            if hd.get("artist_xl"):
                ensure_artist_and_album_art(art_raw, artist_pic_url=hd["artist_xl"])

            art_name = clean_name(art_raw)
            t_title = clean_name(t_raw)
            os.makedirs(MUSIC_SINGLES_DIR, exist_ok=True)
            fname = f"{art_name} - {t_title}.mp3"
            vid_id = (
                item_id
                if (m_type in ("ytmusic", "youtube_all") and len(str(item_id)) == 11)
                else resolve_official_ytmusic_id(art_raw, t_raw)
            )
            tracks_to_dl.append(
                {
                    "vid_id": vid_id,
                    "is_raw_yt": m_type == "youtube_all",
                    "query": f"{art_raw} - {t_raw}",
                    "out_path": os.path.join(MUSIC_SINGLES_DIR, fname),
                    "title": t_raw,
                    "artist": art_raw,
                    "album": "⚡ Singles & Sons en vrac",
                    "album_artist": "Singles",
                    "track_num": None,
                    "cover_url": cover_url,
                }
            )

        total_t = max(len(tracks_to_dl), 1)
        for i, item in enumerate(tracks_to_dl, 1):
            if STATUS["stop"]:
                break
            out_f = item["out_path"]
            STATUS["step"] = f"Piste {i}/{total_t} : {item['artist']} - {item['title']}"
            STATUS["percent"] = round(((i - 1) / total_t) * 100, 1)
            if item.get("is_raw_yt") and item.get("vid_id"):
                target_arg = f"https://www.youtube.com/watch?v={item['vid_id']}"
            elif item.get("vid_id"):
                target_arg = f"https://music.youtube.com/watch?v={item['vid_id']}"
            else:
                target_arg = f"ytsearch1:{item['query']} Audio"
            CURRENT_PROC = subprocess.Popen(
                [
                    ytdlp_bin,
                    "-x",
                    "--audio-format",
                    "mp3",
                    "--audio-quality",
                    "0",
                    "--no-playlist",
                    "--ignore-errors",
                    "--newline",
                    "-o",
                    out_f[:-4] + ".%(ext)s",
                    target_arg,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                env=env,
            )
            for line in CURRENT_PROC.stdout:
                if STATUS["stop"]:
                    try:
                        CURRENT_PROC.kill()
                    except Exception:
                        pass
                    break
                line_s = line.strip()
                if "[download]" in line_s and "%" in line_s:
                    m_pct = re.search(r"(\d+(?:\.\d+)?)%", line_s)
                    m_spd = re.search(r"at\s+([0-9.]+[a-zA-Z/]+)", line_s)
                    if m_pct:
                        track_pct = float(m_pct.group(1))
                        STATUS["percent"] = round((((i - 1) + (track_pct / 100.0)) / total_t) * 100, 1)
                    if m_spd:
                        STATUS["speed"] = m_spd.group(1)
            CURRENT_PROC.wait()
            if STATUS["stop"]:
                break
            if os.path.exists(out_f):
                apply_id3_tags(
                    out_f,
                    title=item["title"],
                    artist=item["artist"],
                    album=item["album"],
                    album_artist=item["album_artist"],
                    track_num=item["track_num"],
                    cover_url=item["cover_url"],
                )
                write_log(
                    f"🎵 Son ajouté : {os.path.basename(out_f)} -> Album='{item['album']}'"
                )

        if STATUS["stop"]:
            STATUS["title"] = "Aucun téléchargement actif"
            STATUS["step"] = "⏹️ Téléchargement arrêté par l'utilisateur."
            STATUS["percent"] = 0
            STATUS["speed"] = "-"
        else:
            rebuild_singles_playlist()
            trigger_navidrome_scan()
            STATUS["percent"] = 100
            STATUS["speed"] = "-"
            STATUS["step"] = f"✅ {label} téléchargé et ajouté à la bibliothèque musicale !"
    except Exception as e:
        STATUS["error"] = str(e)
        write_log(f"❌ Erreur téléchargement musique: {e}")
    finally:
        STATUS["active"] = False


# ==============================================================================
# LECTEUR WEB MINI-SPOTIFY / DEEZER : BIBLIOTHÈQUE LOCALE & POCHETTES HD
# ==============================================================================
@app.route("/api/music_cover")
def api_music_cover():
    """Sert la pochette HD embarquée (APIC) d'un MP3 ou les fichiers cover.jpg / artist.jpg."""
    raw_path = request.args.get("path", "")
    kind = request.args.get("type", "cover")
    if not raw_path:
        return "Missing path", 400
    abs_p = os.path.abspath(raw_path)
    music_root = os.path.abspath(MUSIC_DIR)
    if not abs_p.startswith(music_root) or not os.path.exists(abs_p):
        return "Not found", 404

    headers = {"Cache-Control": "public, max-age=3600"}

    # Cas 1 : Fichier image direct (cover.jpg ou artist.jpg)
    if os.path.isfile(abs_p) and abs_p.lower().endswith((".jpg", ".jpeg", ".png")):
        return send_file(abs_p, mimetype="image/jpeg", max_age=3600)

    # Cas 2 : Fichier MP3 -> Extraction du tag ID3 APIC en priorité
    if os.path.isfile(abs_p) and abs_p.lower().endswith(".mp3"):
        if HAS_MUTAGEN:
            try:
                tags = ID3(abs_p)
                apics = tags.getall("APIC")
                if apics and apics[0].data:
                    return Response(
                        apics[0].data,
                        mimetype=apics[0].mime or "image/jpeg",
                        headers=headers,
                    )
            except Exception:
                pass
        # Fallback cover.jpg du dossier ou artist.jpg du dossier parent
        parent_d = os.path.dirname(abs_p)
        for cand in [
            os.path.join(parent_d, "cover.jpg"),
            os.path.join(os.path.dirname(parent_d), "artist.jpg"),
        ]:
            if os.path.exists(cand):
                return send_file(cand, mimetype="image/jpeg", max_age=3600)

    # Cas 3 : Dossier d'Artiste ou d'Album
    if os.path.isdir(abs_p):
        candidates = (
            [os.path.join(abs_p, "artist.jpg"), os.path.join(abs_p, "cover.jpg")]
            if kind == "artist"
            else [os.path.join(abs_p, "cover.jpg"), os.path.join(abs_p, "artist.jpg")]
        )
        for c in candidates:
            if os.path.exists(c):
                return send_file(c, mimetype="image/jpeg", max_age=3600)
        # Cherche dans les sous-dossiers un cover.jpg ou un MP3 avec APIC
        for r, _, files in os.walk(abs_p):
            for fn in sorted(files):
                if fn.lower() in ("cover.jpg", "artist.jpg"):
                    return send_file(os.path.join(r, fn), mimetype="image/jpeg", max_age=3600)
            for fn in sorted(files):
                if fn.lower().endswith(".mp3") and HAS_MUTAGEN:
                    try:
                        tags = ID3(os.path.join(r, fn))
                        apics = tags.getall("APIC")
                        if apics and apics[0].data:
                            return Response(
                                apics[0].data,
                                mimetype=apics[0].mime or "image/jpeg",
                                headers=headers,
                            )
                    except Exception:
                        pass

    return redirect("https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=300")


@app.route("/api/music_offline_stream")
def api_music_offline_stream():
    """MISSION 1 : Transcode et compresse un fichier MP3 en AAC (.m4a) 96 kbps (ou 128 kbps)
    via ffmpeg pour le stockage Hors-Ligne ultra-léger sur iPhone (~2 Mo au lieu de ~9 Mo)."""
    raw_path = request.args.get("path", "")
    quality = (request.args.get("quality") or "eco").lower().strip()
    if not raw_path:
        return "Missing path", 400
    abs_p = os.path.abspath(raw_path)
    music_root = os.path.abspath(MUSIC_DIR)
    if not abs_p.startswith(music_root) or not os.path.isfile(abs_p):
        return "Not found", 404

    bitrate = "128k" if quality == "normal" else "96k"
    os.makedirs(OFFLINE_CACHE_DIR, exist_ok=True)
    mtime_i = int(os.path.getmtime(abs_p))
    hkey = hashlib.md5(f"{abs_p}|{mtime_i}|{bitrate}".encode("utf-8")).hexdigest()[:16]
    out_m4a = os.path.join(OFFLINE_CACHE_DIR, f"offline_{hkey}_{bitrate}.m4a")

    if not os.path.exists(out_m4a) or os.path.getsize(out_m4a) < 8192:
        tmp_m4a = out_m4a + f".{os.getpid()}_{int(time.time()*1000)}.tmp.m4a"
        ffmpeg_bin = os.path.join(BIN_DIR, "ffmpeg.exe")
        if not os.path.exists(ffmpeg_bin):
            ffmpeg_bin = "ffmpeg"
        try:
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    abs_p,
                    "-vn",
                    "-c:a",
                    "aac",
                    "-b:a",
                    bitrate,
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-movflags",
                    "+faststart",
                    tmp_m4a,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90,
                env=get_env(),
            )
            if os.path.exists(tmp_m4a) and os.path.getsize(tmp_m4a) > 4096:
                os.replace(tmp_m4a, out_m4a)
            elif os.path.exists(tmp_m4a):
                os.remove(tmp_m4a)
        except Exception as e:
            write_log(f"Offline ffmpeg transcode err: {e}")
            if os.path.exists(tmp_m4a):
                try:
                    os.remove(tmp_m4a)
                except Exception:
                    pass

    if os.path.exists(out_m4a) and os.path.getsize(out_m4a) > 4096:
        sz_mb = round(os.path.getsize(out_m4a) / 1048576, 2)
        resp = send_file(out_m4a, mimetype="audio/mp4", conditional=True, max_age=86400 * 30)
        resp.headers["X-Offline-Size-MB"] = str(sz_mb)
        resp.headers["X-Offline-Format"] = f"aac-{bitrate}"
        resp.headers["Access-Control-Expose-Headers"] = "X-Offline-Size-MB, X-Offline-Format"
        return resp

    # Fallback sécurisé sur le MP3 original si ffmpeg indisponible
    sz_orig = round(os.path.getsize(abs_p) / 1048576, 2)
    resp = send_file(abs_p, mimetype="audio/mpeg", conditional=True)
    resp.headers["X-Offline-Size-MB"] = str(sz_orig)
    resp.headers["X-Offline-Format"] = "mp3-fallback"
    return resp


@app.route("/api/music_offline_cover")
def api_music_offline_cover():
    """Compresse la pochette associée en JPEG léger 300x300 (~20 Ko) pour le stockage Hors-Ligne iPhone."""
    raw_path = request.args.get("path", "")
    if not raw_path:
        return "Missing path", 400
    abs_p = os.path.abspath(raw_path)
    music_root = os.path.abspath(MUSIC_DIR)
    if not abs_p.startswith(music_root) or not os.path.exists(abs_p):
        return "Not found", 404

    os.makedirs(OFFLINE_CACHE_DIR, exist_ok=True)
    mtime_i = int(os.path.getmtime(abs_p))
    hkey = hashlib.md5(f"cov300|{abs_p}|{mtime_i}".encode("utf-8")).hexdigest()[:16]
    out_jpg = os.path.join(OFFLINE_CACHE_DIR, f"cov_{hkey}_300.jpg")

    if not os.path.exists(out_jpg) or os.path.getsize(out_jpg) < 512:
        src_img = None
        parent_d = abs_p if os.path.isdir(abs_p) else os.path.dirname(abs_p)
        for cand in [
            os.path.join(parent_d, "cover.jpg"),
            os.path.join(parent_d, "artist.jpg"),
            os.path.join(os.path.dirname(parent_d), "artist.jpg"),
        ]:
            if os.path.exists(cand):
                src_img = cand
                break
        if not src_img and os.path.isfile(abs_p):
            src_img = abs_p

        if src_img:
            tmp_jpg = out_jpg + f".{os.getpid()}.tmp.jpg"
            ffmpeg_bin = os.path.join(BIN_DIR, "ffmpeg.exe")
            if not os.path.exists(ffmpeg_bin):
                ffmpeg_bin = "ffmpeg"
            try:
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-i",
                        src_img,
                        "-an",
                        "-vframes",
                        "1",
                        "-vf",
                        "scale=300:300:force_original_aspect_ratio=increase,crop=300:300",
                        "-q:v",
                        "6",
                        tmp_jpg,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    env=get_env(),
                )
                if os.path.exists(tmp_jpg) and os.path.getsize(tmp_jpg) > 512:
                    os.replace(tmp_jpg, out_jpg)
                elif os.path.exists(tmp_jpg):
                    os.remove(tmp_jpg)
            except Exception:
                if os.path.exists(tmp_jpg):
                    try:
                        os.remove(tmp_jpg)
                    except Exception:
                        pass

    if os.path.exists(out_jpg) and os.path.getsize(out_jpg) > 512:
        return send_file(out_jpg, mimetype="image/jpeg", max_age=86400 * 30)

    return api_music_cover()


@app.route("/api/music_library")
def api_music_library():
    """Retourne toute la bibliothèque musicale locale (Tous mes Sons, Mes Albums, Mes Artistes)
    avec leurs tags ID3, durées et URLs de pochettes HD pour le lecteur Mini-Spotify intégré."""
    tracks = []
    albums_map = {}
    artists_map = {}

    if os.path.exists(MUSIC_DIR):
        for root, _, files in os.walk(MUSIC_DIR):
            if ".offline_cache" in root:
                continue
            for fn in sorted(files):
                if not fn.lower().endswith(".mp3") or fn.endswith(".part"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    st = os.stat(fp)
                    sz_mb = round(st.st_size / 1048576, 2)
                    mtime = st.st_mtime
                except Exception:
                    continue

                stem = fn[:-4]
                default_title = re.sub(r"^\d+\s*-\s*", "", stem).strip()
                default_artist = "Artiste"
                if " - " in default_title:
                    p_a, p_t = default_title.split(" - ", 1)
                    default_artist, default_title = p_a.strip(), p_t.strip()

                title = default_title
                artist = default_artist
                album = os.path.basename(root)
                album_artist = artist
                track_num = 0
                dur_s = 0

                if HAS_MUTAGEN:
                    try:
                        mp3_obj = MP3(fp)
                        if mp3_obj.info and mp3_obj.info.length:
                            dur_s = int(round(mp3_obj.info.length))
                        tags = mp3_obj.tags
                        if tags:
                            if tags.get("TIT2"):
                                title = str(tags["TIT2"].text[0]).strip() or title
                            if tags.get("TPE1"):
                                artist = str(tags["TPE1"].text[0]).strip() or artist
                            if tags.get("TALB"):
                                album = str(tags["TALB"].text[0]).strip() or album
                            if tags.get("TPE2"):
                                album_artist = str(tags["TPE2"].text[0]).strip() or artist
                            if tags.get("TRCK"):
                                tr_str = str(tags["TRCK"].text[0]).split("/")[0].strip()
                                if tr_str.isdigit():
                                    track_num = int(tr_str)
                    except Exception:
                        pass

                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
                cov_url = f"/api/music_cover?path={quote(fp)}&v={int(mtime)}"
                off_cov_url = f"/api/music_offline_cover?path={quote(fp)}&v={int(mtime)}"
                stream_u = f"/stream?path={quote(fp)}"
                off_stream_u = f"/api/music_offline_stream?path={quote(fp)}&quality=eco"

                t_item = {
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "album_artist": album_artist,
                    "track_num": track_num,
                    "duration": dur_s,
                    "duration_str": dur_str,
                    "size_mb": sz_mb,
                    "mtime": mtime,
                    "path": fp,
                    "stream_url": stream_u,
                    "cover_url": cov_url,
                    "offline_stream_url": off_stream_u,
                    "offline_cover_url": off_cov_url,
                }
                tracks.append(t_item)

                # Groupement par Album
                alb_key = f"{album_artist}|||{album}"
                if alb_key not in albums_map:
                    alb_cov = cov_url
                    local_cov = os.path.join(root, "cover.jpg")
                    if os.path.exists(local_cov):
                        alb_cov = f"/api/music_cover?path={quote(local_cov)}&v={int(os.path.getmtime(local_cov))}"
                    albums_map[alb_key] = {
                        "id": alb_key,
                        "album": album,
                        "artist": artist if album_artist == "Singles" else album_artist,
                        "folder": root,
                        "cover_url": alb_cov,
                        "tracks": [],
                    }
                albums_map[alb_key]["tracks"].append(t_item)

                # Groupement par Artiste principal
                primary_art = artist.split(",")[0].split(" feat")[0].split(" ft")[0].strip() or artist
                art_key = primary_art.lower()
                if art_key not in artists_map:
                    art_dir = os.path.join(MUSIC_DIR, clean_name(primary_art))
                    art_jpg = os.path.join(art_dir, "artist.jpg")
                    if os.path.exists(art_jpg):
                        photo_u = f"/api/music_cover?path={quote(art_jpg)}&type=artist&v={int(os.path.getmtime(art_jpg))}"
                    elif os.path.isdir(art_dir):
                        photo_u = f"/api/music_cover?path={quote(art_dir)}&type=artist"
                    else:
                        photo_u = cov_url
                    artists_map[art_key] = {
                        "artist": primary_art,
                        "photo_url": photo_u,
                        "albums_set": set(),
                        "tracks": [],
                    }
                artists_map[art_key]["albums_set"].add(album)
                artists_map[art_key]["tracks"].append(t_item)

    albums_list = []
    for alb in albums_map.values():
        alb["tracks"].sort(key=lambda x: (x["track_num"] if x["track_num"] > 0 else 999, x["title"].lower()))
        alb["tracks_count"] = len(alb["tracks"])
        albums_list.append(alb)
    albums_list.sort(key=lambda x: (0 if "Singles" not in x["album"] else 1, x["artist"].lower(), x["album"].lower()))

    artists_list = []
    for ar in artists_map.values():
        ar["tracks"].sort(key=lambda x: (x["album"].lower(), x["track_num"] if x["track_num"] > 0 else 999, x["title"].lower()))
        artists_list.append(
            {
                "artist": ar["artist"],
                "photo_url": ar["photo_url"],
                "albums_count": len(ar["albums_set"]),
                "tracks_count": len(ar["tracks"]),
                "tracks": ar["tracks"],
            }
        )
    artists_list.sort(key=lambda x: (-x["tracks_count"], x["artist"].lower()))

    tracks_sorted = sorted(tracks, key=lambda x: (-x["mtime"], x["artist"].lower(), x["title"].lower()))

    return jsonify(
        {
            "tracks": tracks_sorted,
            "albums": albums_list,
            "artists": artists_list,
            "counts": {
                "tracks": len(tracks_sorted),
                "albums": len(albums_list),
                "artists": len(artists_list),
            },
        }
    )


# ==============================================================================
# ROUTES FLASK API & APPLICATION AUTONOME ILIANTIFY + TAILSCALE VPN
# ==============================================================================
def get_tailscale_status():
    """Détecte l'état du service Tailscale et l'adresse IP VPN fixe 100.x.y.z du serveur Dell."""
    info = {
        "installed": os.path.exists(TAILSCALE_EXE),
        "state": "NotInstalled",
        "connected": False,
        "ip": "",
        "auth_url": "",
        "hub_url": "",
        "iliantify_url": "",
        "jf_url": "",
    }
    if not info["installed"]:
        return info
    try:
        r = subprocess.run(
            [TAILSCALE_EXE, "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=4,
        )
        if r.stdout:
            data = json.loads(r.stdout)
            b_state = data.get("BackendState") or "Unknown"
            info["state"] = b_state
            info["auth_url"] = data.get("AuthURL") or ""
            ips = (data.get("Self") or {}).get("TailscaleIPs") or []
            ts_ipv4 = next((ip for ip in ips if "." in ip), ips[0] if ips else "")
            if ts_ipv4:
                info["ip"] = ts_ipv4
                info["connected"] = b_state == "Running"
                info["hub_url"] = f"http://{ts_ipv4}:5000"
                info["iliantify_url"] = f"http://{ts_ipv4}:5000/iliantify"
                info["jf_url"] = f"http://{ts_ipv4}:8096"
    except Exception:
        pass
    return info


@app.route("/api/tailscale_connect", methods=["POST", "GET"])
def api_tailscale_connect():
    """Déclenche la connexion Tailscale sur le Dell et renvoie le lien d'authentification (AuthURL) ou l'IP 100.x.y.z."""
    st = get_tailscale_status()
    if not st["installed"]:
        return jsonify({"ok": False, "error": "Tailscale n'est pas installé.", **st})
    if not st["connected"] and not st["auth_url"]:
        try:
            subprocess.Popen(
                [TAILSCALE_EXE, "up", "--unattended"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(8):
                time.sleep(0.5)
                st = get_tailscale_status()
                if st["auth_url"] or st["connected"]:
                    break
        except Exception as e:
            write_log(f"Tailscale up info: {e}")
    return jsonify({"ok": True, **st})


@app.route("/api/stream_healer_status")
def api_stream_healer_status():
    return jsonify(load_sources_config())


@app.route("/api/stream_healer_run", methods=["POST", "GET"])
def api_stream_healer_run():
    cfg = run_stream_healer()
    return jsonify({"ok": True, **cfg})


@app.route("/hugotify")
@app.route("/iliantify")
def iliantify_app():
    """Sert la WebApp musicale autonome IlianTify (Clone Spotify/Deezer iOS)."""
    if os.path.exists(ILIANTIFY_HTML_FILE):
        return open(ILIANTIFY_HTML_FILE, encoding="utf-8", errors="ignore").read()
    return redirect("/")


@app.route("/iliantify_icon.png")
def iliantify_icon():
    icon_p = os.path.join(STATIC_DIR, "iliantify_icon.png")
    if os.path.exists(icon_p):
        return send_file(icon_p, mimetype="image/png", max_age=86400)
    return "", 404


@app.route("/manifest_iliantify.json")
@app.route("/iliantify_manifest.json")
def manifest_iliantify():
    return jsonify(
        {
            "name": "HugoTify Music",
            "short_name": "HugoTify",
            "description": "Application de streaming et téléchargement musical personnel de Hugo (Mode Hors-Ligne inclus)",
            "start_url": "/iliantify",
            "scope": "/",
            "display": "standalone",
            "background_color": "#09090b",
            "theme_color": "#09090b",
            "orientation": "portrait",
            "icons": [
                {
                    "src": "/iliantify_icon.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                }
            ],
        }
    )


@app.route("/sw_iliantify.js")
def sw_iliantify():
    """MISSION 3 : Service Worker pour IlianTify sur iPhone (CacheStorage 'iliantify-shell-v1',
    Network-First avec timeout rapide de 2.5s et fallback immédiat sur le Cache en Mode Avion)."""
    sw_code = r"""const CACHE_NAME = 'iliantify-shell-v1';
const APP_SHELL = [
    '/iliantify',
    '/manifest_iliantify.json',
    '/iliantify_manifest.json',
    '/iliantify_icon.png'
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return Promise.allSettled(
                APP_SHELL.map((url) =>
                    fetch(url, { cache: 'no-cache' }).then((res) => {
                        if (res && res.ok) {
                            return cache.put(url, res.clone());
                        }
                    })
                )
            );
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys.map((k) => {
                    if (k !== CACHE_NAME && k.startsWith('iliantify-shell-')) {
                        return caches.delete(k);
                    }
                })
            )
        ).then(() => self.clients.claim())
    );
});

function fetchWithTimeout(request, timeoutMs) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('SW_TIMEOUT')), timeoutMs);
        fetch(request)
            .then((res) => {
                clearTimeout(timer);
                resolve(res);
            })
            .catch((err) => {
                clearTimeout(timer);
                reject(err);
            });
    });
}

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    const path = url.pathname;

    // Ne jamais mettre en cache les flux audio directs (gérés par IndexedDB en mode hors-ligne)
    if (
        path.startsWith('/stream') ||
        path.startsWith('/api/music_offline_stream') ||
        path.startsWith('/api/music_download')
    ) {
        return;
    }

    // 1. Navigation vers /iliantify ou ressources App Shell + Catalogue API -> Network-First (2.5s max) + Fallback Cache
    if (
        path === '/iliantify' ||
        path === '/manifest_iliantify.json' ||
        path === '/iliantify_manifest.json' ||
        path === '/iliantify_icon.png' ||
        path === '/api/music_library' ||
        path === '/api/music_favorites' ||
        path === '/api/deezer_home'
    ) {
        event.respondWith(
            fetchWithTimeout(req, 2500)
                .then((netRes) => {
                    if (netRes && netRes.ok) {
                        const clone = netRes.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
                    }
                    return netRes;
                })
                .catch(async () => {
                    const cached = await caches.match(req, { ignoreSearch: path === '/iliantify' });
                    if (cached) return cached;
                    if (path === '/iliantify' || req.mode === 'navigate') {
                        const shell = await caches.match('/iliantify');
                        if (shell) return shell;
                    }
                    return new Response(
                        JSON.stringify({ offline: true, tracks: [], albums: [], artists: [], favorites: [] }),
                        { status: 200, headers: { 'Content-Type': 'application/json' } }
                    );
                })
        );
        return;
    }

    // 2. Pochettes d'albums / artistes (/api/music_cover, /api/music_offline_cover) -> Cache-First avec mise à jour réseau
    if (path.startsWith('/api/music_cover') || path.startsWith('/api/music_offline_cover')) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const netFetch = fetchWithTimeout(req, 3500)
                    .then((netRes) => {
                        if (netRes && netRes.ok) {
                            const clone = netRes.clone();
                            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
                        }
                        return netRes;
                    })
                    .catch(() => cached);
                return cached || netFetch;
            })
        );
        return;
    }
});
"""
    return Response(
        sw_code,
        mimetype="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@app.route("/api/music_favorites", methods=["GET", "POST"])
def api_music_favorites():
    favs = []
    if os.path.exists(FAVORITES_FILE):
        try:
            favs = json.load(open(FAVORITES_FILE, encoding="utf-8"))
        except Exception:
            favs = []
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        path = (data.get("path") or request.form.get("path") or "").strip()
        if path:
            if path in favs:
                favs.remove(path)
            else:
                favs.append(path)
            try:
                with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
                    json.dump(favs, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
    return jsonify({"favorites": favs})


@app.route("/")
def index():
    tpl_index = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(tpl_index):
        return render_template("index.html")
    return open(HTML_FILE, encoding="utf-8", errors="ignore").read()


@app.route("/api/status")
def api_status():
    total, used, free = shutil.disk_usage(BASE_DIR)
    logs = (
        "".join(
            open(LOG_FILE, encoding="utf-8", errors="ignore").readlines()[-50:]
        )
        if os.path.exists(LOG_FILE)
        else "Prêt."
    )
    sh_cfg = load_sources_config()
    return jsonify(
        {
            **STATUS,
            "disk_free": round(free / (1024**3), 1),
            "disk_total": round(total / (1024**3), 1),
            "disk_pct": round((used / total) * 100, 1),
            "music_mb": folder_size_mb(MUSIC_DIR),
            "anime_mb": folder_size_mb(ANIME_DIR),
            "films_mb": folder_size_mb(FILMS_DIR),
            "series_mb": folder_size_mb(SERIES_DIR),
            "logs": logs,
            "hub_url": get_tunnel_url("cf_hub.log"),
            "jf_url": get_tunnel_url("cf_jf.log"),
            "nd_url": get_tunnel_url("cf_nd.log"),
            "fb_url": get_tunnel_url("cf_fb.log"),
            "ag_url": get_tunnel_url("cf_ag.log"),
            "ag_port": get_ag_port(),
            "hostname": socket.gethostname(),
            "ips": get_local_ips(),
            "cwd": TERM_CWD,
            "tailscale": get_tailscale_status(),
            "stream_healer": {
                "last_check": sh_cfg.get("last_check", ""),
                "last_status": sh_cfg.get("last_status", "Opérationnel"),
                "sources": sh_cfg.get("sources", {}),
            },
        }
    )


@app.route("/api/cmd", methods=["POST"])
def api_cmd():
    global TERM_CWD
    c = ""
    if request.is_json:
        c = (request.json or {}).get("cmd", "")
    else:
        c = request.form.get("cmd", "")
    c = (c or "").strip()
    if not c:
        return jsonify({"output": "", "cwd": TERM_CWD, "prompt": f"PS {TERM_CWD}>"})

    if not os.path.exists(TERM_CWD):
        TERM_CWD = BASE_DIR

    ps_script = f"""
[Console]::InputEncoding = [Console]::OutputEncoding = $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location -LiteralPath '{TERM_CWD.replace("'", "''")}'
try {{
    {c}
}} catch {{
    Write-Error $_
}}
Write-Output "__HUB_CWD__:$((Get-Location).Path)"
"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            env=get_env(),
        )
        raw_out = (r.stdout or "") + (r.stderr or "")
        lines = raw_out.splitlines()
        cleaned_lines = []
        for ln in lines:
            if ln.startswith("__HUB_CWD__:"):
                new_cwd = ln.split("__HUB_CWD__:", 1)[1].strip()
                if new_cwd and os.path.exists(new_cwd):
                    TERM_CWD = new_cwd
            else:
                cleaned_lines.append(ln)
        final_out = "\n".join(cleaned_lines).strip()
        return jsonify(
            {
                "output": final_out,
                "cwd": TERM_CWD,
                "prompt": f"PS {TERM_CWD}>",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "output": f"Erreur d'exécution : {e}",
                "cwd": TERM_CWD,
                "prompt": f"PS {TERM_CWD}>",
            }
        )


@app.route("/api/restart_all", methods=["POST"])
def api_restart_all():
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            os.path.join(BASE_DIR, "start_all.ps1"),
        ]
    )
    return jsonify({"ok": True})


@app.route("/api/clear_logs", methods=["POST"])
def api_clear_logs():
    open(LOG_FILE, "w", encoding="utf-8").write("")
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global CURRENT_PROC
    STATUS["stop"] = True
    with QUEUE_LOCK:
        DOWNLOAD_QUEUE.clear()
        STATUS["queue_count"] = 0
    if CURRENT_PROC:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(CURRENT_PROC.pid)],
                capture_output=True,
                timeout=4,
            )
        except Exception:
            pass
        try:
            CURRENT_PROC.kill()
        except Exception:
            pass
        CURRENT_PROC = None
    try:
        subprocess.run(["taskkill", "/F", "/IM", "yt-dlp.exe"], capture_output=True, timeout=3)
    except Exception:
        pass
    STATUS["active"] = False
    STATUS["title"] = "Aucun téléchargement actif"
    STATUS["step"] = "⏹️ Téléchargement arrêté."
    STATUS["percent"] = 0
    STATUS["speed"] = "-"
    STATUS["error"] = ""
    write_log("⏹️ Téléchargement et file d'attente arrêtés par l'utilisateur.")
    return jsonify({"ok": True, "status": STATUS})


# --- STUDIO MAC & ÉDITEUR DE CODE À DISTANCE + SAUVEGARDES ---
@app.route("/api/code_read")
def api_code_read():
    rel = request.args.get("file", "index.html").strip()
    target = os.path.abspath(os.path.join(BASE_DIR, rel))
    if not target.startswith(os.path.abspath(BASE_DIR)) or not os.path.isfile(target):
        return jsonify({"ok": False, "error": "Fichier introuvable dans C:\\Serveur."}), 404
    content = open(target, encoding="utf-8", errors="replace").read()
    return jsonify({"ok": True, "file": rel, "content": content})


@app.route("/api/code_save", methods=["POST"])
def api_code_save():
    rel = (request.form.get("file") or "").strip()
    content = request.form.get("content") or ""
    target = os.path.abspath(os.path.join(BASE_DIR, rel))
    if not rel or not target.startswith(os.path.abspath(BASE_DIR)):
        return jsonify({"ok": False, "error": "Chemin non autorisé."}), 400

    if target.lower().endswith(".py"):
        try:
            compile(content, rel, "exec")
        except SyntaxError as se:
            return jsonify(
                {
                    "ok": False,
                    "error": f"Erreur de syntaxe Python ligne {se.lineno} : {se.msg}",
                }
            )

    snap = create_snapshot(f"avant_modif_{os.path.basename(rel)}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    write_log(f"📝 Fichier modifié à distance : {rel} (backup: {snap})")
    return jsonify({"ok": True, "snapshot": snap})


@app.route("/api/backups_list")
def api_backups_list():
    snaps = []
    if os.path.exists(BACKUP_DIR):
        for d in sorted(os.listdir(BACKUP_DIR), reverse=True):
            fp = os.path.join(BACKUP_DIR, d)
            if os.path.isdir(fp):
                files = os.listdir(fp)
                snaps.append(
                    {
                        "name": d,
                        "files_count": len(files),
                        "size_kb": round(folder_size_mb(fp) * 1024, 1),
                    }
                )
    return jsonify({"backups": snaps})


@app.route("/api/backups_create", methods=["POST"])
def api_backups_create():
    lbl = request.form.get("label", "manuel")
    name = create_snapshot(lbl)
    return jsonify({"ok": True, "name": name})


@app.route("/api/backups_restore", methods=["POST"])
def api_backups_restore():
    name = request.form.get("name", "").strip()
    snap_dir = os.path.abspath(os.path.join(BACKUP_DIR, name))
    if not name or not snap_dir.startswith(os.path.abspath(BACKUP_DIR)) or not os.path.isdir(snap_dir):
        return jsonify({"ok": False, "error": "Sauvegarde introuvable."}), 404
    create_snapshot("avant_restauration")
    for fn in os.listdir(snap_dir):
        if fn in ("hub.py", "index.html", "watchdog.ps1", "start_all.ps1", "filebrowser.db"):
            shutil.copy2(os.path.join(snap_dir, fn), os.path.join(BASE_DIR, fn))
        elif fn == "navidrome.toml":
            shutil.copy2(
                os.path.join(snap_dir, fn),
                os.path.join(BASE_DIR, "navidrome", "navidrome.toml"),
            )
    write_log(f"⏪ Restauration appliquée depuis : {name}")
    return jsonify({"ok": True})


@app.route("/api/backups_download_zip")
def api_backups_download_zip():
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in BACKUP_FILES:
            p = os.path.join(BASE_DIR, rel)
            if os.path.exists(p):
                zf.write(p, arcname=rel)
    mem.seek(0)
    ts = time.strftime("%Y%m%d_%H%M")
    return send_file(
        mem,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"Serveur_Hugo_Backup_{ts}.zip",
    )


# --- MUSIQUE : RECHERCHE (YOUTUBE MUSIC OFFICIEL + DEEZER + ONGLET TOUT YOUTUBE) ---
@app.route("/api/music_preview")
def api_music_preview():
    q = request.args.get("q", "").strip()
    m_type = request.args.get("type", "ytmusic").strip()
    results = []
    if not q:
        return jsonify(results)

    if m_type == "ytmusic":
        return jsonify(search_ytmusic_official_songs(q, limit=12))

    if m_type == "youtube_all":
        return jsonify(search_youtube_all_videos(q, limit=14))

    try:
        r = requests.get(
            f"https://api.deezer.com/search/{m_type}",
            params={"q": q, "limit": 10},
            timeout=10,
        ).json()
        for item in r.get("data", []):
            if m_type == "album":
                results.append(
                    {
                        "id": item["id"],
                        "type": "album",
                        "title": item["title"],
                        "artist": item.get("artist", {}).get("name", ""),
                        "subtitle": f"💿 Album • {item['artist']['name']}",
                        "image": item.get("cover_medium", ""),
                        "preview": "",
                    }
                )
            elif m_type == "artist":
                results.append(
                    {
                        "id": item["id"],
                        "type": "artist",
                        "title": item["name"],
                        "artist": item["name"],
                        "subtitle": "🔥 Top 10 titres officiels de l'artiste",
                        "image": item.get("picture_medium", ""),
                        "preview": "",
                    }
                )
            else:
                dur_s = int(item.get("duration") or 0)
                dur_str = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else ""
                alb_name = (item.get("album") or {}).get("title", "")
                results.append(
                    {
                        "id": item["id"],
                        "type": "track",
                        "title": item["title"],
                        "artist": item.get("artist", {}).get("name", ""),
                        "subtitle": f"{item['artist']['name']} • {alb_name}" + (f" ({dur_str})" if dur_str else ""),
                        "image": item.get("album", {}).get("cover_medium", ""),
                        "preview": item.get("preview", ""),
                    }
                )
    except Exception as e:
        write_log(f"Deezer preview err: {e}")
    return jsonify(results)


@app.route("/api/music_find_preview")
def api_music_find_preview():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"preview": ""})
    q_clean = re.sub(r"[\(\[].*?[\)\]]", "", q).strip()
    try:
        r = requests.get(
            "https://api.deezer.com/search/track",
            params={"q": q_clean, "limit": 1},
            timeout=5,
        ).json()
        data = r.get("data", [])
        if data and data[0].get("preview"):
            return jsonify({"preview": data[0]["preview"]})
    except Exception:
        pass
    try:
        r_it = requests.get(
            "https://itunes.apple.com/search",
            params={"term": q_clean, "country": "FR", "entity": "song", "limit": 1},
            timeout=5,
        ).json()
        res = r_it.get("results", [])
        if res and res[0].get("previewUrl"):
            return jsonify({"preview": res[0]["previewUrl"]})
    except Exception:
        pass
    return jsonify({"preview": ""})


@app.route("/api/music_download", methods=["POST"])
def api_music_download():
    m_type = request.form.get("type", "track")
    item_id = request.form.get("id", "")
    title = request.form.get("title", "Musique")
    artist = request.form.get("artist", "")
    image = request.form.get("image", "")
    enqueue_download(
        f"🎵 {artist} - {title}" if artist else f"🎵 {title}",
        music_download_worker,
        m_type,
        item_id,
        title,
        artist,
        image,
    )
    return jsonify({"ok": True, "queued": STATUS["queue_count"]})


# --- CATALOGUE UNIVERSEL (TENDANCES, DISNEY+, HBO MAX, ANIMÉS, FILMS, SÉRIES) ---
@app.route("/api/media_catalog")
def api_media_catalog():
    flt = request.args.get("filter", "trending").strip().lower()
    q = request.args.get("q", "").strip()
    cache_key = f"{flt}:{q.lower()}"
    if cache_key in CATALOG_CACHE and (time.time() - CATALOG_CACHE[cache_key]["ts"] < 600):
        return jsonify(CATALOG_CACHE[cache_key]["items"])

    items = []
    try:
        if q:
            if flt == "animes":
                items.extend(search_anime_sama_items(q, limit=14))
            elif flt == "movies":
                items.extend(fetch_itunes_movies(q, limit=12))
            elif flt == "series":
                r_tv = requests.get(
                    "https://api.tvmaze.com/search/shows",
                    params={"q": q},
                    timeout=6,
                ).json()
                for entry in r_tv[:12]:
                    sh = entry.get("show") or {}
                    img = (sh.get("image") or {}).get("original") or (sh.get("image") or {}).get("medium") or ""
                    wc = (sh.get("webChannel") or {}).get("name") or (sh.get("network") or {}).get("name") or "Série TV"
                    items.append(
                        {
                            "id": f"tvmaze:{sh.get('id')}",
                            "tvmaze_id": sh.get("id"),
                            "imdb_id": (sh.get("externals") or {}).get("imdb") or "",
                            "media_type": "series",
                            "title": sh.get("name", q),
                            "year": (sh.get("premiered") or "")[:4] or "2024",
                            "badge": f"📺 {wc}",
                            "image": img,
                            "synopsis": strip_html(sh.get("summary") or "Série TV disponible."),
                        }
                    )
            else:
                items.extend(search_anime_sama_items(q, limit=5))
                items.extend(fetch_itunes_movies(q, limit=5))
                r_tv = requests.get(
                    "https://api.tvmaze.com/search/shows",
                    params={"q": q},
                    timeout=6,
                ).json()
                for entry in r_tv[:6]:
                    sh = entry.get("show") or {}
                    img = (sh.get("image") or {}).get("original") or (sh.get("image") or {}).get("medium") or ""
                    wc = (sh.get("webChannel") or {}).get("name") or (sh.get("network") or {}).get("name") or "Série TV"
                    badge = (
                        "🏰 Disney+"
                        if "disney" in wc.lower()
                        else ("🐉 HBO Max" if "hbo" in wc.lower() or wc.lower() == "max" else f"📺 {wc}")
                    )
                    items.append(
                        {
                            "id": f"tvmaze:{sh.get('id')}",
                            "tvmaze_id": sh.get("id"),
                            "imdb_id": (sh.get("externals") or {}).get("imdb") or "",
                            "media_type": "series",
                            "title": sh.get("name", q),
                            "year": (sh.get("premiered") or "")[:4] or "2024",
                            "badge": badge,
                            "image": img,
                            "synopsis": strip_html(
                                sh.get("summary") or "Série disponible pour Jellyfin."
                            ),
                        }
                    )
        elif flt == "animes":
            for aq in CURATED_ANIMES:
                found = search_anime_sama_items(aq, limit=1)
                if found:
                    items.append(found[0])
        elif flt == "disney":
            for c in CURATED_DISNEY:
                if c["type"] == "series":
                    res = fetch_tvmaze_show(c["q"], badge_override=c["badge"])
                    if res:
                        items.append(res)
                else:
                    m_list = fetch_itunes_movies(c["q"], limit=1, badge_override=c["badge"])
                    if m_list:
                        items.append(m_list[0])
        elif flt == "hbo":
            for c in CURATED_HBO:
                if c["type"] == "series":
                    res = fetch_tvmaze_show(c["q"], badge_override=c["badge"])
                    if res:
                        items.append(res)
                else:
                    m_list = fetch_itunes_movies(c["q"], limit=1, badge_override=c["badge"])
                    if m_list:
                        items.append(m_list[0])
        elif flt == "movies":
            r_top = requests.get(
                "https://itunes.apple.com/fr/rss/topmovies/limit=16/json", timeout=6
            ).json()
            for entry in r_top.get("feed", {}).get("entry", []):
                imgs = entry.get("im:image", [])
                img_u = imgs[-1].get("label", "").replace("170x170bb", "600x600bb") if imgs else ""
                title = (entry.get("im:name") or {}).get("label", "Film")
                year = ((entry.get("im:releaseDate") or {}).get("label", ""))[:4] or "2025"
                cat = ((entry.get("category") or {}).get("attributes") or {}).get("label", "Film HD")
                summary = (entry.get("summary") or {}).get("label", f"Film {cat} ({year}) en HD.")
                items.append(
                    {
                        "id": f"itunes:{title}",
                        "imdb_id": "",
                        "media_type": "movie",
                        "title": title,
                        "year": year,
                        "badge": f"🍿 {cat}",
                        "image": img_u,
                        "synopsis": summary,
                    }
                )
        elif flt == "series":
            for c in (CURATED_HBO[:6] + CURATED_DISNEY[:6]):
                if c["type"] == "series":
                    res = fetch_tvmaze_show(c["q"], badge_override=c["badge"])
                    if res:
                        items.append(res)
        else:
            for c in [CURATED_HBO[0], CURATED_DISNEY[0], CURATED_HBO[1], CURATED_DISNEY[1]]:
                res = fetch_tvmaze_show(c["q"], badge_override=c["badge"])
                if res:
                    items.append(res)
            for aq in ["Solo Leveling", "One Piece", "Jujutsu Kaisen"]:
                found = search_anime_sama_items(aq, limit=1)
                if found:
                    items.append(found[0])
            try:
                r_top = requests.get(
                    "https://itunes.apple.com/fr/rss/topmovies/limit=5/json", timeout=6
                ).json()
                for entry in r_top.get("feed", {}).get("entry", []):
                    imgs = entry.get("im:image", [])
                    img_u = imgs[-1].get("label", "").replace("170x170bb", "600x600bb") if imgs else ""
                    title = (entry.get("im:name") or {}).get("label", "Film")
                    year = ((entry.get("im:releaseDate") or {}).get("label", ""))[:4] or "2025"
                    summary = (entry.get("summary") or {}).get("label", "Film tendance en HD.")
                    items.append(
                        {
                            "id": f"itunes:{title}",
                            "imdb_id": "",
                            "media_type": "movie",
                            "title": title,
                            "year": year,
                            "badge": "🔥 Film",
                            "image": img_u,
                            "synopsis": summary,
                        }
                    )
            except Exception:
                pass
    except Exception as e:
        write_log(f"Catalogue media err: {e}")

    if items:
        CATALOG_CACHE[cache_key] = {"ts": time.time(), "items": items}
    return jsonify(items)


@app.route("/api/series_episodes")
def api_series_episodes():
    item_id = request.args.get("id", "")
    title = request.args.get("title", "").strip()
    seasons_map = {}
    try:
        tvmaze_id = None
        if item_id.startswith("tvmaze:"):
            tvmaze_id = item_id.split(":", 1)[1]
        elif title:
            r_s = requests.get(
                "https://api.tvmaze.com/singlesearch/shows",
                params={"q": title},
                timeout=6,
            )
            if r_s.status_code == 200:
                tvmaze_id = r_s.json().get("id")

        if tvmaze_id:
            eps = requests.get(
                f"https://api.tvmaze.com/shows/{tvmaze_id}/episodes", timeout=6
            ).json()
            for ep in eps:
                s_num = int(ep.get("season") or 1)
                e_num = int(ep.get("number") or 1)
                seasons_map.setdefault(s_num, []).append(
                    {
                        "episode": e_num,
                        "name": ep.get("name") or f"Épisode {e_num}",
                    }
                )
    except Exception:
        pass

    if not seasons_map:
        seasons_map[1] = [{"episode": i, "name": f"Épisode {i}"} for i in range(1, 11)]

    seasons_list = [
        {"season": s, "count": len(eps), "episodes": eps}
        for s, eps in sorted(seasons_map.items())
    ]
    return jsonify({"seasons": seasons_list})


@app.route("/api/download_media", methods=["POST"])
def api_download_media():
    m_type = request.form.get("media_type", "movie")
    title = request.form.get("title", "Media")
    year = request.form.get("year", "")
    season = request.form.get("season", "1")
    start_ep = request.form.get("start_ep", "1")
    end_ep = request.form.get("end_ep", "1")
    imdb_id = request.form.get("imdb_id", "")
    custom_url = request.form.get("custom_url", "")
    lang = (request.form.get("lang") or "vf").lower().strip()
    if lang not in ("vf", "vostfr", "vo"):
        lang = "vf"
    enqueue_download(
        f"🎬 {title} ({lang.upper()})",
        media_download_worker,
        m_type,
        title,
        year,
        season,
        start_ep,
        end_ep,
        imdb_id,
        custom_url,
        lang,
    )
    return jsonify({"ok": True, "queued": STATUS["queue_count"]})


@app.route("/api/anime_search")
def api_anime_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    return jsonify(search_anime_sama_items(q, limit=12))


@app.route("/api/anime_seasons")
def api_anime_seasons():
    raw_u = request.args.get("url", "")
    if raw_u.startswith("anime:"):
        raw_u = raw_u.split("anime:", 1)[1]
    url = normalize_as_url(raw_u)
    seasons, seen = [], set()
    try:
        r = scraper.get(url, timeout=10)
        clean_html = re.sub(r"/\*.*?\*/", "", r.text, flags=re.DOTALL)
        clean_active = "\n".join(
            [l for l in clean_html.splitlines() if not l.strip().startswith("//")]
        )
        for name, rel_path in re.findall(
            r'panneauAnime\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            clean_active,
        ):
            if (
                name.lower() == "nom"
                or "scan" in name.lower()
                or "scan" in rel_path.lower()
            ):
                continue
            base_s = re.sub(r"/(vostfr|vf|vj)$", "", rel_path.strip("/"))
            found_for_season = {}
            for lang_code in ["vf", "vostfr", "vj"]:
                js_u = f"{url}{base_s}/{lang_code}/episodes.js"
                ui_lang = "vo" if lang_code == "vj" else lang_code
                if js_u not in seen:
                    seen.add(js_u)
                    if rel_path.strip("/").endswith(f"/{lang_code}"):
                        seasons.append({"name": name, "lang": ui_lang, "js_url": js_u})
                        found_for_season[ui_lang] = js_u
                    else:
                        try:
                            if (
                                scraper.get(
                                    js_u, headers={"Referer": url}, timeout=4
                                ).status_code
                                == 200
                            ):
                                seasons.append(
                                    {"name": name, "lang": ui_lang, "js_url": js_u}
                                )
                                found_for_season[ui_lang] = js_u
                        except Exception:
                            pass
    except Exception:
        pass
    return jsonify({"seasons": seasons})


@app.route("/api/season_info")
def api_season_info():
    return jsonify({"count": len(parse_episodes_js(request.args.get("js_url", "")))})


@app.route("/api/download_season", methods=["POST"])
def api_download_season():
    title = request.form.get("title", "Anime")
    season = request.form.get("season", "Saison 1")
    js_url = request.form.get("js_url", "")
    start_ep = request.form.get("start_ep", "1")
    end_ep = request.form.get("end_ep", "1")
    enqueue_download(
        f"🎌 {title} ({season} Ép {start_ep}-{end_ep})",
        season_download_worker,
        title,
        season,
        js_url,
        start_ep,
        end_ep,
    )
    return jsonify({"ok": True, "queued": STATUS["queue_count"]})


# --- GESTION DES MÉDIAS RANGÉS PAR DOSSIERS / SÉRIES / OEUVRES ---
@app.route("/api/files")
def api_files():
    groups = []
    flat_files = []
    categories = [
        ("animes", "🎌 Animés", ANIME_DIR, (".mp4", ".mkv", ".webm")),
        ("films", "🍿 Films", FILMS_DIR, (".mp4", ".mkv", ".webm")),
        ("series", "📺 Séries", SERIES_DIR, (".mp4", ".mkv", ".webm")),
        ("musique", "🎵 Musique", MUSIC_DIR, (".mp3", ".flac", ".m4a")),
    ]
    for cat_key, cat_label, base_d, exts in categories:
        if not os.path.exists(base_d):
            continue
        for entry in sorted(os.listdir(base_d)):
            if entry.startswith("."):
                continue
            entry_path = os.path.join(base_d, entry)
            if not os.path.isdir(entry_path):
                continue
            item_files = []
            total_mb = 0.0
            for root, _, fnames in os.walk(entry_path):
                for f in sorted(fnames):
                    if f.lower().endswith(exts) and not f.endswith(".part"):
                        fp = os.path.join(root, f)
                        try:
                            sz = round(os.path.getsize(fp) / 1048576, 1)
                        except Exception:
                            sz = 0.0
                        total_mb += sz
                        sub_folder = os.path.basename(root)
                        f_obj = {
                            "name": f,
                            "subfolder": sub_folder if sub_folder != entry else "",
                            "folder": f"{cat_label} • {entry}",
                            "size_mb": sz,
                            "path": fp,
                        }
                        item_files.append(f_obj)
                        flat_files.append(f_obj)
            if item_files:
                groups.append(
                    {
                        "category": cat_key,
                        "category_label": cat_label,
                        "title": entry,
                        "folder_path": entry_path,
                        "count": len(item_files),
                        "total_mb": round(total_mb, 1),
                        "files": item_files,
                    }
                )
    return jsonify({"groups": groups, "files": flat_files})


@app.route("/stream")
def stream():
    p = os.path.abspath(request.args.get("path", ""))
    if p.startswith(os.path.abspath(MEDIAS_DIR)) and os.path.exists(p):
        mime = "audio/mpeg" if p.lower().endswith(".mp3") else "video/mp4"
        return send_file(p, mimetype=mime, conditional=True)
    return "Introuvable", 404


@app.route("/api/delete_file", methods=["POST"])
def api_delete_file():
    p = os.path.abspath(request.form.get("path", ""))
    if p.startswith(os.path.abspath(MEDIAS_DIR)) and os.path.exists(p):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            write_log(f"🗑️ Dossier supprimé : {os.path.basename(p)}")
        else:
            os.remove(p)
            write_log(f"🗑️ Fichier supprimé : {os.path.basename(p)}")
        rebuild_singles_playlist()
        refresh_jellyfin_library()
    return jsonify({"ok": True})


def publish_tunnel_url():
    try:
        u = get_tunnel_url("cf_hub.log")
        if u:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=u.encode("utf-8"),
                headers={"Title": "Portail 4G/5G Serveur Hugo", "Click": u},
                timeout=6,
            )
    except Exception:
        pass


def startup_maintenance():
    cleanup_existing_music()
    ensure_jellyfin_configured()
    publish_tunnel_url()
    try:
        run_stream_healer()
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=startup_maintenance, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
