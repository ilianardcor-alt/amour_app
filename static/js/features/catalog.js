/**
 * FEATURE / CATALOG — Catalogue Films, Séries & Animés, choix de langue et sources
 */
import { api } from "../core/api.js?v=8";
import { store } from "../core/state.js?v=8";
import { escJs, escHtml } from "../core/utils.js?v=8";
import { markBtnValidated, showToast } from "../ui/feedback.js?v=8";
import { updateStatus, notifyDownloadStarted } from "./status.js?v=8";

export function clearMediaSearchInput() {
  const inp = document.getElementById("ms_query");
  if (inp) {
    inp.value = "";
    inp.focus();
  }
  if (store.isSearchMode) {
    loadMediaCatalog(store.currentFilter);
  }
}

export function setActiveFilterBtn(flt) {
  store.currentFilter = flt;
  ["trending", "disney", "hbo", "animes", "movies", "series"].forEach((k) => {
    const el = document.getElementById("flt_" + k);
    if (el) {
      const isAct = k === flt;
      el.classList.toggle("active", isAct);
      el.setAttribute("aria-selected", isAct ? "true" : "false");
    }
  });
}

export function scrollCatalogCarousel(dir = 1) {
  const strip = document.querySelector("#media_results .poster-strip") || document.getElementById("media_results");
  if (!strip) return;
  strip.scrollBy({ left: dir * 560, behavior: "smooth" });
}

function buildSkeletonPostersHtml(count = 6) {
  let html = '<div class="poster-strip">';
  for (let i = 0; i < count; i++) {
    html += `
      <div class="poster-card" aria-hidden="true">
        <div class="poster-img-wrap skeleton"></div>
        <div class="poster-card-body">
          <div class="skeleton" style="height:16px;width:85%"></div>
          <div class="skeleton" style="height:14px;width:55%"></div>
        </div>
      </div>`;
  }
  html += "</div>";
  return html;
}

export function toggleCatalogExpanded() {
  store.catalogExpanded = !store.catalogExpanded;
  renderMediaItems(store.catalogItems);
}

export async function loadMediaCatalog(flt) {
  const normFlt = flt === "anime" ? "animes" : flt;
  setActiveFilterBtn(normFlt);
  store.isSearchMode = false;
  store.catalogExpanded = false;
  const qEl = document.getElementById("ms_query");
  if (qEl) qEl.value = "";
  const panelEl = document.getElementById("media_action_panel");
  if (panelEl) panelEl.innerHTML = "";
  const box = document.getElementById("media_results");
  if (box) box.innerHTML = buildSkeletonPostersHtml(6);
  try {
    store.catalogItems = await api.getCatalog(normFlt);
    renderMediaItems(store.catalogItems);
  } catch (_) {
    if (box) box.innerHTML = "<div class='status-box'>Impossible de charger le catalogue.</div>";
  }
}

export async function searchMediaCatalog() {
  const qEl = document.getElementById("ms_query");
  const q = qEl ? qEl.value.trim() : "";
  if (!q) return loadMediaCatalog(store.currentFilter);
  store.isSearchMode = true;
  store.catalogExpanded = true;
  const panelEl = document.getElementById("media_action_panel");
  if (panelEl) panelEl.innerHTML = "";
  const box = document.getElementById("media_results");
  if (box) box.innerHTML = buildSkeletonPostersHtml(4);
  try {
    store.catalogItems = await api.getCatalog("all", q);
    renderMediaItems(store.catalogItems);
  } catch (_) {
    if (box) box.innerHTML = "<div class='status-box'>Erreur lors de la recherche.</div>";
  }
}

export function renderMediaItems(items) {
  const box = document.getElementById("media_results");
  const toggleBtn = document.getElementById("toggle_cat_view_btn");
  const prevBtn = document.getElementById("carousel_prev_btn");
  const nextBtn = document.getElementById("carousel_next_btn");
  if (!box) return;

  if (!items || !items.length) {
    box.innerHTML = "<div class='status-box'>Aucun résultat trouvé pour cette recherche.</div>";
    if (toggleBtn) toggleBtn.style.display = "none";
    if (prevBtn) prevBtn.style.display = "none";
    if (nextBtn) nextBtn.style.display = "none";
    return;
  }

  const isCarousel = !store.catalogExpanded && !store.isSearchMode;
  if (prevBtn) prevBtn.style.display = isCarousel ? "inline-flex" : "none";
  if (nextBtn) nextBtn.style.display = isCarousel ? "inline-flex" : "none";

  if (toggleBtn) {
    toggleBtn.style.display = "inline-flex";
    toggleBtn.textContent = store.catalogExpanded
      ? "🎠 Vue carrousel"
      : `📐 Tout voir (${items.length})`;
  }

  if (isCarousel) {
    box.innerHTML =
      `<div class="poster-strip">` +
      items
        .map((it, idx) => {
          const typeLabel =
            it.media_type === "anime"
              ? "🎌 Animé"
              : it.media_type === "movie"
              ? "🍿 Film"
              : "📺 Série";
          const langLabel = "VF / VOSTFR";
          const platformLabel = it.badge
            ? `${it.badge}${it.year && it.year !== "VF/VOSTFR" ? " • " + it.year : ""}`
            : it.year || "Catalogue HD";
          const clickCall = `openMediaPanelByIndex(${idx})`;
          return `
          <div class="poster-card" role="button" tabindex="0" onclick="${clickCall}" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${clickCall}}">
            <div class="poster-img-wrap">
              <img src="${it.image || ""}" alt="${escHtml(it.title)}" width="176" height="256" loading="lazy" onerror="this.style.opacity='0.2'">
              <div class="poster-overlay-badges">
                <span class="poster-pill">${escHtml(typeLabel)}</span>
                <span class="poster-pill">${escHtml(langLabel)}</span>
              </div>
              <div class="poster-hover-cta">
                <span class="btn btn-primary btn-sm">+ Ajouter</span>
              </div>
            </div>
            <div class="poster-card-body">
              <div class="poster-card-title" title="${escJs(it.title)}">${escHtml(it.title)}</div>
              <div class="poster-card-platform" title="${escJs(platformLabel)}">${escHtml(platformLabel)}</div>
            </div>
          </div>`;
        })
        .join("") +
      `</div>`;
    return;
  }

  box.innerHTML =
    `<div class="poster-grid-expanded">` +
    items
      .map((it, idx) => {
        const typeLabel =
          it.media_type === "anime"
            ? "🎌 Animé"
            : it.media_type === "movie"
            ? "🍿 Film"
            : "📺 Série";
        return `
        <div class="res-item">
          <img src="${it.image || ""}" alt="${escHtml(it.title)}" width="72" height="104" loading="lazy" onerror="this.style.opacity='0.2'">
          <div class="res-info">
            <b title="${escJs(it.title)}">${escHtml(it.title)} <span style="color:var(--text-secondary);font-weight:400">(${escHtml(it.year)})</span></b>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin:4px 0">
              <span class="badge badge-neutral">${escHtml(typeLabel)}</span>
              <span class="badge badge-neutral">${escHtml(it.badge || "VF / VOSTFR")}</span>
            </div>
            <div class="synopsis">${escHtml(it.synopsis || "")}</div>
          </div>
          <button type="button" class="btn-primary btn-sm" onclick="openMediaPanelByIndex(${idx})">
            + Ajouter
          </button>
        </div>`;
      })
      .join("") +
    `</div>`;
}

export function openMediaPanelByIndex(idx) {
  const it = (store.catalogItems || [])[idx];
  if (!it) return;
  openMediaPanel(
    it.id || "",
    it.media_type || "movie",
    it.title || "Média",
    it.year || "",
    it.imdb_id || "",
    it.url || "",
    it.synopsis || "",
    true
  );
}

function buildLangPillBarHtml() {
  const cur = store.selectedMediaLang;
  return `
    <div class="lang-pill-bar">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span style="font-size:var(--text-xs);font-weight:700;color:var(--text-secondary)">🌐 Langue :</span>
        <div class="lang-pill-group">
          <button type="button" class="lang-pill ${cur === "vf" ? "active" : ""}" id="lpill_vf" onclick="selectMediaLang('vf')">🇫🇷 VF</button>
          <button type="button" class="lang-pill ${cur === "vostfr" ? "active" : ""}" id="lpill_vostfr" onclick="selectMediaLang('vostfr')">🇯🇵 VOSTFR</button>
          <button type="button" class="lang-pill ${cur === "vo" ? "active" : ""}" id="lpill_vo" onclick="selectMediaLang('vo')">🇬🇧 VO</button>
        </div>
      </div>
      <span id="lang_fallback_badge" class="badge badge-warning" style="display:none"></span>
    </div>`;
}

export function selectMediaLang(lang) {
  store.selectedMediaLang = lang;
  ["vf", "vostfr", "vo"].forEach((k) => {
    const el = document.getElementById("lpill_" + k);
    if (el) el.classList.toggle("active", k === lang);
  });
  const ctx = store.currentPanelCtx;
  if (!ctx) return;
  if (ctx.mediaType === "anime") {
    renderAnimeSeasonsByLang();
  } else if (ctx.mediaType === "movie") {
    const btn = document.getElementById("movie_dl_btn_main");
    if (btn) btn.innerHTML = `📥 Télécharger le Film en ${lang.toUpperCase()} (Jellyfin)`;
  } else if (ctx.mediaType === "series") {
    renderSeriesSeasonEps(ctx.title, ctx.year, ctx.imdbId);
  }
}

export function renderAnimeSeasonsByLang() {
  const listBox = document.getElementById("anime_seasons_list_box");
  const fbBadge = document.getElementById("lang_fallback_badge");
  const epSub = document.getElementById("anime_ep_subpanel");
  if (epSub) epSub.innerHTML = "";
  if (!listBox) return;

  const seasons = store.currentAnimeSeasons || [];
  if (!seasons.length) {
    listBox.innerHTML = `<div class="sub">Aucune saison détectée.</div>`;
    return;
  }

  let matching = seasons.filter((s) => (s.lang || "").toLowerCase() === store.selectedMediaLang);
  let effectiveLang = store.selectedMediaLang;
  if (!matching.length) {
    const fallbackOrder = ["vostfr", "vf", "vo"];
    for (const cand of fallbackOrder) {
      const found = seasons.filter((s) => (s.lang || "").toLowerCase() === cand);
      if (found.length) {
        matching = found;
        effectiveLang = cand;
        break;
      }
    }
    if (fbBadge) {
      fbBadge.style.display = "inline-flex";
      fbBadge.textContent = `⚠️ Indisponible en ${store.selectedMediaLang.toUpperCase()} — bascule auto ${effectiveLang.toUpperCase()}`;
    }
  } else if (fbBadge) {
    fbBadge.style.display = "none";
  }

  const title = store.currentPanelCtx ? store.currentPanelCtx.title : "Animé";
  listBox.innerHTML = matching
    .map(
      (s) => `
      <div class="season-btn">
        <div><b>${escHtml(s.name)}</b> <span class="badge badge-anime">${escHtml(s.lang.toUpperCase())}</span></div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn-green btn-sm" onclick="startEpDl('${escJs(title)}', '${escJs(s.name)} (${s.lang.toUpperCase()})', '${escJs(s.js_url)}', 1, 1, this)">📥 Lancer Ép. 1</button>
          <button type="button" class="btn-primary btn-sm" onclick="openAnimeSeasonEpisodes('${escJs(title)}', '${escJs(s.name)} (${s.lang.toUpperCase()})', '${escJs(s.js_url)}')">🎞️ Choisir épisodes</button>
        </div>
      </div>`
    )
    .join("");

  if (matching.length > 0) {
    const first = matching[0];
    openAnimeSeasonEpisodes(title, `${first.name} (${first.lang.toUpperCase()})`, first.js_url);
  }
}

export async function openMediaPanel(id, mediaType, title, year, imdbId, animeUrl, synopsis, autoStartMovie = false) {
  const panel = document.getElementById("media_action_panel");
  if (!panel) return;
  store.currentPanelCtx = { id, mediaType, title, year, imdbId, animeUrl, synopsis };

  if (mediaType === "anime") {
    const targetUrl = animeUrl || id.replace(/^anime:/, "");
    panel.innerHTML = "<div class='season-box'>⏳ Analyse des saisons VF / VOSTFR / VO...</div>";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const data = await api.getAnimeSeasons(targetUrl);
    store.currentAnimeSeasons = data.seasons || [];
    panel.innerHTML = `
      <div class="season-box" style="border-color:#f472b6">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b style="color:#f472b6">🎌 ${escHtml(title)}</b>
          <button type="button" class="btn-ghost btn-sm" onclick="document.getElementById('media_action_panel').innerHTML=''">✖️ Fermer</button>
        </div>
        ${buildLangPillBarHtml()}
        <div id="anime_seasons_list_box"></div>
        <div id="anime_ep_subpanel"></div>
      </div>`;
    renderAnimeSeasonsByLang();
    return;
  }

  if (mediaType === "movie") {
    panel.innerHTML = `
      <div class="season-box" style="border-color:#10b981">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <b style="color:#10b981">🍿 ${escHtml(title)} (${escHtml(year)})</b>
          <button type="button" class="btn-ghost btn-sm" onclick="document.getElementById('media_action_panel').innerHTML=''">✖️ Fermer</button>
        </div>
        <p class="sub" style="margin-top:6px">${escHtml(synopsis || "")}</p>
        ${buildLangPillBarHtml()}
        <input type="text" id="custom_media_url" placeholder="Optionnel : Lien direct hébergeur (uqload, vidmoly, voe, mp4, m3u8)..." style="margin-bottom:8px">
        <button type="button" id="movie_dl_btn_main" class="btn-green btn-block" onclick="triggerMediaDownload('movie', '${escJs(title)}', '${escJs(year)}', 1, 1, 1, '${escJs(imdbId)}', this)">📥 Télécharger le Film en ${store.selectedMediaLang.toUpperCase()} (Jellyfin)</button>
      </div>`;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (autoStartMovie) {
      triggerMediaDownload("movie", title, year, 1, 1, 1, imdbId, document.getElementById("movie_dl_btn_main"));
    }
    return;
  }

  panel.innerHTML = "<div class='season-box'>⏳ Chargement des saisons et épisodes...</div>";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const data = await api.getSeriesEpisodes(id, title);
  store.currentSeriesSeasons = data.seasons || [];
  const sOpts = store.currentSeriesSeasons
    .map((s) => `<option value="${s.season}">Saison ${String(s.season).padStart(2, "0")} (${s.count} ép.)</option>`)
    .join("");

  panel.innerHTML = `
    <div class="season-box">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <b>📺 ${escHtml(title)} (${escHtml(year)})</b>
        <button type="button" class="btn-ghost btn-sm" onclick="document.getElementById('media_action_panel').innerHTML=''">✖️ Fermer</button>
      </div>
      <p class="sub" style="margin-top:6px">${escHtml(synopsis || "")}</p>
      ${buildLangPillBarHtml()}
      <select id="series_season_sel" onchange="renderSeriesSeasonEps('${escJs(title)}', '${escJs(year)}', '${escJs(imdbId)}')" style="margin-bottom:8px">${sOpts}</select>
      <input type="text" id="custom_media_url" placeholder="Optionnel : Lien direct hébergeur (uqload, vidmoly, voe, m3u8)...">
      <div id="series_eps_box"></div>
    </div>`;
  renderSeriesSeasonEps(title, year, imdbId);
}

export async function openAnimeSeasonEpisodes(animeTitle, seasonLabel, jsUrl) {
  const epPanel = document.getElementById("anime_ep_subpanel");
  if (!epPanel) return;
  epPanel.innerHTML = "<div class='sub' style='margin-top:8px'>⏳ Lecture des épisodes...</div>";
  const data = await api.getSeasonInfo(jsUrl);
  if (!data.count) {
    epPanel.innerHTML = "<div class='sub'>Aucun épisode trouvé.</div>";
    return;
  }
  let btns = "";
  for (let i = 1; i <= data.count; i++) {
    btns += `<button type="button" class="btn-green btn-sm" onclick="startEpDl('${escJs(animeTitle)}', '${escJs(seasonLabel)}', '${escJs(jsUrl)}', ${i}, ${i}, this)">📥 Ép ${i}</button>`;
  }
  epPanel.innerHTML = `
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border-subtle)">
      <b>🎬 ${escHtml(animeTitle)} — ${escHtml(seasonLabel)} (${data.count} ép.)</b>
      <div class="ep-grid">${btns}</div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px">
        <span style="font-size:var(--text-xs)">De</span>
        <input type="number" id="ep_start" value="1" min="1" max="${data.count}" style="width:72px">
        <span style="font-size:var(--text-xs)">à</span>
        <input type="number" id="ep_end" value="${data.count}" min="1" max="${data.count}" style="width:72px">
        <button type="button" class="btn-primary btn-sm" onclick="startRangeDl('${escJs(animeTitle)}', '${escJs(seasonLabel)}', '${escJs(jsUrl)}', this)">📥 Tout télécharger</button>
      </div>
    </div>`;
}

export function renderSeriesSeasonEps(title, year, imdbId) {
  const selEl = document.getElementById("series_season_sel");
  if (!selEl) return;
  const sNum = parseInt(selEl.value || "1", 10);
  const sObj = (store.currentSeriesSeasons || []).find((x) => x.season === sNum) || { season: sNum, count: 10 };
  const count = sObj.count || 10;
  const langTag = store.selectedMediaLang.toUpperCase();
  let btns = "";
  for (let i = 1; i <= count; i++) {
    const epTag = `S${String(sNum).padStart(2, "0")}E${String(i).padStart(2, "0")}`;
    btns += `<button type="button" class="btn-green btn-sm" onclick="triggerMediaDownload('series', '${escJs(title)}', '${escJs(year)}', ${sNum}, ${i}, ${i}, '${escJs(imdbId)}', this)">📥 ${epTag}</button>`;
  }
  const box = document.getElementById("series_eps_box");
  if (box) {
    box.innerHTML = `
      <div class="ep-grid">${btns}</div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px">
        <span style="font-size:var(--text-xs)">Ép.</span>
        <input type="number" id="ser_ep_start" value="1" min="1" max="${count}" style="width:72px">
        <span style="font-size:var(--text-xs)">à</span>
        <input type="number" id="ser_ep_end" value="${count}" min="1" max="${count}" style="width:72px">
        <button type="button" class="btn-primary btn-sm" onclick="triggerMediaRangeDownload('${escJs(title)}', '${escJs(year)}', ${sNum}, '${escJs(imdbId)}', this)">📥 Télécharger en ${langTag}</button>
      </div>`;
  }
}

export async function triggerMediaDownload(mediaType, title, year, season, startEp, endEp, imdbId, btnEl) {
  const langTag = (store.selectedMediaLang || "vf").toUpperCase();
  const label = mediaType === "movie" ? `🍿 ${title} (${langTag})` : `📺 ${title} S${season} (${langTag})`;
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(label);
  const customUrlEl = document.getElementById("custom_media_url");
  await api.downloadMedia({
    media_type: mediaType,
    title,
    year,
    season,
    start_ep: startEp,
    end_ep: endEp,
    imdb_id: imdbId || "",
    custom_url: customUrlEl ? customUrlEl.value.trim() : "",
    lang: store.selectedMediaLang || "vf",
  });
  updateStatus();
}

export function triggerMediaRangeDownload(title, year, season, imdbId, btnEl) {
  const s = document.getElementById("ser_ep_start")?.value || 1;
  const e = document.getElementById("ser_ep_end")?.value || 1;
  triggerMediaDownload("series", title, year, season, s, e, imdbId, btnEl);
}

export async function startEpDl(title, season, jsUrl, startEp, endEp, btnEl) {
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(`🎬 ${title} - ${season} (Ép ${startEp} à ${endEp})`);
  await api.downloadAnimeSeason({ title, season, js_url: jsUrl, start_ep: startEp, end_ep: endEp });
  updateStatus();
}

export function startRangeDl(title, season, jsUrl, btnEl) {
  const s = document.getElementById("ep_start")?.value || 1;
  const e = document.getElementById("ep_end")?.value || 12;
  startEpDl(title, season, jsUrl, s, e, btnEl);
}

export function renderStreamHealerBar(sh) {
  if (!sh) return;
  const txtEl = document.getElementById("healer_txt");
  const pillsEl = document.getElementById("healer_domains_pills");
  const keys = sh.sources ? Object.keys(sh.sources) : [];
  const totalCount = keys.length || 5;
  const okCount = keys.filter((k) => sh.sources[k]?.status !== "down").length || totalCount;

  if (txtEl) {
    txtEl.textContent = `Catalogue opérationnel — ${okCount} sources sur ${totalCount} actives`;
  }
  if (pillsEl && sh.sources) {
    pillsEl.innerHTML = keys
      .map((k) => {
        const s = sh.sources[k];
        const host = (s.active_domain || "").replace(/^https?:\/\//, "");
        return `<span class="badge badge-neutral" title="Source : ${escJs(s.label || k)}">✔ ${escHtml(s.label || k)} (${escHtml(host)})</span>`;
      })
      .join("");
  }
}

export async function runStreamHealerNow(btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳ Vérification en cours...";
  }
  try {
    const d = await api.runStreamHealer();
    renderStreamHealerBar(d);
    showToast("✅ Sources vidéo vérifiées et à jour !", "success");
  } catch (_) {
    showToast("Impossible de vérifier les sources vidéo.", "error");
  } finally {
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.textContent = "🛠️ Vérifier les sources vidéo";
    }
  }
}
