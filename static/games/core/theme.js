/*
 * Games Zone — brand theme bridge (GAMES_ZONE_PLAN.md section 4).
 * Reads the JSON palette Django embeds in #games-theme (brand_colors with
 * safe defaults) and exposes it to the canvas games, so every game paints
 * in the outlet's brand colours without any game knowing about Django.
 */
(function () {
  "use strict";

  var DEFAULTS = {
    primary: "#7FA06B",
    secondary: "#5E7F52",
    accent: "#D9A83C",
    dark: "#1F3726"
  };

  var data = {};
  var el = document.getElementById("games-theme");
  if (el) {
    try {
      data = JSON.parse(el.textContent) || {};
    } catch (e) {
      data = {};
    }
  }

  var theme = {
    primary: data.primary || DEFAULTS.primary,
    secondary: data.secondary || DEFAULTS.secondary,
    accent: data.accent || DEFAULTS.accent,
    dark: data.dark || DEFAULTS.dark,
    cream: "#F7F2E6",
    white: "#FFFFFF",
    danger: "#C4574A",
    /* ordered palette games cycle through for tiles / cards / layers */
    palette: []
  };
  theme.palette = [
    theme.primary,
    theme.accent,
    theme.secondary,
    "#8FBF7A",
    "#E4C05C",
    theme.dark
  ];

  window.GamesTheme = theme;
})();
