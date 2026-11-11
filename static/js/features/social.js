/**
 * FEATURE / SOCIAL — Téléchargement direct par lien (YouTube, TikTok, X / Twitter, Instagram)
 */
import { api } from "../core/api.js?v=6";
import { escJs, escHtml } from "../core/utils.js?v=6";
import { markBtnValidated, showToast, confirmAction } from "../ui/feedback.js?v=6";
import { updateStatus, notifyDownloadStarted } from "./status.js?v=6";
import { loadFiles } from "./library.js?v=6";

let currentSocialFormat = "mp4";

export function clearSocialUrlInput() {
  const inp = document.getElementById("social_dl_url");
  if (inp) {
    inp.value = "";
    inp.focus();
  }
}

export function selectSocialFormat(fmt) {
  currentSocialFormat = fmt === "mp3" ? "mp3" : "mp4";
  ["mp4", "mp3"].forEach((k) => {
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

export async function startSocialLinkDownload(btnEl) {
  const inp = document.getElementById("social_dl_url");
  const url = inp ? inp.value.trim() : "";
  if (!url || !/^https?:\/\//i.test(url)) {
    showToast("Veuillez coller un lien valide (commençant par https://).", "error");
    if (inp) inp.focus();
    return;
  }

  const plat = detectPlatformLabel(url);
  const fmtLabel = currentSocialFormat === "mp3" ? "MP3" : "MP4 HD";
  markBtnValidated(btnEl, "Lancé !");
  notifyDownloadStarted(`${plat} (${fmtLabel})`);

  try {
    const res = await api.downloadSocialLink(url, currentSocialFormat);
    if (res && res.ok) {
      if (inp) inp.value = "";
      updateStatus();
      setTimeout(loadSocialDownloads, 4000);
      setTimeout(loadSocialDownloads, 10000);
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
      box.innerHTML = `<div class="sub" style="padding:8px 0">Aucune vidéo téléchargée par lien pour le moment. Collez un lien YouTube, TikTok ou X ci-dessus pour tester.</div>`;
      return;
    }

    box.innerHTML = `
      <div style="margin-top:8px">
        <b style="font-size:var(--text-sm);color:var(--text-secondary);display:block;margin-bottom:8px">📂 Fichiers récupérés par lien (${files.length}) :</b>
        <div style="display:flex;flex-direction:column;gap:8px">
          ${files
            .map(
              (f) => `
            <div class="res-item" style="padding:10px 14px">
              <div class="res-info">
                <b title="${escJs(f.name)}">${f.ext === "mp3" ? "🎵" : "🎬"} ${escHtml(f.name)}</b>
                <div style="font-size:var(--text-xs);color:var(--text-secondary);margin-top:2px">
                  ${f.size_mb} Mo • ${escHtml(f.date || "")}
                </div>
              </div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <a href="/download_file?path=${encodeURIComponent(f.path)}" class="btn btn-primary btn-sm" download>⬇️ Enregistrer sur mon appareil</a>
                <a href="/stream?path=${encodeURIComponent(f.path)}" target="_blank" class="btn btn-secondary btn-sm">▶ Lire</a>
                <button type="button" class="btn-danger btn-sm" onclick="deleteSocialFile('${escJs(f.path)}', '${escJs(f.name)}')">🗑️</button>
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
