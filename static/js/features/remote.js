/**
 * FEATURE / REMOTE — 3 options d'accès à distance (« À la maison », « Hors de chez vous », « Accès permanent »)
 */
import { api } from "../core/api.js";
import { copyTextToClipboard, escJs, escHtml } from "../core/utils.js";
import { showToast } from "../ui/feedback.js";

export async function copyLinkWithFeedback(url, label = "Lien") {
  if (!url) {
    showToast("Ce lien n'est pas encore disponible.", "error");
    return;
  }
  await copyTextToClipboard(url);
  showToast(`✓ Lien copié (${label})`, "success");
}

export function renderRemoteLinksPanel(st) {
  const panel = document.getElementById("links_panel");
  if (!panel) return;

  const mainIp = (st.ips || "192.168.1.22").split(",")[0].trim();
  const localUrl = `http://${mainIp}:5000`;
  const mobileUrl = st.hub_url || "";
  const tsInfo = st.tailscale || {};
  const tsUrl = tsInfo.connected && tsInfo.ip ? `http://${tsInfo.ip}:5000` : "";

  const mobileBadge = mobileUrl
    ? `<span class="badge badge-success">🟢 Disponible</span>`
    : `<span class="badge badge-warning">⏳ Non démarré</span>`;

  const tsBadge = tsUrl
    ? `<span class="badge badge-success">🟢 Disponible</span>`
    : tsInfo.auth_url
    ? `<span class="badge badge-warning">⏳ En attente</span>`
    : `<span class="badge badge-neutral">⚪ Non configuré</span>`;

  panel.innerHTML = `
    <div class="remote-steps-grid">
      <!-- OPTION 1 : À LA MAISON -->
      <div class="remote-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
            <h3 style="font-size:var(--text-base)">🏠 À la maison</h3>
            <span class="badge badge-success">🟢 Disponible</span>
          </div>
          <p class="sub">Pour tous vos appareils connectés au même réseau Wi-Fi ou câble que le serveur.</p>
          <div class="copy-input-group" style="margin-bottom:12px">
            <label for="inp_remote_home" class="sr-only">Lien local à la maison</label>
            <input id="inp_remote_home" type="text" readonly value="${escHtml(localUrl)}" onclick="this.select()">
            <button type="button" class="btn-secondary btn-sm" onclick="copyLinkWithFeedback('${escJs(localUrl)}', 'À la maison')" aria-label="Copier le lien à la maison" title="Copier le lien">📋 Copier</button>
          </div>
        </div>
        <a href="${escHtml(localUrl)}/iliantify" class="btn btn-secondary btn-sm btn-block" style="text-decoration:none">🎧 Ouvrir IlianTify sur le réseau local</a>
      </div>

      <!-- OPTION 2 : HORS DE CHEZ VOUS -->
      <div class="remote-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
            <h3 style="font-size:var(--text-base)">🌍 Hors de chez vous</h3>
            ${mobileBadge}
          </div>
          <p class="sub">Lien 4G / 5G temporaire pour accéder à votre serveur en déplacement sans rien installer.</p>
          <div class="copy-input-group" style="margin-bottom:12px">
            <label for="inp_remote_4g" class="sr-only">Lien hors de chez vous 4G/5G</label>
            <input id="inp_remote_4g" type="text" readonly value="${escHtml(mobileUrl || "Tunnel 4G/5G non démarré")}" onclick="this.select()">
            <button type="button" class="btn-secondary btn-sm" ${mobileUrl ? "" : "disabled"} onclick="copyLinkWithFeedback('${escJs(mobileUrl)}', 'Hors de chez vous')" aria-label="Copier le lien 4G/5G" title="Copier le lien">📋 Copier</button>
          </div>
        </div>
        <a href="/api/permanent_bookmark" class="btn btn-primary btn-sm btn-block" style="text-decoration:none">📌 Enregistrer le raccourci 4G/5G</a>
      </div>

      <!-- OPTION 3 : ACCÈS PERMANENT -->
      <div class="remote-card">
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
            <h3 style="font-size:var(--text-base)">🛡️ Accès permanent</h3>
            ${tsBadge}
          </div>
          <p class="sub">Adresse privée fixe (VPN Tailscale) qui ne change jamais, même si le serveur redémarre.</p>
          <div class="copy-input-group" style="margin-bottom:12px">
            <label for="inp_remote_ts" class="sr-only">Lien accès permanent Tailscale</label>
            <input id="inp_remote_ts" type="text" readonly value="${escHtml(tsUrl || "Non configuré — cliquez ci-dessous")}" onclick="this.select()">
            <button type="button" class="btn-secondary btn-sm" ${tsUrl ? "" : "disabled"} onclick="copyLinkWithFeedback('${escJs(tsUrl)}', 'Accès permanent')" aria-label="Copier le lien permanent" title="Copier le lien">📋 Copier</button>
          </div>
        </div>
        <button type="button" class="btn-secondary btn-sm btn-block" onclick="toggleTailscaleCard(true)">🔒 Configurer l'accès permanent</button>
      </div>
    </div>
  `;
}

export function toggleTailscaleCard(forceOpen = null) {
  const card = document.getElementById("sec_tailscale");
  if (!card) return;
  const open = forceOpen !== null ? forceOpen : card.style.display === "none";
  card.style.display = open ? "block" : "none";
  if (open) {
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

export function renderTailscaleStatus(ts) {
  if (!ts) return;
  const badge = document.getElementById("ts_mini_badge");
  const stTitle = document.getElementById("ts_state_title");
  const stSub = document.getElementById("ts_state_sub");
  const btn = document.getElementById("ts_connect_btn");
  const tutoLinks = document.getElementById("ts_links_tuto");

  if (ts.connected && ts.ip) {
    if (badge) badge.textContent = `🟢 Actif : ${ts.ip}`;
    if (stTitle) stTitle.innerHTML = `🟢 Accès permanent actif — Adresse fixe : <code>${ts.ip}</code>`;
    if (stSub) {
      stSub.innerHTML = `Portail : <a href="http://${ts.ip}:5000">http://${ts.ip}:5000</a> • IlianTify : <a href="http://${ts.ip}:5000/iliantify">http://${ts.ip}:5000/iliantify</a>`;
    }
    if (btn) btn.textContent = "✅ Serveur connecté";
    if (tutoLinks) {
      tutoLinks.innerHTML =
        `• Portail : <a href="http://${ts.ip}:5000">http://${ts.ip}:5000</a><br>` +
        `• IlianTify : <a href="http://${ts.ip}:5000/iliantify">http://${ts.ip}:5000/iliantify</a><br>` +
        `• Jellyfin : <a href="http://${ts.ip}:8096">http://${ts.ip}:8096</a>`;
    }
  } else if (ts.auth_url) {
    if (badge) badge.textContent = "🔑 Prêt à valider";
    if (stTitle) stTitle.textContent = "🔑 Association Tailscale prête à être validée";
    if (stSub) {
      stSub.innerHTML = `<a href="${ts.auth_url}" target="_blank">👉 Ouvrir la page d'activation Tailscale</a>`;
    }
    if (btn) {
      btn.textContent = "🔑 Valider mon compte";
      btn.onclick = () => window.open(ts.auth_url, "_blank");
    }
  } else {
    if (badge) badge.textContent = "🔒 Adresse fixe";
    if (stTitle) stTitle.textContent = "🛡️ Accès permanent prêt à être configuré";
  }
}

export async function connectTailscaleNow(btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳ Génération du lien...";
  }
  try {
    const d = await api.connectTailscale();
    renderTailscaleStatus(d);
    if (d.auth_url) window.open(d.auth_url, "_blank");
  } catch (_) {
    showToast("Impossible de contacter le service Tailscale.", "error");
  } finally {
    if (btnEl) btnEl.disabled = false;
  }
}
