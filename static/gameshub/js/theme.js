/**
 * Background packs for the restaurant demo.
 *
 * The server renders the full pack list as JSON, so there is exactly one copy of
 * these colours in the project (apps/gameshub/conf.py). This module only reads
 * that list and pushes the chosen pack into CSS custom properties.
 */

const THEMES_ID = "gh-themes";
const DEFAULT_ID = "gh-theme-default";

function readJson(id) {
  const node = document.getElementById(id);
  if (!node) return null;
  try {
    return JSON.parse(node.textContent);
  } catch {
    return null;
  }
}

/** @returns {object[]} every background pack the demo knows about */
export function readThemes() {
  const list = readJson(THEMES_ID);
  return Array.isArray(list) ? list : [];
}

/** @returns {string} the slug the server considers the default */
export function readDefaultThemeSlug() {
  return readJson(DEFAULT_ID) || "king-chef";
}

export function resolveTheme(slug) {
  const themes = readThemes();
  return (
    themes.find((t) => t.slug === slug) ||
    themes.find((t) => t.slug === readDefaultThemeSlug()) ||
    themes[0] ||
    null
  );
}

/** Push a pack into the playfield custom properties. */
export function applyTheme(theme) {
  if (!theme) return;
  const root = document.documentElement.style;
  root.setProperty("--gp-sky", theme.sky);
  root.setProperty("--gp-far", theme.far);
  root.setProperty("--gp-near", theme.near);
  root.setProperty("--gp-ground", theme.ground);
  root.setProperty("--gp-accent", theme.accent);
}

/** Hex string to a Phaser-friendly 0xRRGGBB integer. */
export function toColor(hex) {
  const clean = String(hex || "#000000").replace("#", "");
  const value = Number.parseInt(clean.slice(0, 6), 16);
  return Number.isFinite(value) ? value : 0x000000;
}
