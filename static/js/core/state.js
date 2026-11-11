/**
 * CORE / STATE — Store centralisé de l'application (Source unique de vérité)
 */

export const store = {
  // Catalogue & Médias
  currentFilter: "trending",
  catalogItems: [],
  catalogExpanded: false,
  isSearchMode: false,
  selectedMediaLang: "vf",
  currentPanelCtx: null,
  currentAnimeSeasons: [],
  currentSeriesSeasons: [],

  // Musique
  lastMusicMode: "track",

  // Bibliothèque locale
  allFileGroups: [],
  currentFilesFilter: "all",
  openAccordions: {},

  // Terminal & Administration
  termHistory: [],
  termHistIdx: -1,
};
