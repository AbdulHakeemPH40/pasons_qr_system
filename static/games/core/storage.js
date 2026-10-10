/*
 * Games Zone — per-device best scores (GAMES_ZONE_PLAN.md section 4).
 * localStorage only, wrapped in try/catch so private-browsing modes and
 * full storage never break a game. Nothing leaves the phone.
 */
(function () {
  "use strict";

  var KEY = "pasons.games.best.";

  function get(slug) {
    try {
      var raw = window.localStorage.getItem(KEY + slug);
      var n = parseInt(raw, 10);
      return isFinite(n) && n > 0 ? n : 0;
    } catch (e) {
      return 0;
    }
  }

  /* Stores score when it beats the stored best; returns the best now held. */
  function submit(slug, score) {
    var best = get(slug);
    if (score > best) {
      best = score;
      try {
        window.localStorage.setItem(KEY + slug, String(best));
      } catch (e) {
        /* storage unavailable: the session score still counts in-page */
      }
    }
    return best;
  }

  window.GamesStorage = { get: get, submit: submit };
})();
