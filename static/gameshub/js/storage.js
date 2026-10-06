/**
 * Browser persistence for the hub. Nothing here is sent anywhere.
 *
 * Every access is guarded: Safari private mode and some in-app browsers throw
 * on localStorage access, and a game that dies over a storage error is worse
 * than a game that forgets your best score.
 */

import { STORAGE_PREFIX } from "./config.js";

const HIGH_SCORE_KEY = "high-score";
const THEME_KEY = "theme";

function store() {
  try {
    const s = window.localStorage;
    // Touch it: some browsers expose the object but throw on use.
    const probe = STORAGE_PREFIX + "probe";
    s.setItem(probe, "1");
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}

const cache = new Map();

export function getHighScore(gameId) {
  const s = store();
  if (!s) return cache.get(gameId) || 0;
  const raw = s.getItem(`${STORAGE_PREFIX}${HIGH_SCORE_KEY}:${gameId}`);
  const value = Number.parseInt(raw || "0", 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function setHighScore(gameId, score) {
  const value = Math.max(0, Math.trunc(score) || 0);
  cache.set(gameId, value);
  const s = store();
  if (!s) return value;
  try {
    s.setItem(`${STORAGE_PREFIX}${HIGH_SCORE_KEY}:${gameId}`, String(value));
  } catch {
    /* quota or private mode — the in-memory value still works this session */
  }
  return value;
}

export function getThemeSlug(fallback) {
  const s = store();
  const value = s ? s.getItem(`${STORAGE_PREFIX}${THEME_KEY}`) : cache.get("theme");
  return value || fallback;
}

export function setThemeSlug(slug) {
  cache.set("theme", slug);
  const s = store();
  if (!s) return;
  try {
    s.setItem(`${STORAGE_PREFIX}${THEME_KEY}`, slug);
  } catch {
    /* ignore */
  }
}
