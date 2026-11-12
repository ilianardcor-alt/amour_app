/**
 * FEATURE / ADMIN — Outils avancés (Console PowerShell, Éditeur de code, Sauvegardes)
 */
import { api } from "../core/api.js?v=8";
import { store } from "../core/state.js?v=8";
import { escJs, escHtml } from "../core/utils.js?v=8";
import { confirmAction, showToast } from "../ui/feedback.js?v=8";
import { updateStatus } from "./status.js?v=8";

export function switchStudioTab(tab) {
  ["term", "ide", "bk", "ag", "mac"].forEach((t) => {
    const btn = document.getElementById("stab_" + t);
    const pan = document.getElementById("spanel_" + t);
    if (btn) btn.classList.toggle("active", t === tab);
    if (pan) pan.style.display = t === tab ? "block" : "none";
  });
  const ed = document.getElementById("code_editor");
  if (tab === "ide" && ed && !ed.value) {
    loadCodeFile();
  } else if (tab === "bk") {
    loadBackupsList();
  }
}

export async function loadCodeFile() {
  const sel = document.getElementById("ide_file_sel");
  const st = document.getElementById("ide_status");
  if (!sel || !st) return;
  const f = sel.value;
  st.textContent = `Chargement de ${f}...`;
  try {
    const d = await api.readCode(f);
    if (d.ok) {
      document.getElementById("code_editor").value = d.content;
      st.textContent = `Fichier chargé : ${d.file}`;
    } else {
      st.textContent = d.error || "Erreur de lecture.";
    }
  } catch (_) {
    st.textContent = "Impossible de lire le fichier.";
  }
}

export async function saveCodeFile() {
  const f = document.getElementById("ide_file_sel")?.value;
  const content = document.getElementById("code_editor")?.value || "";
  const st = document.getElementById("ide_status");
  if (!f || !st) return;
  st.textContent = "Vérification et sauvegarde en cours...";
  try {
    const d = await api.saveCode(f, content);
    if (d.ok) {
      st.textContent = `Enregistré avec succès (sauvegarde créée : ${d.snapshot})`;
      showToast(`Fichier ${f} enregistré.`, "success");
      if (f === "index.html") {
        const reload = await confirmAction({
          title: "Recharger l'interface ?",
          message: "Le fichier index.html a été modifié. Voulez-vous recharger la page pour appliquer les changements ?",
          confirmLabel: "Recharger la page",
          cancelLabel: "Plus tard",
          danger: false,
        });
        if (reload) window.location.reload();
      }
    } else {
      st.textContent = `Erreur : ${d.error}`;
      showToast(d.error || "Sauvegarde refusée.", "error");
    }
  } catch (_) {
    st.textContent = "Erreur réseau lors de l'enregistrement.";
  }
}

export async function loadBackupsList() {
  const box = document.getElementById("backups_list_box");
  if (!box) return;
  try {
    const d = await api.listBackups();
    if (!d.backups || !d.backups.length) {
      box.innerHTML = "<div class='sub'>Aucune sauvegarde disponible.</div>";
      return;
    }
    box.innerHTML = d.backups
      .map(
        (b) => `
        <div class="ep-row">
          <div>
            <b>${escHtml(b.name)}</b><br>
            <span style="font-size:var(--text-xs);color:var(--text-secondary)">${b.files_count} fichiers • ${b.size_kb} Ko</span>
          </div>
          <button type="button" class="btn-secondary btn-sm" onclick="restoreBackup('${escJs(b.name)}')">Restaurer cette version</button>
        </div>`
      )
      .join("");
  } catch (_) {}
}

export async function createBackupNow() {
  const inp = document.getElementById("bk_label");
  const lbl = (inp ? inp.value.trim() : "") || "manuel";
  await api.createBackup(lbl);
  if (inp) inp.value = "";
  showToast(`Sauvegarde « ${lbl} » créée.`, "success");
  loadBackupsList();
}

export async function restoreBackup(name) {
  const ok = await confirmAction({
    title: "Restaurer cette sauvegarde ?",
    message: `Voulez-vous restaurer la version « ${name} » ? Une sauvegarde de l'état actuel sera créée automatiquement avant l'opération.`,
    confirmLabel: "Restaurer la version",
    cancelLabel: "Annuler",
    danger: true,
  });
  if (!ok) return;
  const d = await api.restoreBackup(name);
  if (d.ok) {
    showToast("Restauration terminée. Rechargement...", "success");
    setTimeout(() => window.location.reload(), 900);
  }
}

export function appendTerminalEntry(promptStr, cmdStr, outStr) {
  const body = document.getElementById("term_body");
  if (!body) return;
  const block = document.createElement("div");
  block.style.marginTop = "6px";
  const echoLine = document.createElement("div");
  echoLine.innerHTML = `<span style="color:#34d399;font-weight:700">${escHtml(promptStr)}</span> <span style="color:#60a5fa;font-weight:700">${escHtml(cmdStr)}</span>`;
  block.appendChild(echoLine);
  if (outStr) {
    const outDiv = document.createElement("div");
    outDiv.textContent = outStr;
    block.appendChild(outDiv);
  }
  body.appendChild(block);
  body.scrollTop = body.scrollHeight;
}

export async function execTerminalCmd(cmdStr) {
  const c = (cmdStr || "").trim();
  if (!c) return;
  if (c.toLowerCase() === "cls" || c.toLowerCase() === "clear") {
    clearTerminal();
    return;
  }
  store.termHistory.push(c);
  store.termHistIdx = store.termHistory.length;
  const promptEl = document.getElementById("term_prompt");
  const curPrompt = promptEl ? promptEl.textContent : "PS>";
  const inp = document.getElementById("term_input");
  if (inp) {
    inp.value = "";
    inp.disabled = true;
  }
  try {
    const d = await api.execCmd(c);
    appendTerminalEntry(curPrompt, c, d.output || "");
    if (d.prompt && promptEl) promptEl.textContent = d.prompt;
  } catch (e) {
    appendTerminalEntry(curPrompt, c, "Erreur de connexion : " + e);
  } finally {
    if (inp) {
      inp.disabled = false;
      inp.focus();
    }
  }
}

export function handleTermKey(e) {
  const inp = document.getElementById("term_input");
  if (!inp) return;
  if (e.key === "Enter") {
    e.preventDefault();
    execTerminalCmd(inp.value);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (store.termHistory.length > 0 && store.termHistIdx > 0) {
      store.termHistIdx--;
      inp.value = store.termHistory[store.termHistIdx];
    }
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    if (store.termHistIdx < store.termHistory.length - 1) {
      store.termHistIdx++;
      inp.value = store.termHistory[store.termHistIdx];
    } else {
      store.termHistIdx = store.termHistory.length;
      inp.value = "";
    }
  }
}

export function clearTerminal() {
  const b = document.getElementById("term_body");
  if (b) b.innerHTML = "Console effacée.";
}

export function quickTermPorts() {
  execTerminalCmd("netstat -ano | Select-String 'LISTENING' | Select-String ':(22|8022|5000|8096|4533|8080|8053)\\s' | Out-String");
}

export function quickTermLinks() {
  execTerminalCmd("Write-Output \"Hostname : $(hostname)\"; Get-ChildItem logs\\cf_*.log -ErrorAction SilentlyContinue | ForEach-Object { $m = Select-String -Path $_.FullName -Pattern 'https://[a-zA-Z0-9-]+\\.trycloudflare\\.com' -AllMatches; if ($m) { Write-Output \"$($_.Name) -> $($m.Matches[-1].Value)\" } }");
}

export async function restartServices() {
  const ok = await confirmAction({
    title: "Relancer les services du serveur ?",
    message: "Tous les services multimédias (Jellyfin, Navidrome, FileBrowser, AdGuard et le Hub) vont redémarrer. Les liens d'accès 4G/5G seront conservés.",
    confirmLabel: "Relancer le serveur",
    cancelLabel: "Annuler",
    danger: true,
  });
  if (!ok) return;
  appendTerminalEntry(
    document.getElementById("term_prompt")?.textContent || "PS>",
    "start_all.ps1",
    "Relance des services en cours..."
  );
  await api.restartAll();
  showToast("Relance des services démarrée.", "info");
  setTimeout(updateStatus, 8000);
}
