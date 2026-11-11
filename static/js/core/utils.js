/**
 * CORE / UTILS — Fonctions utilitaires pures (échappement, presse-papiers, URLs)
 */

export function escJs(str) {
  return String(str || "")
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/"/g, "&quot;");
}

export function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function copyTextToClipboard(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {}
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(area);
  return ok;
}

export function openService(port, tunnelUrl, subPath) {
  const path = subPath || "/";
  if (
    window.location.hostname.includes("trycloudflare.com") &&
    tunnelUrl &&
    tunnelUrl.startsWith("http")
  ) {
    window.open(tunnelUrl.replace(/\/$/, "") + path, "_blank");
  } else {
    window.open(
      "http://" + window.location.hostname + ":" + port + path,
      "_blank"
    );
  }
}
