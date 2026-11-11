/**
 * UI / FEEDBACK — Modale de confirmation accessible, Notifications Toast & États bouton
 */

export function showToast(message, type = "info") {
  let container = document.getElementById("toast_container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast_container";
    container.className = "toast-container";
    container.setAttribute("role", "status");
    container.setAttribute("aria-live", "polite");
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 3200);
}

export function confirmAction({
  title = "Confirmer l'action",
  message = "Voulez-vous vraiment continuer ?",
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  danger = true,
}) {
  return new Promise((resolve) => {
    const backdrop = document.getElementById("confirm_modal");
    if (!backdrop) {
      resolve(window.confirm(`${title}\n\n${message}`));
      return;
    }
    const titleEl = document.getElementById("confirm_modal_title");
    const msgEl = document.getElementById("confirm_modal_msg");
    const okBtn = document.getElementById("confirm_modal_ok");
    const cancelBtn = document.getElementById("confirm_modal_cancel");

    titleEl.textContent = title;
    msgEl.textContent = message;
    okBtn.textContent = confirmLabel;
    okBtn.className = danger ? "btn-danger" : "btn-primary";
    cancelBtn.textContent = cancelLabel;

    const cleanup = (result) => {
      backdrop.classList.remove("open");
      backdrop.setAttribute("aria-hidden", "true");
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      resolve(result);
    };

    okBtn.onclick = () => cleanup(true);
    cancelBtn.onclick = () => cleanup(false);
    backdrop.classList.add("open");
    backdrop.setAttribute("aria-hidden", "false");
    cancelBtn.focus();
  });
}

export function markBtnValidated(btnEl, label = "Lancé !") {
  if (!btnEl) return;
  if (!btnEl.dataset.origHtml) {
    btnEl.dataset.origHtml = btnEl.innerHTML;
  }
  btnEl.innerHTML = `✓ ${label}`;
  btnEl.disabled = true;
  setTimeout(() => {
    if (btnEl && btnEl.dataset.origHtml) {
      btnEl.innerHTML = btnEl.dataset.origHtml;
      btnEl.disabled = false;
    }
  }, 1800);
}
