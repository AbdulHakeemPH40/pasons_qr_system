/**
 * Play screen entry point.
 *
 * Resolve the background pack -> load the engine -> load one game module ->
 * wire the shell. Deliberately the only place that knows how those pieces are
 * assembled, so a scoring service can be swapped in at exactly one line.
 */

import { TUNING, PLAYFIELD } from "./config.js";
import { loadPhaser } from "./loader.js";
import { createScoring } from "./scoring.js";
import { createShell } from "./shell.js";
import { resolveTheme, applyTheme, readDefaultThemeSlug } from "./theme.js";
import { getThemeSlug } from "./storage.js";

const GAME_MODULES = {
  "catch-the-burger": () => import("../games/catch-the-burger.js"),
  "memory-match": () => import("../games/memory-match.js"),
  "stack-the-burger": () => import("../games/stack-the-burger.js"),
};

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function showFailure(host, message) {
  const fallback = host.querySelector(".gh-canvas-fallback");
  if (fallback) {
    fallback.textContent = message;
    fallback.hidden = false;
  } else {
    host.textContent = message;
  }
}

async function main() {
  const host = document.querySelector("[data-game-host]");
  if (!host) return;

  const gameId = host.dataset.gameHost;
  const loadGame = GAME_MODULES[gameId];
  if (!loadGame) {
    showFailure(host, "This game is not available.");
    return;
  }

  // Background pack: the stored preference wins, the server default stands in.
  const theme = resolveTheme(getThemeSlug(readDefaultThemeSlug()));
  applyTheme(theme);

  const reducedMotion = prefersReducedMotion();
  const scoring = createScoring({ gameId });
  const shell = createShell({ gameId, host, scoring, reducedMotion });

  // The template knows where static files really live; config.js keeps the
  // external URL. Neither has to know about the other's concerns.
  const local = host.dataset.staticBase
    ? host.dataset.staticBase + "vendor/phaser.min.js"
    : undefined;

  let engine;
  try {
    engine = await loadPhaser(local ? { local } : {});
  } catch {
    showFailure(host, "The game could not load. Check the connection and try again.");
    return;
  }

  const module = await loadGame();

  const game = module.createGame({
    Phaser: engine,
    host,
    theme,
    tuning: TUNING[gameId],
    playfield: PLAYFIELD,
    emit: shell.emit,
    reducedMotion,
  });

  shell.attachGame(game);
  game.start();

  // The engine is up; the loading placeholder has done its job.
  const fallback = host.querySelector(".gh-canvas-fallback");
  if (fallback) fallback.remove();
}

main().catch((error) => {
  const host = document.querySelector("[data-game-host]");
  if (host) showFailure(host, "The game could not start.");
  // eslint-disable-next-line no-console
  console.error("[gameshub]", error);
});
