# 🖥️ Serveur Ilian — Hub média & musique auto-hébergé (Windows)

Portail web tout-en-un pour un PC Windows servant de serveur domestique :

- 🎧 **IlianTify** : application musicale PWA (style Spotify/Deezer), mode hors-ligne iPhone (IndexedDB + Service Worker), sync Deezer/Spotify/YouTube Music
- 🎬 **Catalogue** Films / Séries / Animés avec vérificateur anti-bande-annonce, choix VF/VOSTFR/VO
- 🖥️ **Hub Flask** (`hub.py`) : API, terminal PowerShell web, éditeur de code distant, sauvegardes
- 🛡️ **Watchdog** PowerShell : relance Jellyfin, Navidrome, FileBrowser, AdGuard Home, tunnels Cloudflare
- 🌍 Accès distant : Cloudflare Tunnel + Tailscale

## Prérequis
Windows 10/11, Python 3.11+, et dans `bin/` : `ffmpeg`, `yt-dlp`, `cloudflared`, `filebrowser`.
Installés à part : Jellyfin, Navidrome, AdGuard Home, Tailscale.

```powershell
pip install flask requests beautifulsoup4 cloudscraper mutagen ytmusicapi
copy secrets.example.json secrets.json   # puis édite tes valeurs
python hub.py                            # http://localhost:5000
```

Lancement complet (services + tunnels) : `powershell -File start_all.ps1`.

## Configuration
Les secrets vivent dans `secrets.json` (**ignoré par Git**) ou en variables d'environnement
(`JF_PASSWORD`, `NTFY_TOPIC`). Voir `secrets.example.json`.

## ⚠️ Sécurité
`/api/cmd` (terminal), `/api/code_save` et les routes d'administration n'ont **aucune authentification**.
N'expose jamais ce hub sur Internet sans protection (Tailscale, Cloudflare Access ou mot de passe).

## Licence
MIT — voir `LICENSE`.
