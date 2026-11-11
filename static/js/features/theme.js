/**
 * FEATURE / THEME — Gestion du mode Sombre et du mode Clair
 */

export function applyTheme(themeName) {
  const isLight = themeName === "light" || themeName === "xp";
  const normalized = isLight ? "light" : "dark";

  document.body.classList.remove("theme-light", "theme-xp");
  if (isLight) {
    document.body.classList.add("theme-light");
  }
  localStorage.setItem("serveur_ilian_theme", normalized);

  const btn = document.getElementById("theme_toggle_btn");
  if (btn) {
    btn.innerHTML = isLight ? "🌙 Mode Nuit" : "☀️ Mode Clair";
    btn.setAttribute(
      "aria-label",
      isLight ? "Activer le thème sombre" : "Activer le thème clair"
    );
  }
}

export function cycleTheme() {
  const cur = localStorage.getItem("serveur_ilian_theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next);
}

export function updateXpClock() {
  const el = document.getElementById("xp_clock");
  if (el) {
    const d = new Date();
    el.textContent =
      String(d.getHours()).padStart(2, "0") +
      ":" +
      String(d.getMinutes()).padStart(2, "0");
  }
}
