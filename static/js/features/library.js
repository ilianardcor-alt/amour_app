/**
 * FEATURE / LIBRARY — Gestion de la bibliothèque locale, état vide illustré (Point 10) et suppression sécurisée
 */
import { api } from "../core/api.js?v=6";
import { store } from "../core/state.js?v=6";
import { escJs, escHtml } from "../core/utils.js?v=6";
import { confirmAction, showToast } from "../ui/feedback.js?v=6";
import { updateStatus } from "./status.js?v=6";

export function setFilesFilter(cat) {
  store.currentFilesFilter = cat;
  ["all", "animes", "series", "films", "musique"].forEach((k) => {
    const el = document.getElementById("fcat_" + k);
    if (el) {
      const isAct = k === cat;
      el.classList.toggle("active", isAct);
      el.setAttribute("aria-selected", isAct ? "true" : "false");
    }
  });
  renderFileGroups();
}

export function toggleFolderAcc(folderPath) {
  store.openAccordions[folderPath] = !store.openAccordions[folderPath];
  renderFileGroups();
}

export async function loadFiles() {
  try {
    const data = await api.getFiles();
    store.allFileGroups = data.groups || [];
    renderFileGroups();
  } catch (_) {}
}

export function renderFileGroups() {
  const box = document.getElementById("files_list");
  if (!box) return;

  const filtered = store.allFileGroups.filter(
    (g) => store.currentFilesFilter === "all" || g.category === store.currentFilesFilter
  );

  // Point 10 : État vide avec icône, phrase courte et bouton qui renvoie vers « Ajouter du contenu »
  if (!filtered.length) {
    const targetSec = store.currentFilesFilter === "musique" ? "#sec_music" : "#sec_catalog";
    box.innerHTML = `
      <div class="empty-state-box">
        <div class="empty-state-icon" aria-hidden="true">📂</div>
        <div>
          <b style="display:block;font-size:var(--text-base);color:var(--text-primary);margin-bottom:4px">Aucun média dans cette catégorie</b>
          <p class="sub" style="margin:0">Vos films, séries, animés et musiques téléchargés apparaîtront automatiquement ici.</p>
        </div>
        <a href="${targetSec}" class="btn btn-primary btn-sm" style="text-decoration:none">+ Ajouter du contenu</a>
      </div>`;
    return;
  }

  box.innerHTML = filtered
    .map((g) => {
      const isOpen = !!store.openAccordions[g.folder_path];
      const filesHtml = g.files
        .map(
          (f) => `
          <div class="ep-row">
            <div style="flex:1;min-width:0;padding-right:8px">
              <b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">🎬 ${escHtml(f.name)}</b>
              <span style="font-size:var(--text-xs);color:var(--text-secondary)">${f.subfolder ? escHtml(f.subfolder) + " • " : ""}${f.size_mb} Mo</span>
            </div>
            <div style="display:flex;gap:8px;flex-shrink:0">
              <a href="/stream?path=${encodeURIComponent(f.path)}" target="_blank" class="btn btn-secondary btn-sm">▶️ Lire</a>
              <button type="button" class="btn-danger btn-sm" onclick="deleteFile('${escJs(f.path)}', false, '${escJs(f.name)}')">🗑️ Supprimer</button>
            </div>
          </div>`
        )
        .join("");

      return `
        <div class="folder-acc ${isOpen ? "open" : ""}">
          <div class="folder-acc-head" onclick="toggleFolderAcc('${escJs(g.folder_path)}')" role="button" tabindex="0" aria-expanded="${isOpen}">
            <div style="flex:1;min-width:0">
              <b style="font-size:var(--text-base)">${isOpen ? "📂" : "📁"} ${escHtml(g.title)}</b>
              <span class="badge badge-neutral" style="margin-left:8px">${escHtml(g.category_label)} • ${g.count} fichier(s) • ${g.total_mb} Mo</span>
            </div>
            <div style="display:flex;gap:8px;align-items:center" onclick="event.stopPropagation()">
              <button type="button" class="btn-danger btn-sm" onclick="deleteFile('${escJs(g.folder_path)}', true, '${escJs(g.title)} (${g.count} fichiers)')">🗑️ Tout supprimer</button>
            </div>
          </div>
          <div class="folder-acc-body">${filesHtml}</div>
        </div>`;
    })
    .join("");
}

export async function deleteFile(path, isFolder, displayLabel = "") {
  const itemName = displayLabel || path.split(/[\\/]/).pop() || path;
  const ok = await confirmAction({
    title: isFolder ? "Supprimer ce dossier complet ?" : "Supprimer ce fichier ?",
    message: isFolder
      ? `Le dossier « ${itemName} » et tous ses épisodes seront définitivement supprimés du serveur.`
      : `Le fichier « ${itemName} » sera définitivement supprimé du serveur.`,
    confirmLabel: isFolder ? "🗑️ Tout supprimer" : "🗑️ Supprimer",
    cancelLabel: "Annuler",
    danger: true,
  });
  if (!ok) return;

  await api.deleteFile(path);
  showToast(`🗑️ « ${itemName} » supprimé.`, "info");
  loadFiles();
  updateStatus();
}
