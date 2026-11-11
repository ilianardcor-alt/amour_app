import os
import re
import shutil
import requests
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TRCK, ID3NoHeaderError

MUSIC_DIR = r"C:\Serveur\Medias\Musique"
SINGLES_DIR = os.path.join(MUSIC_DIR, "Singles")
OLD_ALBUMS_DIR = os.path.join(MUSIC_DIR, "Albums")

ARTIST_CACHE = {}
ALBUM_COVER_CACHE = {}
TRACK_COVER_CACHE = {}


def clean_name(s):
    s = re.sub(r'[\\/*?:"<>|]', "", str(s or "")).strip()
    return s or "Inconnu"


def fetch_img_bytes(url):
    if not url:
        return None
    try:
        hi_url = re.sub(r"/\d+x\d+-000000-", "/1000x1000-000000-", str(url))
        r = requests.get(hi_url, timeout=10)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
        if hi_url != url:
            r2 = requests.get(url, timeout=10)
            if r2.status_code == 200 and len(r2.content) > 1000:
                return r2.content
    except Exception as e:
        print(f"  [WARN] Erreur telechargement image {url}: {e}")
    return None


def get_artist_picture_bytes(artist_name):
    key = artist_name.lower().strip()
    if key in ARTIST_CACHE:
        return ARTIST_CACHE[key]
    try:
        r = requests.get(
            "https://api.deezer.com/search/artist",
            params={"q": artist_name, "limit": 3},
            timeout=8,
        ).json()
        data = r.get("data") or []
        if data:
            best = data[0]
            for d in data:
                if d.get("name", "").lower().strip() == key:
                    best = d
                    break
            pic_url = (
                best.get("picture_xl")
                or best.get("picture_big")
                or best.get("picture_medium")
                or ""
            )
            b = fetch_img_bytes(pic_url)
            if b:
                ARTIST_CACHE[key] = b
                return b
    except Exception as e:
        print(f"  [WARN] Artist search {artist_name}: {e}")
    ARTIST_CACHE[key] = None
    return None


def get_track_or_album_cover_bytes(artist_name, title_name, album_name=""):
    t_key = f"{artist_name.lower().strip()}|||{title_name.lower().strip()}"
    if t_key in TRACK_COVER_CACHE:
        return TRACK_COVER_CACHE[t_key]

    a_key = f"{artist_name.lower().strip()}|||{album_name.lower().strip()}"
    try:
        # 1. Recherche du morceau précis sur Deezer
        q = f"{artist_name} {title_name}".strip()
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": q, "limit": 5},
            timeout=8,
        ).json()
        data = r.get("data") or []
        best = None
        for cand in data:
            c_art = ((cand.get("artist") or {}).get("name") or "").lower()
            if artist_name.lower() in c_art:
                best = cand
                break
        if not best and data:
            best = data[0]

        if best:
            alb_obj = best.get("album") or {}
            art_obj = best.get("artist") or {}
            cov_url = (
                alb_obj.get("cover_xl")
                or alb_obj.get("cover_big")
                or alb_obj.get("cover_medium")
                or ""
            )
            art_url = (
                art_obj.get("picture_xl")
                or art_obj.get("picture_big")
                or ""
            )
            if art_url and artist_name.lower().strip() not in ARTIST_CACHE:
                ab = fetch_img_bytes(art_url)
                if ab:
                    ARTIST_CACHE[artist_name.lower().strip()] = ab
            b = fetch_img_bytes(cov_url)
            if b:
                TRACK_COVER_CACHE[t_key] = b
                if album_name:
                    ALBUM_COVER_CACHE[a_key] = b
                return b

        # 2. Fallback sur l'album ou l'artiste
        if a_key in ALBUM_COVER_CACHE and ALBUM_COVER_CACHE[a_key]:
            return ALBUM_COVER_CACHE[a_key]

        if album_name and "Singles" not in album_name:
            r_alb = requests.get(
                "https://api.deezer.com/search/album",
                params={"q": f"{artist_name} {album_name}", "limit": 3},
                timeout=8,
            ).json()
            albs = r_alb.get("data") or []
            if albs:
                cov_url = (
                    albs[0].get("cover_xl")
                    or albs[0].get("cover_big")
                    or albs[0].get("cover_medium")
                    or ""
                )
                b = fetch_img_bytes(cov_url)
                if b:
                    ALBUM_COVER_CACHE[a_key] = b
                    TRACK_COVER_CACHE[t_key] = b
                    return b
    except Exception as e:
        print(f"  [WARN] Track/Album search {artist_name} - {title_name}: {e}")

    # 3. Dernier fallback : photo de l'artiste
    return get_artist_picture_bytes(artist_name)


def migrate_and_retag_all():
    os.makedirs(MUSIC_DIR, exist_ok=True)
    os.makedirs(SINGLES_DIR, exist_ok=True)

    # Collecte de tous les MP3 existants
    all_mp3s = []
    for root, _, files in os.walk(MUSIC_DIR):
        for fn in sorted(files):
            if fn.lower().endswith(".mp3"):
                all_mp3s.append(os.path.join(root, fn))

    print(f"=== MIGRATION & RE-TAGGAGE HD DE {len(all_mp3s)} FICHIERS MP3 ===")
    migrated_count = 0

    for fp in all_mp3s:
        fn = os.path.basename(fp)
        parent_dir = os.path.dirname(fp)
        parent_name = os.path.basename(parent_dir)
        is_single = os.path.abspath(parent_dir) == os.path.abspath(SINGLES_DIR)

        # Lecture des tags existants
        title, artist, album, album_artist, track_num = "", "", "", "", None
        try:
            tags = ID3(fp)
            if tags.get("TIT2"):
                title = str(tags["TIT2"].text[0]).strip()
            if tags.get("TPE1"):
                artist = str(tags["TPE1"].text[0]).strip()
            if tags.get("TALB"):
                album = str(tags["TALB"].text[0]).strip()
            if tags.get("TPE2"):
                album_artist = str(tags["TPE2"].text[0]).strip()
            if tags.get("TRCK"):
                track_num = str(tags["TRCK"].text[0]).strip()
        except Exception:
            pass

        # Déduction depuis le dossier / nom de fichier si manquant
        m_num = re.match(r"^(\d+)\s*-\s*(.+)$", fn[:-4])
        if m_num:
            if not track_num:
                track_num = str(int(m_num.group(1)))
            if not title:
                title = m_num.group(2).strip()
        elif not title:
            if " - " in fn[:-4]:
                p_a, p_t = fn[:-4].split(" - ", 1)
                if not artist:
                    artist = p_a.strip()
                title = p_t.strip()
            else:
                title = fn[:-4].strip()

        if " - " in parent_name and not is_single:
            p_art, p_alb = parent_name.split(" - ", 1)
            if not artist or artist == "Artiste":
                artist = p_art.strip()
            if not album:
                album = p_alb.strip()
            if not album_artist or album_artist in ("Divers Artistes", "Artiste"):
                album_artist = p_art.strip()

        if not artist:
            artist = "Artiste"
        if not album:
            album = "⚡ Singles & Sons en vrac" if is_single else parent_name

        # Récupération pochette 1000x1000 et photo d'artiste 1000x1000 sur Deezer
        art_bytes = get_artist_picture_bytes(artist)
        cov_bytes = get_track_or_album_cover_bytes(artist, title, album)

        # Sauvegarde systématique de artist.jpg dans C:\Serveur\Medias\Musique\<Nom Artiste>\artist.jpg
        art_clean = clean_name(album_artist if (not is_single and album_artist) else artist)
        artist_folder = os.path.join(MUSIC_DIR, art_clean)
        os.makedirs(artist_folder, exist_ok=True)
        artist_jpg = os.path.join(artist_folder, "artist.jpg")
        if art_bytes and not os.path.exists(artist_jpg):
            with open(artist_jpg, "wb") as f:
                f.write(art_bytes)
            print(f"  [ARTIST HD] Cree : {artist_jpg} ({len(art_bytes)} octets)")

        # Détermination de la destination finale selon Mission 3.1
        if is_single:
            dest_dir = SINGLES_DIR
            dest_fp = fp
            final_album = "⚡ Singles & Sons en vrac"
            final_album_artist = "Singles"
        else:
            alb_clean = clean_name(album)
            if alb_clean.lower().startswith(art_clean.lower() + " - "):
                alb_clean = alb_clean[len(art_clean) + 3 :].strip()
            dest_dir = os.path.join(artist_folder, alb_clean)
            os.makedirs(dest_dir, exist_ok=True)
            dest_fp = os.path.join(dest_dir, fn)
            final_album = album
            final_album_artist = artist

            # Sauvegarde de cover.jpg dans le dossier de l'album
            cover_jpg = os.path.join(dest_dir, "cover.jpg")
            if cov_bytes and not os.path.exists(cover_jpg):
                with open(cover_jpg, "wb") as f:
                    f.write(cov_bytes)
                print(f"  [COVER HD] Cree : {cover_jpg} ({len(cov_bytes)} octets)")

        if os.path.abspath(fp) != os.path.abspath(dest_fp):
            if os.path.exists(dest_fp):
                os.remove(dest_fp)
            shutil.move(fp, dest_fp)

        # Injection des tags ID3 + APIC 1000x1000
        try:
            try:
                id3 = ID3(dest_fp)
            except ID3NoHeaderError:
                id3 = ID3()

            for fr in ["TIT2", "TPE1", "TALB", "TPE2", "TRCK"]:
                id3.delall(fr)

            id3.add(TIT2(encoding=3, text=str(title)))
            id3.add(TPE1(encoding=3, text=str(artist)))
            id3.add(TALB(encoding=3, text=str(final_album)))
            id3.add(TPE2(encoding=3, text=str(final_album_artist)))
            if track_num:
                id3.add(TRCK(encoding=3, text=str(track_num)))

            if cov_bytes:
                id3.delall("APIC")
                id3.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=cov_bytes,
                    )
                )

            id3.save(dest_fp, v2_version=3)
            migrated_count += 1
            print(f"  [OK] {artist} - {title} ({final_album}) -> APIC={'OUI' if cov_bytes else 'NON'}")
        except Exception as e:
            print(f"  [ERR] Tag {dest_fp}: {e}")

    # Nettoyage de l'ancien dossier Albums s'il est vide
    if os.path.exists(OLD_ALBUMS_DIR):
        for r, dirs, files in os.walk(OLD_ALBUMS_DIR, topdown=False):
            if not os.listdir(r):
                try:
                    os.rmdir(r)
                except Exception:
                    pass
        if os.path.exists(OLD_ALBUMS_DIR) and not os.listdir(OLD_ALBUMS_DIR):
            try:
                os.rmdir(OLD_ALBUMS_DIR)
                print("  [CLEAN] Ancien dossier 'Albums' vide supprime.")
            except Exception:
                pass

    print(f"=== TERMINE : {migrated_count}/{len(all_mp3s)} MP3 migres et tagues en HD 1000x1000 ===")


if __name__ == "__main__":
    migrate_and_retag_all()
