/**
 * FEATURE / MUSIC — Recherche musicale, aperçu audio 30s et synchronisation Deezer
 */
import { api } from "../core/api.js?v=6";
import { store } from "../core/state.js?v=6";
import { escJs, escHtml } from "../core/utils.js?v=6";
import { markBtnValidated, showToast } from "../ui/feedback.js?v=6";
import { updateStatus, notifyDownloadStarted } from "./status.js?v=6";
import { loadFiles } from "./library.js?v=6";

export function clearMusicSearchInput() {
  const inp = document.getElementById("m_query");
  if (inp) {
    inp.value = "";
    inp.focus();
  }
  const box = document.getElementById("music_results");
  if (box) box.innerHTML = "";
}

export function toggleDeezerDrawer(forceOpen = null) {
  const dr = document.getElementById("deezer_drawer");
  if (!dr) return;
  const isNowOpen = forceOpen !== null ? forceOpen : dr.style.display === "none";
  dr.style.display = isNowOpen ? "block" : "none";
}

export function switchDeezerTab(tab) {
  ["recs", "pls", "albs"].forEach((k) => {
    const view = document.getElementById("dzview_" + k);
    const btn = document.getElementById("dztab_" + k);
    if (view) view.style.display = k === tab ? (k === "pls" ? "block" : "grid") : "none";
    if (btn) btn.classList.toggle("active", k === tab);
  });
}

export function renderMusicCardHtml(item, isServerStream = false) {
  const img =
    item.image ||
    item.cover_url ||
    "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=120";
  const playUrl = isServerStream ? item.stream_url : item.preview || "";
  const subTxt =
    item.subtitle ||
    (item.artist ? `${item.artist}${item.album ? " • " + item.album : ""}` : "");

  return `
    <div class="spot-card">
      <img src="${img}" alt="" onerror="this.style.opacity='0.2'">
      <div class="spot-info">
        <b title="${escJs(item.title)}">${escHtml(item.title)}</b>
        <span title="${escJs(subTxt)}">${escHtml(subTxt)}</span>
      </div>
      <div class="spot-actions">
        <button type="button" class="btn-spot btn-sm" title="Écouter un extrait de 30s" onclick="playMusicPreview('${escJs(item.title)}', '${escJs(item.artist || "")}', '${escJs(img)}', '${escJs(playUrl)}', ${isServerStream})">▶ Extrait</button>
        ${
          !isServerStream
            ? `<button type="button" class="btn-primary btn-sm" onclick="downloadMusicItem('${item.type || "track"}', '${escJs(item.id)}', '${escJs(item.title)}', '${escJs(item.artist || "")}', '${escJs(img)}', this)">📥 Ajouter</button>`
            : ``
        }
      </div>
    </div>`;
}

export async function loadDeezerHome(force = false) {
  try {
    const d = await api.getDeezerHome(force);
    const stEl = document.getElementById("dz_acct_status");
    if (stEl && d.account_name && d.account_name !== "Non connecté") {
      stEl.textContent = `💜 ${d.account_name} :`;
    }
    const urlInp = document.getElementById("sp_sync_url");
    if (urlInp && d.account_url) {
      urlInp.value = d.account_url;
    }
    const recsEl = document.getElementById("dzview_recs");
    if (recsEl) {
      recsEl.innerHTML = (d.recommendations || []).map((it) => renderMusicCardHtml(it, false)).join("");
    }
    const albsEl = document.getElementById("dzview_albs");
    if (albsEl) {
      albsEl.innerHTML = (d.top_albums || []).map((it) => renderMusicCardHtml(it, false)).join("");
    }
    const pls = d.playlists || [];
    const cntEl = document.getElementById("sp_pl_cnt");
    if (cntEl) cntEl.textContent = pls.length;
    const plsEl = document.getElementById("dzview_pls");
    if (plsEl) {
      plsEl.innerHTML = pls.length
        ? pls
            .map(
              (p) => `
              <div class="status-box" style="margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
                  <b>💜 ${escHtml(p.name)} (${p.tracks_count || (p.tracks || []).length} titres)</b>
                  <button type="button" class="btn-purp btn-sm" onclick="downloadSpotifyPlaylist('${escJs(p.id)}', '${escJs(p.name)}', this)">📥 Tout télécharger</button>
                </div>
                <div class="music-grid" style="max-height:200px">
                  ${(p.tracks || []).slice(0, 30).map((tr) => renderMusicCardHtml(tr, false)).join("")}
                </div>
              </div>`
            )
            .join("")
        : "<div class='sub'>Collez le lien de votre profil ou d'une playlist Deezer ci-dessus puis cliquez sur Synchroniser.</div>";
    }
  } catch (_) {}
}

export async function syncDeezerNow(btnEl) {
  const inp = document.getElementById("sp_sync_url");
  const u = inp ? inp.value.trim() : "";
  if (!u) {
    showToast("Veuillez coller un lien de profil ou de playlist Deezer.", "error");
    return;
  }
  markBtnValidated(btnEl, "Synchronisé");
  try {
    const d = await api.syncDeezer(u);
    if (d.ok) {
      await loadDeezerHome(true);
      toggleDeezerDrawer(true);
      switchDeezerTab("pls");
      showToast("💜 Compte Deezer synchronisé !", "success");
    } else {
      showToast(d.error || "Impossible de synchroniser ce lien Deezer.", "error");
    }
  } catch (_) {
    showToast("Erreur lors de la synchronisation Deezer.", "error");
  }
}

export async function downloadSpotifyPlaylist(pid, name, btnEl) {
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(`💜 Playlist : ${name}`);
  await api.downloadPlaylist(pid);
  updateStatus();
}

export function selectMusicSearchMode(type) {
  store.lastMusicMode = type;
  window.lastMusicMode = type;
  ["track", "album", "artist", "ytm_song", "yt_video"].forEach((k) => {
    const el = document.getElementById("mseg_" + k);
    if (el) {
      const isAct = k === type;
      el.classList.toggle("active", isAct);
      el.setAttribute("aria-selected", isAct ? "true" : "false");
    }
  });
  const inp = document.getElementById("m_query");
  if (inp && inp.value.trim()) {
    previewMusic(type);
  }
}

export async function previewMusic(type = "track") {
  store.lastMusicMode = type;
  window.lastMusicMode = type;
  ["track", "album", "artist", "ytm_song", "yt_video"].forEach((k) => {
    const el = document.getElementById("mseg_" + k);
    if (el) {
      const isAct = k === type;
      el.classList.toggle("active", isAct);
      el.setAttribute("aria-selected", isAct ? "true" : "false");
    }
  });
  const inp = document.getElementById("m_query");
  const q = inp ? inp.value.trim() : "";
  const box = document.getElementById("music_results");
  if (!q) {
    if (inp) inp.focus();
    return;
  }
  if (box) {
    box.innerHTML =
      `<div class="spot-card skeleton" style="height:80px"></div>` +
      `<div class="spot-card skeleton" style="height:80px"></div>` +
      `<div class="spot-card skeleton" style="height:80px"></div>`;
  }
  try {
    const data = await api.searchMusic(q, type);
    if (!data || !data.length) {
      if (box) box.innerHTML = "<div class='status-box'>Aucun résultat musical trouvé pour cette recherche.</div>";
      return;
    }
    if (box) box.innerHTML = data.map((item) => renderMusicCardHtml(item, false)).join("");
  } catch (_) {
    if (box) box.innerHTML = "<div class='status-box'>Impossible d'effectuer la recherche musicale.</div>";
  }
}

export async function downloadMusicItem(type, id, title, artist, image, btnEl) {
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(`🎵 ${artist ? artist + " - " : ""}${title}`);
  await api.downloadMusic({ type, id, title, artist: artist || "", image: image || "" });
  updateStatus();
  setTimeout(() => {
    loadFiles();
  }, 8000);
}

export async function playMusicPreview(title, artist, image, directPreviewUrl, isFullStream = false) {
  let url = directPreviewUrl;
  if (!url && !isFullStream) {
    const q = artist && !title.toLowerCase().includes(artist.toLowerCase()) ? `${artist} ${title}` : title;
    try {
      const d = await api.findMusicPreview(q);
      url = d.preview || "";
    } catch (_) {}
  }
  if (!url) {
    showToast("Aucun extrait 30s disponible (cliquez sur 📥 Ajouter pour le télécharger).", "info");
    return;
  }
  const audio = document.getElementById("preview_audio");
  const bar = document.getElementById("preview_bar_mini");
  const txt = document.getElementById("preview_bar_txt");
  if (audio) {
    audio.src = url;
    audio.play().catch(() => {});
    if (bar) bar.style.display = "flex";
    if (txt) txt.textContent = `▶ Extrait 30s : ${artist ? artist + " - " : ""}${title}`;
    audio.onended = () => {
      if (bar) bar.style.display = "none";
    };
  }
}

export function stopMiniPreview() {
  const audio = document.getElementById("preview_audio");
  const bar = document.getElementById("preview_bar_mini");
  if (audio) {
    audio.pause();
    audio.src = "";
  }
  if (bar) bar.style.display = "none";
}
