/**
 * FEATURE / SOCIAL — Téléchargement direct par lien (YouTube, TikTok, X / Twitter) avec choix de qualité (jusqu'à 4K / Max)
 */
import { api } from "../core/api.js?v=8";
import { escJs, escHtml } from "../core/utils.js?v=8";
import { markBtnValidated, showToast, confirmAction } from "../ui/feedback.js?v=8";
import { updateStatus, notifyDownloadStarted } from "./status.js?v=8";
import { loadFiles } from "./library.js?v=8";

let currentSocialFormat = "best";
let lastProbedUrl = "";

const ALL_QUALITY_KEYS = ["best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "mp3"];

export function clearSocialUrlInput() {
  const inp = document.getElementById("social_dl_url");
  if (inp) {
    inp.value = "";
    inp.focus();
  }
  lastProbedUrl = "";
  const probeBox = document.getElementById("social_probe_box");
  if (probeBox) probeBox.innerHTML = "";
}

export async function pasteSocialUrlFromClipboard() {
  const inp = document.getElementById("social_dl_url");
  if (!inp) return;
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      const txt = (await navigator.clipboard.readText()).trim();
      if (txt) {
        inp.value = txt;
        probeSocialLinkQualities(true);
        return;
      }
    }
  } catch (_) {}
  inp.focus();
  showToast("Maintenez appuyé dans le champ pour coller votre lien.", "info");
}

export function selectSocialFormat(fmt) {
  currentSocialFormat = fmt || "best";
  ALL_QUALITY_KEYS.forEach((k) => {
    const btn = document.getElementById("sfmt_" + k);
    if (btn) {
      const isAct = k === currentSocialFormat;
      btn.classList.toggle("active", isAct);
      btn.setAttribute("aria-selected", isAct ? "true" : "false");
    }
  });
}

function detectPlatformLabel(url) {
  const u = (url || "").toLowerCase();
  if (u.includes("tiktok.com")) return "🎵 TikTok";
  if (u.includes("twitter.com") || u.includes("x.com")) return "🐦 X / Twitter";
  if (u.includes("instagram.com")) return "📸 Instagram";
  if (u.includes("youtu.be") || u.includes("youtube.com")) return "▶️ YouTube";
  return "🔗 Lien Vidéo";
}

function formatQualityDisplayLabel(fmt) {
  if (!fmt || fmt === "best" || fmt === "mp4") return "Qualité Max";
  if (fmt === "mp3") return "Audio MP3 320k";
  if (fmt === "2160p") return "4K (2160p)";
  if (fmt === "1440p") return "2K (1440p)";
  return fmt.toUpperCase();
}

export async function probeSocialLinkQualities(manual = false) {
  const inp = document.getElementById("social_dl_url");
  const probeBox = document.getElementById("social_probe_box");
  const probeBtn = document.getElementById("social_probe_btn");
  const url = inp ? inp.value.trim() : "";
  if (!url || !/^https?:\/\//i.test(url)) {
    if (manual) {
      showToast("Collez d'abord un lien valide (https://...) pour voir les qualités.", "error");
      if (inp) inp.focus();
    }
    return;
  }
  if (!manual && url === lastProbedUrl) return;
  lastProbedUrl = url;

  if (probeBtn) {
    probeBtn.disabled = true;
    probeBtn.textContent = "⏳ Analyse...";
  }
  if (probeBox) {
    probeBox.innerHTML = `<div class="status-box" style="margin-bottom:var(--space-2)">⏳ Analyse des résolutions disponibles sur ce lien (4K, 1080p, 720p, MP3)...</div>`;
  }

  try {
    const d = await api.probeSocialFormats(url);
    if (!d || !d.ok) {
      if (probeBox) {
        probeBox.innerHTML = `<div class="status-box" style="margin-bottom:var(--space-2);color:var(--text-secondary)">ℹ️ Choisissez directement la qualité ci-dessus puis cliquez sur <b>📥 Télécharger</b>.</div>`;
      }
      return;
    }

    const quals = d.qualities || [];
    const qBtnsHtml = quals
      .map((q, idx) => {
        const isPrimary = idx === 0 || q.id === currentSocialFormat;
        return `<button type="button" class="${isPrimary ? "btn-primary" : "btn-secondary"} btn-sm" onclick="startSocialLinkDownloadWithQuality('${escJs(q.id)}', this)">
          📥 ${escHtml(q.label)}
        </button>`;
      })
      .join("");

    if (probeBox) {
      probeBox.innerHTML = `
        <div class="status-box social-probe-card" style="margin-bottom:var(--space-2);border-color:var(--border-focus)">
          <div class="social-probe-header">
            ${
              d.thumbnail
                ? `<img src="${escHtml(d.thumbnail)}" alt="" class="social-probe-thumb" onerror="this.style.display='none'">`
                : ""
            }
            <div class="social-probe-meta">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
                <span class="badge badge-success">✨ Max disponible : ${escHtml(d.max_label || "HD")}</span>
                ${d.duration ? `<span class="badge badge-neutral">⏱️ ${escHtml(d.duration)}</span>` : ""}
                ${d.uploader ? `<span class="badge badge-neutral">📺 ${escHtml(d.uploader)}</span>` : ""}
              </div>
              <b style="font-size:var(--text-base);display:block">${escHtml(d.title || "Vidéo détectée")}</b>
              <div style="font-size:var(--text-xs);color:var(--text-secondary);margin-top:4px">
                Cliquez sur la qualité souhaitée pour lancer le téléchargement immédiat :
              </div>
            </div>
          </div>
          <div class="social-probe-actions">
            ${qBtnsHtml}
          </div>
        </div>`;
    }
  } catch (_) {
    if (probeBox) probeBox.innerHTML = "";
  } finally {
    if (probeBtn) {
      probeBtn.disabled = false;
      probeBtn.textContent = "🔍 Qualités";
    }
  }
}

export async function startSocialLinkDownloadWithQuality(quality, btnEl) {
  selectSocialFormat(quality);
  await startSocialLinkDownload(btnEl, quality);
}

export async function startSocialLinkDownload(btnEl, forcedQuality = null) {
  const inp = document.getElementById("social_dl_url");
  const url = inp ? inp.value.trim() : "";
  if (!url || !/^https?:\/\//i.test(url)) {
    showToast("Veuillez coller un lien valide (commençant par https://).", "error");
    if (inp) inp.focus();
    return;
  }

  const chosenQ = forcedQuality || currentSocialFormat || "best";
  const plat = detectPlatformLabel(url);
  const fmtLabel = formatQualityDisplayLabel(chosenQ);
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(`${plat} (${fmtLabel})`);

  try {
    const res = await api.downloadSocialLink(url, chosenQ);
    if (res && res.ok) {
      if (inp) inp.value = "";
      lastProbedUrl = "";
      const probeBox = document.getElementById("social_probe_box");
      if (probeBox) probeBox.innerHTML = "";
      updateStatus();
      setTimeout(loadSocialDownloads, 4000);
      setTimeout(loadSocialDownloads, 9000);
      setTimeout(loadFiles, 10000);
    } else {
      showToast((res && res.error) || "Impossible de lancer ce lien.", "error");
    }
  } catch (_) {
    showToast("Erreur lors de l'envoi du lien au serveur.", "error");
  }
}

export async function loadSocialDownloads() {
  const box = document.getElementById("social_dl_results");
  if (!box) return;
  try {
    const data = await api.getSocialDownloads();
    const files = (data && data.files) || [];
    if (!files.length) {
      box.innerHTML = `<div class="sub" style="padding:8px 0">Aucune vidéo téléchargée par lien pour le moment. Collez un lien YouTube, TikTok ou X ci-dessus et choisissez la qualité souhaitée.</div>`;
      return;
    }

    box.innerHTML = `
      <div style="margin-top:8px">
        <b style="font-size:var(--text-sm);color:var(--text-secondary);display:block;margin-bottom:8px">📂 Fichiers récupérés par lien (${files.length}) :</b>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${files
            .map(
              (f) => `
            <div class="res-item social-file-item">
              <div class="res-info">
                <b title="${escJs(f.name)}">${f.ext === "mp3" ? "🎵" : "🎬"} ${escHtml(f.name)}</b>
                <div style="font-size:var(--text-xs);color:var(--text-secondary);margin-top:2px">
                  ${f.size_mb} Mo • ${escHtml(f.date || "")}
                </div>
              </div>
              <div class="social-file-actions">
                <a href="/download_file?path=${encodeURIComponent(f.path)}" class="btn btn-primary btn-sm" download>⬇️ Enregistrer sur mon appareil</a>
                <a href="/stream?path=${encodeURIComponent(f.path)}" target="_blank" class="btn btn-secondary btn-sm">▶ Lire</a>
                <button type="button" class="btn-danger btn-sm" onclick="deleteSocialFile('${escJs(f.path)}', '${escJs(f.name)}')" aria-label="Supprimer">🗑️</button>
              </div>
            </div>`
            )
            .join("")}
        </div>
      </div>`;
  } catch (_) {}
}

export async function deleteSocialFile(path, name) {
  const confirmed = await confirmAction({
    title: "Supprimer ce fichier ?",
    message: `Voulez-vous supprimer « ${name} » du serveur ?`,
    confirmLabel: "Supprimer",
    cancelLabel: "Annuler",
    danger: true,
  });
  if (!confirmed) return;
  await api.deleteFile(path);
  showToast(`🗑️ « ${name} » supprimé.`, "info");
  loadSocialDownloads();
  loadFiles();
}
