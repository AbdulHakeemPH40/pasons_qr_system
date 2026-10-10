/*
 * Games Zone — shared shell for VENDORED open-source games.
 *
 * The games themselves live unmodified in static/games/vendor/<slug>/ and run
 * inside a same-origin iframe (see templates/games/play.html). Because the
 * iframe is same-origin, the shell can observe each game through its DOM or
 * window globals using the per-game `bridge` config Django embeds in
 * #games-bridge — no vendored code is patched to talk to us.
 *
 * The shell owns:
 *   - the HUD (live score + per-device best from GamesStorage)
 *   - the game-over overlay (score, best, Play again, Exit)
 *   - Restart (reloads the iframe: fresh page, fresh state, zero shared globals)
 *   - the analytics beacon (GameEvent played / finished)
 *
 * It deliberately does NOT own start or pause: every vendored game ships its
 * own start screen and, where the genre needs it, its own pause control.
 * Faking a pause over games we do not control would lie to the guest.
 */
(function () {
  "use strict";

  function boot() {
    var host = document.getElementById("game-host");
    if (!host) return;

    var frame = document.getElementById("game-frame");
    var overlay = document.getElementById("game-overlay");
    var scoreEl = document.getElementById("game-score");
    var bestEl = document.getElementById("game-best");
    var restartBtn = document.getElementById("game-restart");
    if (!frame || !overlay || !scoreEl || !bestEl) return;

    var slug = host.dataset.slug || "";
    var bridge = {};
    var bridgeEl = document.getElementById("games-bridge");
    if (bridgeEl) {
      try { bridge = JSON.parse(bridgeEl.textContent) || {}; } catch (e) { bridge = {}; }
    }
    var storage = window.GamesStorage || {
      get: function () { return 0; },
      submit: function (s, v) { return v; }
    };

    var best = storage.get(slug);
    var score = 0;
    var over = false;
    var played = false;
    var doc = null;

    function paintBest() {
      bestEl.textContent = best > 0 ? "Best " + best : "Best —";
    }

    function exitHref() {
      var b = document.querySelector(".sheet-back");
      return (b && b.getAttribute("href")) || "/";
    }

    /* ---- analytics beacon: GameEvent rows for the play funnel ---- */
    function beacon(kind, value) {
      var url = host.dataset.beacon;
      if (!url) return;
      try {
        var body = new FormData();
        body.append("slug", slug);
        body.append("kind", kind);
        body.append("score", String(value | 0));
        if (host.dataset.qr) body.append("qr", host.dataset.qr);
        var token = host.dataset.csrf;
        if (token) body.append("csrfmiddlewaretoken", token);
        if (navigator.sendBeacon) navigator.sendBeacon(url, body);
        else fetch(url, { method: "POST", body: body, keepalive: true });
      } catch (e) {
        /* analytics must never break a game */
      }
    }

    function markPlayed() {
      if (played) return;
      played = true;
      beacon("played", score);
    }

    function setScore(n) {
      n = Math.max(0, n | 0);
      if (n === score) return;
      score = n;
      scoreEl.textContent = String(score);
      if (score > 0) markPlayed();
    }

    /* ---- bridge readers ---- */
    function readScore() {
      var cfg = bridge.score;
      if (!doc || !cfg) return null;
      try {
        if (cfg.kind === "text") {
          var el = doc.querySelector(cfg.sel);
          return el ? (parseInt(el.textContent, 10) || 0) : null;
        }
        if (cfg.kind === "digits") {
          var box = doc.querySelector(cfg.sel);
          if (!box) return null;
          var alts = "";
          var imgs = box.querySelectorAll("img");
          for (var i = 0; i < imgs.length; i++) alts += imgs[i].getAttribute("alt") || "";
          return alts ? (parseInt(alts, 10) || 0) : 0;
        }
        if (cfg.kind === "global") {
          var v = frame.contentWindow[cfg.name];
          return typeof v === "number" ? v : (parseInt(v, 10) || 0);
        }
        if (cfg.kind === "parse") {
          var els = doc.querySelectorAll(cfg.sel);
          var re = new RegExp(cfg.re);
          for (var j = 0; j < els.length; j++) {
            var m = re.exec(els[j].textContent || "");
            if (m) return parseInt(m[1], 10) || 0;
          }
          return 0;
        }
        /* "objects": count the entries of a game global array whose named
           property is truthy, divided by divisor. Needed where the game keeps
           matched items in the DOM (memory-match never removes matched cards,
           so a children count can't see progress) but exposes its state on a
           model global. MemoryGame.cards[i].isRevealed is exactly 2 x matched
           pairs, and the model clears a mismatch at once, so the score never
           sticks high while two mismatched cards are still shown. */
        if (cfg.kind === "objects") {
          var ref = frame.contentWindow;
          var path = String(cfg.name || "").split(".");
          for (var p = 0; p < path.length && ref; p++) ref = ref[path[p]];
          if (!ref || typeof ref.length !== "number") return null;
          var hit = 0;
          for (var q = 0; q < ref.length; q++) {
            if (ref[q] && ref[q][cfg.prop]) hit++;
          }
          return Math.floor(hit / (cfg.divisor || 1));
        }
      } catch (e) {
        return null;
      }
      return null;
    }

    function isOver() {
      var cfg = bridge.over;
      if (!doc || !cfg) return false;
      try {
        if (cfg.kind === "class") {
          var el = doc.querySelector(cfg.sel);
          return !!(el && el.classList.contains(cfg.cls));
        }
        if (cfg.kind === "visible") {
          var els = doc.querySelectorAll(cfg.sel);
          for (var i = 0; i < els.length; i++) {
            if (els[i].offsetParent !== null || els[i].getClientRects().length) return true;
          }
        }
        /* "equals": an iframe window global reaches a sentinel value.
           Needed where the game-over element always has a layout box
           (hextris hides #gameoverscreen with jQuery only after first
           use, so DOM visibility lies); gameState == -1 is authoritative. */
        if (cfg.kind === "equals") {
          return frame.contentWindow[cfg.name] === cfg.value;
        }
      } catch (e) { /* ignore */ }
      return false;
    }

    /* ---- game over ---- */
    function finish() {
      if (over) return;
      over = true;
      markPlayed();
      best = storage.submit(slug, score);
      paintBest();
      beacon("finished", score);

      overlay.dataset.state = "over";
      overlay.innerHTML = "";
      var t = document.createElement("p");
      t.className = "game-overlay__title";
      t.textContent = "Game over";
      var s = document.createElement("p");
      s.className = "game-overlay__score";
      s.textContent = String(score);
      var sub = document.createElement("p");
      sub.className = "game-overlay__sub";
      sub.textContent = score > 0 && score >= best
        ? "New best on this phone."
        : (best > 0 ? "Best on this phone: " + best : "Thanks for playing.");
      var row = document.createElement("div");
      row.className = "game-overlay__row";
      var again = document.createElement("button");
      again.type = "button";
      again.className = "game-cta";
      again.textContent = "Play again";
      again.addEventListener("click", restart);
      var exit = document.createElement("a");
      exit.className = "game-cta game-cta--ghost";
      exit.href = exitHref();
      exit.textContent = "Exit";
      row.appendChild(again);
      row.appendChild(exit);
      overlay.appendChild(t);
      overlay.appendChild(s);
      overlay.appendChild(sub);
      overlay.appendChild(row);
    }

    /* ---- restart: reload the vendored page for a clean round ---- */
    function reloadFrame(url) {
      frame.src = url;
    }

    function clearResetKeys() {
      var keys = bridge.resetKeys;
      if (!keys || !keys.length) return;
      try {
        for (var i = 0; i < keys.length; i++) window.localStorage.removeItem(keys[i]);
      } catch (e) { /* private mode: nothing to clear */ }
    }

    function restart() {
      over = false;
      played = false;
      score = 0;
      scoreEl.textContent = "0";
      overlay.dataset.state = "hidden";
      overlay.innerHTML = "";

      /* Capture the absolute game URL now: after we navigate to about:blank
         the frame's own src/base is blank and a relative URL would not
         resolve back to the game. */
      var gameSrc = frame.src;

      /* Some vendored games persist a resume state in localStorage (the
         same-origin iframe shares the parent store) AND re-save it on
         unload, so clearing before a reload is undone by the departing
         page. Two-step: navigate to about:blank first (the game is gone
         and can no longer re-save), clear its declared resetKeys, then
         load the real page fresh. Never touches pasons.games.best.*. */
      if (bridge.resetKeys && bridge.resetKeys.length) {
        clearResetKeys();
        frame.addEventListener("load", function onBlank() {
          frame.removeEventListener("load", onBlank);
          clearResetKeys();
          reloadFrame(gameSrc);
        });
        frame.src = "about:blank";
      } else {
        reloadFrame(gameSrc);
      }
    }

    if (restartBtn) restartBtn.addEventListener("click", restart);

    frame.addEventListener("load", function () {
      try { doc = frame.contentDocument || null; } catch (e) { doc = null; }
      over = false;
      if (doc) {
        /* first real interaction inside the game counts as "played" */
        doc.addEventListener("pointerdown", markPlayed, { once: true });
        doc.addEventListener("keydown", markPlayed, { once: true });
      }
    });

    window.setInterval(function () {
      if (!doc || over) return;
      var s = readScore();
      if (s !== null) setScore(s);
      if (isOver()) finish();
    }, 250);

    paintBest();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
