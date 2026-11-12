/**
 * MAIN.JS — Point d'entrée unique, initialisation et pont de non-régression window.*
 */
import { escJs, openService } from "./core/utils.js?v=8";
import { markBtnValidated } from "./ui/feedback.js?v=8";
import { applyTheme, cycleTheme, updateXpClock } from "./features/theme.js?v=8";
import {
  copyLogs,
  clearLogs,
  stopDownload,
  updateStatus,
  dismissFloatingDock,
  notifyDownloadStarted,
} from "./features/status.js?v=8";
import {
  copyLinkWithFeedback,
  toggleTailscaleCard,
  renderTailscaleStatus,
  connectTailscaleNow,
} from "./features/remote.js?v=8";
import {
  clearMediaSearchInput,
  setActiveFilterBtn,
  toggleCatalogExpanded,
  scrollCatalogCarousel,
  loadMediaCatalog,
  searchMediaCatalog,
  renderMediaItems,
  selectMediaLang,
  renderAnimeSeasonsByLang,
  openMediaPanel,
  openMediaPanelByIndex,
  openAnimeSeasonEpisodes,
  renderSeriesSeasonEps,
  triggerMediaDownload,
  triggerMediaRangeDownload,
  startEpDl,
  startRangeDl,
  renderStreamHealerBar,
  runStreamHealerNow,
} from "./features/catalog.js?v=8";
import {
  clearMusicSearchInput,
  toggleDeezerDrawer,
  switchDeezerTab,
  renderMusicCardHtml,
  loadDeezerHome,
  syncDeezerNow,
  downloadSpotifyPlaylist,
  selectMusicSearchMode,
  previewMusic,
  downloadMusicItem,
  playMusicPreview,
  stopMiniPreview,
} from "./features/music.js?v=8";
import {
  setFilesFilter,
  toggleFolderAcc,
  loadFiles,
  renderFileGroups,
  deleteFile,
} from "./features/library.js?v=8";
import {
  switchStudioTab,
  loadCodeFile,
  saveCodeFile,
  loadBackupsList,
  createBackupNow,
  restoreBackup,
  appendTerminalEntry,
  execTerminalCmd,
  handleTermKey,
  clearTerminal,
  quickTermPorts,
  quickTermLinks,
  restartServices,
} from "./features/admin.js?v=8";
import {
  clearSocialUrlInput,
  pasteSocialUrlFromClipboard,
  selectSocialFormat,
  probeSocialLinkQualities,
  startSocialLinkDownload,
  startSocialLinkDownloadWithQuality,
  loadSocialDownloads,
  deleteSocialFile,
} from "./features/social.js?v=8";

// Pont de rétrocompatibilité : expose toutes les fonctions attendues par le DOM
Object.assign(window, {
  escJs,
  openService,
  markBtnValidated,
  applyTheme,
  cycleTheme,
  updateXpClock,
  copyLogs,
  clearLogs,
  stopDownload,
  updateStatus,
  dismissFloatingDock,
  notifyDownloadStarted,
  copyLinkWithFeedback,
  toggleTailscaleCard,
  renderTailscaleStatus,
  connectTailscaleNow,
  clearMediaSearchInput,
  setActiveFilterBtn,
  toggleCatalogExpanded,
  scrollCatalogCarousel,
  loadMediaCatalog,
  searchMediaCatalog,
  renderMediaItems,
  selectMediaLang,
  renderAnimeSeasonsByLang,
  openMediaPanel,
  openMediaPanelByIndex,
  openAnimeSeasonEpisodes,
  renderSeriesSeasonEps,
  triggerMediaDownload,
  triggerMediaRangeDownload,
  startEpDl,
  startRangeDl,
  renderStreamHealerBar,
  runStreamHealerNow,
  clearMusicSearchInput,
  toggleDeezerDrawer,
  switchDeezerTab,
  renderMusicCardHtml,
  loadDeezerHome,
  syncDeezerNow,
  downloadSpotifyPlaylist,
  selectMusicSearchMode,
  previewMusic,
  downloadMusicItem,
  playMusicPreview,
  stopMiniPreview,
  setFilesFilter,
  toggleFolderAcc,
  loadFiles,
  renderFileGroups,
  deleteFile,
  switchStudioTab,
  loadCodeFile,
  saveCodeFile,
  loadBackupsList,
  createBackupNow,
  restoreBackup,
  appendTerminalEntry,
  execTerminalCmd,
  handleTermKey,
  clearTerminal,
  quickTermPorts,
  quickTermLinks,
  restartServices,
  clearSocialUrlInput,
  pasteSocialUrlFromClipboard,
  selectSocialFormat,
  probeSocialLinkQualities,
  startSocialLinkDownload,
  startSocialLinkDownloadWithQuality,
  loadSocialDownloads,
  deleteSocialFile,
});

function initNavigationObserver() {
  const navLinks = document.querySelectorAll("[data-nav-sec]");
  if (!navLinks.length || !("IntersectionObserver" in window)) return;

  const setActiveNav = (secId) => {
    navLinks.forEach((link) => {
      const isMatch = link.getAttribute("data-nav-sec") === secId;
      link.classList.toggle("active", isMatch);
      if (isMatch) {
        link.setAttribute("aria-current", "true");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      const targetId = link.getAttribute("data-nav-sec");
      if (targetId) setActiveNav(targetId);
    });
  });

  const sections = ["sec_home", "sec_music", "sec_catalog", "sec_library", "sec_remote", "sec_admin", "sec_social_dl"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (visible.length > 0) {
        setActiveNav(visible[0].target.id);
      }
    },
    { rootMargin: "-20% 0px -60% 0px", threshold: [0.1, 0.3, 0.6] }
  );

  sections.forEach((sec) => observer.observe(sec));
}

// Initialisation au chargement du DOM
document.addEventListener("DOMContentLoaded", () => {
  applyTheme(localStorage.getItem("serveur_hugo_theme") || "dark");
  updateXpClock();
  setInterval(updateXpClock, 15000);
  initNavigationObserver();

  updateStatus();
  loadFiles();
  loadMediaCatalog("trending");
  loadDeezerHome();
  loadSocialDownloads();

  setInterval(updateStatus, 2500);
  setInterval(loadFiles, 10000);
  setInterval(loadSocialDownloads, 8000);
});
