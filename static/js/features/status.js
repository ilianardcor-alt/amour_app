/**
 * FEATURE / STATUS — Stockage intelligent (Go/To), Zone Téléchargements cohérente et Dock flottant
 */
import { api } from "../core/api.js";
import { copyTextToClipboard } from "../core/utils.js";
import { confirmAction, showToast } from "../ui/feedback.js";
import { renderTailscaleStatus, renderRemoteLinksPanel } from "./remote.js";
import { renderStreamHealerBar } from "./catalog.js";

let dockDismissedForTitle = null;
let dockAutoHideTimer = null;

function formatDiskCapacity(gb) {
  const num = Number(gb) || 0;
  if (num >= 1000) {
    return `${(num / 1024).toFixed(1).replace(".", ",")} To`;
  }
  return `${Math.round(num)} Go`;
}

export function dismissFloatingDock() {
  const dock = document.getElementById("floating_dl_dock");
  const titleEl = document.getElementById("dock_dl_title");
  if (titleEl) {
    dockDismissedForTitle = titleEl.textContent;
  }
  if (dock) {
    dock.style.display = "none";
  }
}

export function notifyDownloadStarted(label = "Téléchargement en cours...") {
  dockDismissedForTitle = null;
  if (dockAutoHideTimer) {
    clearTimeout(dockAutoHideTimer);
    dockAutoHideTimer = null;
  }

  // Bascule immédiate de l'état vide vers la carte de progression active
  const emptyBox = document.getElementById("dl_empty_state");
  const activeCard = document.getElementById("dl_active_card");
  if (emptyBox) emptyBox.style.display = "none";
  if (activeCard) activeCard.style.display = "block";

  const dlState = document.getElementById("dl_state");
  if (dlState) {
    dlState.textContent = "⏳ Téléchargement en cours";
    dlState.className = "badge badge-warning";
  }
  const dlTitle = document.getElementById("dl_title");
  if (dlTitle) dlTitle.textContent = label;
  const dlStep = document.getElementById("dl_step");
  if (dlStep) dlStep.textContent = "⏳ Démarrage du téléchargement...";
  const dlBar = document.getElementById("dl_bar");
  if (dlBar) dlBar.style.width = "4%";
  const dlPct = document.getElementById("dl_pct");
  if (dlPct) dlPct.textContent = "0%";
  const dlSpeed = document.getElementById("dl_speed");
  if (dlSpeed) dlSpeed.textContent = "Démarrage...";

  // Affichage immédiat du dock flottant en bas de l'écran (visible sans scroller)
  const dock = document.getElementById("floating_dl_dock");
  if (dock) dock.style.display = "block";
  const dockTitle = document.getElementById("dock_dl_title");
  if (dockTitle) dockTitle.textContent = label;
  const dockStep = document.getElementById("dock_dl_step");
  if (dockStep) dockStep.textContent = "⏳ Démarrage du téléchargement...";
  const dockBadge = document.getElementById("dock_dl_badge");
  if (dockBadge) {
    dockBadge.textContent = "⏳ En cours";
    dockBadge.className = "badge badge-warning";
  }
  const dockBar = document.getElementById("dock_dl_bar");
  if (dockBar) dockBar.style.width = "4%";
  const dockPct = document.getElementById("dock_dl_pct");
  if (dockPct) dockPct.textContent = "0%";
  const dockSpeed = document.getElementById("dock_dl_speed");
  if (dockSpeed) dockSpeed.textContent = "Démarrage...";
  const spinner = document.getElementById("dock_spinner");
  if (spinner) spinner.style.display = "inline-block";

  showToast(`📥 Ajouté aux téléchargements : ${label}`, "success");
}

export async function copyLogs() {
  const el = document.getElementById("raw_logs");
  if (!el || !el.value) {
    showToast("Aucun journal à copier.", "info");
    return;
  }
  await copyTextToClipboard(el.value);
  showToast("📋 Journaux d'activité copiés !", "success");
}

export async function clearLogs() {
  await api.clearLogs();
  showToast("🧹 Journaux d'activité effacés.", "info");
  updateStatus();
}

export async function stopDownload() {
  const titleEl = document.getElementById("dl_title");
  const currentTask = titleEl ? titleEl.textContent : "le téléchargement en cours";

  const ok = await confirmAction({
    title: "Arrêter le téléchargement ?",
    message: `Voulez-vous vraiment interrompre « ${currentTask} » ?`,
    confirmLabel: "⏹️ Arrêter le téléchargement",
    cancelLabel: "Continuer",
    danger: true,
  });
  if (!ok) return;

  // Remise à zéro immédiate de l'interface vers l'état vide cohérent
  const emptyBox = document.getElementById("dl_empty_state");
  const activeCard = document.getElementById("dl_active_card");
  if (activeCard) activeCard.style.display = "none";
  if (emptyBox) emptyBox.style.display = "flex";

  const dlState = document.getElementById("dl_state");
  if (dlState) {
    dlState.textContent = "Aucun téléchargement";
    dlState.className = "badge badge-neutral";
  }
  const idleNote = document.getElementById("dl_idle_note");
  if (idleNote) {
    idleNote.textContent = "⏹️ Dernier téléchargement arrêté. Choisissez un média ci-dessous pour en lancer un nouveau.";
  }

  const dock = document.getElementById("floating_dl_dock");
  if (dock) {
    dock.style.display = "none";
  }

  try {
    await api.stopDownload();
  } catch (_) {}
  showToast("⏹️ Téléchargement arrêté.", "info");
  await updateStatus();
}

export async function updateStatus() {
  try {
    const st = await api.getStatus();
    window.JF_URL = st.jf_url;
    window.ND_URL = st.nd_url;
    window.FB_URL = st.fb_url;
    window.AG_PORT = st.ag_port;

    // 1. Stockage (Point 11 : "238 Go libres sur 1,8 To" en grand, détail affiché uniquement si > 0 Mo)
    const diskTxt = document.getElementById("disk_txt");
    if (diskTxt) {
      const freeStr = `${Math.round(Number(st.disk_free) || 0)} Go`;
      const totalStr = formatDiskCapacity(st.disk_total);
      diskTxt.textContent = `${freeStr} libres sur ${totalStr}`;
    }
    const diskBar = document.getElementById("disk_bar");
    if (diskBar) {
      diskBar.style.width = `${st.disk_pct || 0}%`;
    }
    const diskDetails = document.getElementById("disk_details");
    if (diskDetails) {
      const catParts = [];
      if (Number(st.music_mb) > 0) catParts.push(`<span>🎵 Musique : <b>${st.music_mb} Mo</b></span>`);
      if (Number(st.films_mb) > 0) catParts.push(`<span>🍿 Films : <b>${st.films_mb} Mo</b></span>`);
      if (Number(st.series_mb) > 0) catParts.push(`<span>📺 Séries : <b>${st.series_mb} Mo</b></span>`);
      if (Number(st.anime_mb) > 0) catParts.push(`<span>🎬 Animés : <b>${st.anime_mb} Mo</b></span>`);

      if (catParts.length > 0) {
        diskDetails.innerHTML = catParts.join("");
        diskDetails.style.display = "flex";
      } else {
        diskDetails.innerHTML = "";
        diskDetails.style.display = "none";
      }
    }

    renderRemoteLinksPanel(st);
    renderTailscaleStatus(st.tailscale);
    renderStreamHealerBar(st.stream_healer);

    const mainIp = (st.ips || "192.168.1.33").split(",")[0].trim();
    const macSsh = document.getElementById("mac_ssh_cmd");
    if (macSsh && mainIp) {
      if (macSsh.tagName === "INPUT") {
        macSsh.value = `ssh hpigr@${mainIp}`;
      } else {
        macSsh.textContent = `ssh hpigr@${mainIp}`;
      }
    }

    // 2. Zone Téléchargements cohérente (Point 5 : État vide OU Carte de progression)
    const qTxt = st.queue_count > 0 ? ` (+${st.queue_count} en attente)` : "";
    const emptyBox = document.getElementById("dl_empty_state");
    const activeCard = document.getElementById("dl_active_card");
    const dlState = document.getElementById("dl_state");

    if (st.active) {
      if (emptyBox) emptyBox.style.display = "none";
      if (activeCard) activeCard.style.display = "block";
      if (dlState) {
        dlState.textContent = `⏳ En cours${qTxt}`;
        dlState.className = "badge badge-warning";
      }
      const dlTitle = document.getElementById("dl_title");
      if (dlTitle) dlTitle.textContent = st.title || "Téléchargement en cours";
      const dlStep = document.getElementById("dl_step");
      if (dlStep) dlStep.textContent = st.step || "Téléchargement...";
      const dlBar = document.getElementById("dl_bar");
      if (dlBar) dlBar.style.width = `${st.percent || 0}%`;
      const dlPct = document.getElementById("dl_pct");
      if (dlPct) dlPct.textContent = `${st.percent || 0}%`;
      const dlSpeed = document.getElementById("dl_speed");
      if (dlSpeed) dlSpeed.textContent = st.speed || "-";
    } else {
      if (activeCard) activeCard.style.display = "none";
      if (emptyBox) emptyBox.style.display = "flex";
      if (dlState) {
        dlState.textContent = "Aucun téléchargement";
        dlState.className = "badge badge-neutral";
      }
    }

    // 3. Synchronisation du Dock Flottant
    const dock = document.getElementById("floating_dl_dock");
    if (dock) {
      if (st.active) {
        if (dockAutoHideTimer) {
          clearTimeout(dockAutoHideTimer);
          dockAutoHideTimer = null;
        }
        if (dockDismissedForTitle !== st.title) {
          dock.style.display = "block";
        }
        const dockTitle = document.getElementById("dock_dl_title");
        if (dockTitle) dockTitle.textContent = (st.title || "Téléchargement") + qTxt;
        const dockStep = document.getElementById("dock_dl_step");
        if (dockStep) dockStep.textContent = st.step || "Téléchargement en cours...";
        const dockBadge = document.getElementById("dock_dl_badge");
        if (dockBadge) {
          dockBadge.textContent = "⏳ En cours" + qTxt;
          dockBadge.className = "badge badge-warning";
        }
        const dockPct = document.getElementById("dock_dl_pct");
        if (dockPct) dockPct.textContent = `${st.percent || 0}%`;
        const dockSpeed = document.getElementById("dock_dl_speed");
        if (dockSpeed) dockSpeed.textContent = st.speed || "-";
        const dockBar = document.getElementById("dock_dl_bar");
        if (dockBar) dockBar.style.width = `${Math.max(4, st.percent || 0)}%`;
        const spinner = document.getElementById("dock_spinner");
        if (spinner) spinner.style.display = "inline-block";
      } else if (dock.style.display !== "none") {
        if ((st.step || "").includes("arrêté")) {
          dock.style.display = "none";
        } else {
          const dockBadge = document.getElementById("dock_dl_badge");
          if (dockBadge) {
            dockBadge.textContent = "✅ Terminé";
            dockBadge.className = "badge badge-success";
          }
          const dockStep = document.getElementById("dock_dl_step");
          if (dockStep) dockStep.textContent = st.step || "Terminé.";
          const dockPct = document.getElementById("dock_dl_pct");
          if (dockPct) dockPct.textContent = "100%";
          const dockBar = document.getElementById("dock_dl_bar");
          if (dockBar) dockBar.style.width = "100%";
          const spinner = document.getElementById("dock_spinner");
          if (spinner) spinner.style.display = "none";
          if (!dockAutoHideTimer) {
            dockAutoHideTimer = setTimeout(() => {
              dock.style.display = "none";
              dockAutoHideTimer = null;
            }, 3500);
          }
        }
      }
    }

    const termPrompt = document.getElementById("term_prompt");
    if (termPrompt && st.cwd) {
      termPrompt.textContent = `PS ${st.cwd}>`;
    }
    const logEl = document.getElementById("raw_logs");
    if (logEl && document.activeElement !== logEl) {
      logEl.value = st.logs || "";
      logEl.scrollTop = logEl.scrollHeight;
    }
  } catch (_) {}
}
