/**
 * Games Hub — configuration.
 *
 * This is the ONLY module in the hub that holds an external URL. If the CDN has
 * to be swapped for a mirror, change it here and nowhere else; every other file
 * is same-origin.
 *
 * Gameplay tuning lives here too, so no speed, timing or scoring weight is
 * buried in the design brief.
 */

/** Engine source. Pinned — an unpinned CDN would let the games change under us. */
export const ENGINE = {
  name: "Phaser",
  version: "3.80.1",
  /** Pinned CDN build. */
  cdn: "https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js",
  /** Same-version local mirror, used automatically when the CDN is unreachable. */
  local: "/static/gameshub/vendor/phaser.min.js",
};

/** Key namespace for everything this hub writes to localStorage. */
export const STORAGE_PREFIX = "gameshub:";

/** End-of-round reasons, mapped to the words the player sees. */
export const END_REASONS = {
  "time-up": "Time's up",
  complete: "Round complete",
  "game-over": "Game over",
};

/** Reason used when a round is stopped deliberately (not a failure). */
export const DEFAULT_END_REASON = "complete";

/** Playfield budget shared by every game. Portrait first, letterboxed in landscape. */
export const PLAYFIELD = {
  width: 390,
  height: 620,
  targetFps: 60,
  /** Cap the device pixel ratio — a 3x phone screen triples fill cost for nothing. */
  maxPixelRatio: 2,
};

export const TUNING = {
  "catch-the-burger": {
    groundY: 486,
    playerX: 92,
    playerSize: 56,
    gravity: 2150,
    jumpVelocity: -770,
    startSpeed: 232,
    maxSpeed: 470,
    speedRampPerSecond: 6.5,
    spawnGapMin: 1.0,
    spawnGapMax: 1.8,
    burgerChance: 0.42,
    burgerScore: 10,
    survivalScorePerSecond: 1,
    /** Shrink the physics box so a near-miss never feels like a robbery. */
    hitboxShrink: 12,
  },

  "memory-match": {
    cols: 4,
    rows: 3,
    pairs: 6,
    roundSeconds: 60,
    flipBackDelayMs: 720,
    pairScore: 100,
    timeBonusPerSecond: 5,
    /** Below this the tiles get noisier to flip — kept generous for small thumbs. */
    tileGap: 10,
  },

  "stack-the-burger": {
    layerWidth: 258,
    layerHeight: 34,
    baseY: 548,
    moveSpeed: 265,
    moveSpeedPerLayer: 9,
    maxMoveSpeed: 520,
    perfectTolerance: 9,
    perfectBonus: 25,
    layerScore: 10,
    minWidth: 44,
    /** How far the tower must rise before the camera follows it. */
    scrollThresholdY: 300,
    scrollSpeed: 2.4,
  },
};
