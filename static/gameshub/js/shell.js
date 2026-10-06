/**
 * Game screen shell.
 *
 * Owns everything around the canvas: score readout, the short feedback line,
 * pause/resume, the end-of-round panel, and the background/foreground hand-off.
 *
 * Two rules this file exists to enforce:
 *   1. DOM listeners are registered exactly once, at mount. Restarting a game
 *      never adds a listener — it only tells the game to reset itself. Use is
 *      made of event delegation so the count is constant no matter how many
 *      buttons the markup has.
 *   2. Games report state through `emit` and never reach into the page.
 */

import { END_REASONS, DEFAULT_END_REASON } from "./config.js";

const HIDDEN = "hidden";

export function createShell({ gameId, host, scoring, reducedMotion = false }) {
  const scope = host.closest(".gh-play") || document;
  const els = {
    score: scope.querySelector("[data-score]"),
    feedback: scope.querySelector("[data-feedback]"),
    end: scope.querySelector("[data-end]"),
    endKicker: scope.querySelector("[data-end-kicker]"),
    endScore: scope.querySelector("[data-end-score]"),
    endBest: scope.querySelector("[data-end-best]"),
    pause: scope.querySelector("[data-pause]"),
  };

  const controller = new AbortController();
  const { signal } = controller;

  let game = null;
  let ended = true;
  let pausedByPlayer = false;
  let pausedByBackground = false;

  const setScore = (value) => {
    if (els.score) els.score.textContent = String(Math.max(0, Math.trunc(value) || 0));
  };

  const setFeedback = (text) => {
    if (els.feedback) els.feedback.textContent = text || "";
  };

  const showEnd = async ({ reason, score, won }) => {
    if (ended) return;
    ended = true;

    if (els.pause) els.pause.hidden = true;
    if (els.endKicker) {
      els.endKicker.textContent = END_REASONS[reason] || END_REASONS[DEFAULT_END_REASON];
    }
    if (els.endScore) els.endScore.textContent = String(score);
    if (els.end) els.end.hidden = false;

    const result = await scoring.finish(score, { reason: reason || DEFAULT_END_REASON, won: !!won });
    if (els.endBest) els.endBest.textContent = String(result.best);
  };

  const actions = {
    pause() {
      if (ended || !game || pausedByPlayer) return;
      pausedByPlayer = true;
      game.pause();
      if (els.pause) els.pause.hidden = false;
    },
    resume() {
      if (!game || ended) return;
      pausedByPlayer = false;
      pausedByBackground = false;
      if (els.pause) els.pause.hidden = true;
      game.resume();
    },
    restart() {
      if (!game) return;
      pausedByPlayer = false;
      pausedByBackground = false;
      ended = false;
      if (els.pause) els.pause.hidden = true;
      if (els.end) els.end.hidden = true;
      setScore(0);
      setFeedback("");
      game.restart();
    },
  };

  // --- the single delegated click listener ---------------------------------
  scope.addEventListener(
    "click",
    (event) => {
      const trigger = event.target.closest("[data-act]");
      if (!trigger || !scope.contains(trigger)) return;
      const action = actions[trigger.dataset.act];
      if (action) {
        event.preventDefault();
        action();
      }
    },
    { signal },
  );

  // --- background / foreground --------------------------------------------
  document.addEventListener(
    "visibilitychange",
    () => {
      if (!game || ended) return;
      if (document.hidden) {
        if (!pausedByPlayer) {
          pausedByBackground = true;
          game.pause();
        }
      } else if (pausedByBackground) {
        pausedByBackground = false;
        game.resume();
      }
    },
    { signal },
  );

  return {
    reducedMotion,
    /** Wired into every game. */
    emit: {
      score: setScore,
      feedback: setFeedback,
      end: showEnd,
    },
    attachGame(instance) {
      game = instance;
      ended = false;
      setScore(0);
    },
    /** Tears down every listener this shell added. */
    destroy() {
      controller.abort();
      game = null;
    },
  };
}
