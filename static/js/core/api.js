/**
 * CORE / API — Client HTTP centralisé avec gestion d'erreurs humaine
 */

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Erreur serveur (${response.status})`);
  }
  return response.json();
}

function toFormData(obj) {
  const fd = new FormData();
  Object.entries(obj).forEach(([key, val]) => {
    fd.append(key, val !== undefined && val !== null ? val : "");
  });
  return fd;
}

export const api = {
  getStatus: () => request("/api/status"),
  clearLogs: () => fetch("/api/clear_logs", { method: "POST" }),
  stopDownload: () => fetch("/api/stop", { method: "POST" }),

  // Catalogue & Téléchargements vidéo
  getCatalog: (filter, q = "") =>
    request(
      `/api/media_catalog?filter=${encodeURIComponent(filter)}${
        q ? `&q=${encodeURIComponent(q)}` : ""
      }`
    ),
  getAnimeSeasons: (url) =>
    request(`/api/anime_seasons?url=${encodeURIComponent(url)}`),
  getSeasonInfo: (jsUrl) =>
    request(`/api/season_info?js_url=${encodeURIComponent(jsUrl)}`),
  getSeriesEpisodes: (id, title) =>
    request(
      `/api/series_episodes?id=${encodeURIComponent(id)}&title=${encodeURIComponent(title)}`
    ),
  downloadMedia: (payload) =>
    fetch("/api/download_media", { method: "POST", body: toFormData(payload) }),
  downloadAnimeSeason: (payload) =>
    fetch("/api/download_season", { method: "POST", body: toFormData(payload) }),
  runStreamHealer: () => request("/api/stream_healer_run", { method: "POST" }),

  // Musique & Deezer
  getDeezerHome: (refresh = false) =>
    request(`/api/deezer_home${refresh ? "?refresh=1" : ""}`),
  syncDeezer: (url) =>
    request("/api/deezer_sync", { method: "POST", body: toFormData({ url }) }),
  downloadPlaylist: (id) =>
    fetch("/api/spotify_download_playlist", {
      method: "POST",
      body: toFormData({ id }),
    }),
  searchMusic: (q, type) =>
    request(`/api/music_preview?q=${encodeURIComponent(q)}&type=${encodeURIComponent(type)}`),
  downloadMusic: (payload) =>
    fetch("/api/music_download", { method: "POST", body: toFormData(payload) }),
  findMusicPreview: (q) =>
    request(`/api/music_find_preview?q=${encodeURIComponent(q)}`),

  // Bibliothèque de fichiers
  getFiles: () => request("/api/files"),
  deleteFile: (path) =>
    fetch("/api/delete_file", { method: "POST", body: toFormData({ path }) }),

  // Téléchargement rapide par lien (YouTube, TikTok, X / Twitter)
  probeSocialFormats: (url) =>
    request(`/api/social_formats?url=${encodeURIComponent(url)}`),
  downloadSocialLink: (url, format = "best") =>
    request("/api/social_download", {
      method: "POST",
      body: toFormData({ url, format }),
    }),
  getSocialDownloads: () => request("/api/social_downloads_list"),

  // Accès distant & Administration
  connectTailscale: () =>
    request("/api/tailscale_connect", { method: "POST" }),
  execCmd: (cmd) =>
    request("/api/cmd", { method: "POST", body: toFormData({ cmd }) }),
  readCode: (file) =>
    request(`/api/code_read?file=${encodeURIComponent(file)}`),
  saveCode: (file, content) =>
    request("/api/code_save", {
      method: "POST",
      body: toFormData({ file, content }),
    }),
  listBackups: () => request("/api/backups_list"),
  createBackup: (label) =>
    fetch("/api/backups_create", {
      method: "POST",
      body: toFormData({ label }),
    }),
  restoreBackup: (name) =>
    request("/api/backups_restore", {
      method: "POST",
      body: toFormData({ name }),
    }),
  restartAll: () => fetch("/api/restart_all", { method: "POST" }),
};
