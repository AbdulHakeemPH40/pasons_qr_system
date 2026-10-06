/**
 * The scoring boundary.
 *
 * Games never touch storage or a network themselves. They finish a round and
 * hand the score here; whatever `submit` does is somebody else's business. That
 * is the seam that lets a scoring service be added later without rewriting a
 * single game loop.
 *
 * To move scoring server-side, call `createScoring({ submit: serverSubmit })`
 * from boot.js and leave every game file untouched.
 */

import { getHighScore, setHighScore } from "./storage.js";

/**
 * Default submit: keep the best score on this device.
 * @returns {Promise<{best:number,isBest:boolean}>}
 */
export function localSubmit({ gameId, score }) {
  const clean = Math.max(0, Math.trunc(score) || 0);
  const previous = getHighScore(gameId);
  const isBest = clean > previous;
  const best = isBest ? setHighScore(gameId, clean) : previous;
  return Promise.resolve({ best, isBest });
}

/**
 * @param {object} opts
 * @param {string} opts.gameId
 * @param {function} [opts.submit] - override the persistence strategy
 */
export function createScoring({ gameId, submit = localSubmit } = {}) {
  if (!gameId) throw new Error("createScoring needs a gameId");

  return {
    /** Record a finished round and learn how it compares to the best. */
    async finish(score, meta = {}) {
      return submit({ gameId, score: Math.max(0, Math.trunc(score) || 0), meta });
    },
    /** Best score known right now. */
    best() {
      return getHighScore(gameId);
    },
  };
}
