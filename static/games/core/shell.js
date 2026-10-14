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
    var reloading = false;
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
    /* readScoreFrom returns the score rendered at `sel`, or null when the
       element is missing or holds nothing readable yet. null means "no
       reading" and MUST NOT be coerced to 0: several games erase their
       on-field score display at game-over (flappy-burger empties #bigscore
       and moves the total to #currentscore), and a spurious 0 there would
       both zero the HUD and make the best-score submit a no-op. */
    function readScoreFrom(sel) {
      var cfg = bridge.score;
      if (!doc || !cfg || !sel) return null;
      try {
        if (cfg.kind === "text") {
          var el = doc.querySelector(sel);
          if (!el) return null;
          var txt = (el.textContent || "").trim();
          return txt ? (parseInt(txt, 10) || 0) : null;
        }
        if (cfg.kind === "digits") {
          var box = doc.querySelector(sel);
          if (!box) return null;
          var alts = "";
          var imgs = box.querySelectorAll("img");
          for (var i = 0; i < imgs.length; i++) alts += imgs[i].getAttribute("alt") || "";
          return alts ? (parseInt(alts, 10) || 0) : null;
        }
      } catch (e) {
        return null;
      }
      return null;
    }

    function readScore() {
      return readScoreFrom(bridge.score && bridge.score.sel);
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
      } catch (e) { /* ignore */ }
      return false;
    }

    /* ---- game over ---- */
    function finish() {
      if (over) return;
      over = true;
      /* Final score: re-read the authoritative display before submitting.
         score.overSel points at the game-over counter for games that erase
         their on-field display (flappy-burger empties #bigscore and moves
         the total to #currentscore); otherwise the normal score selector
         still holds the final render (2048, memory-match). Fall back to the
         last polled reading when both hold nothing. */
      var cfg = bridge.score || {};
      var finalScore = readScoreFrom(cfg.overSel || cfg.sel);
      if (finalScore === null) finalScore = score;
      score = Math.max(0, finalScore | 0);
      scoreEl.textContent = String(score);
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
      reloading = true;
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

    /* ---- fit-to-card scaler ---- */
    /* Every vendored game lays out at its own natural size (2048 is a fixed
       280px column; the others fill the frame). Sizing the frame to the
       game's own content box and scaling it to "contain" inside the host
       card means the game is NEVER cut off: it grows to fill the card when
       the card is bigger than the game, and shrinks to fit on short
       screens instead of being cropped. Measurement runs on layout boxes
       with the transform cleared (getBoundingClientRect), so re-running it
       is stable. */
    var fit = { w: 0, h: 0 };

    function contentExtent(d) {
      var body, html, cs, i, el;
      var minL = Infinity, minT = Infinity, maxR = 0, maxB = 0, any = false;
      var mt = 0, mb = 0, ml = 0, mr = 0, sw = 0, sh = 0;
      try {
        body = d.body;
        html = d.documentElement;
        if (!body || !html) return null;
        /* layout boxes (offset*), never getBoundingClientRect: elements
           mid-animation (Flappy's splash materialize runs a transform) lie
           about their size through rects and would fit the card wrong */
        for (i = 0; i < body.children.length; i++) {
          el = body.children[i];
          if (!el || el.tagName === "SCRIPT" || el.tagName === "STYLE") continue;
          if (!el.offsetWidth && !el.offsetHeight) continue;
          any = true;
          if (el.offsetLeft < minL) minL = el.offsetLeft;
          if (el.offsetTop < minT) minT = el.offsetTop;
          if (el.offsetLeft + el.offsetWidth > maxR) {
            maxR = el.offsetLeft + el.offsetWidth;
          }
          if (el.offsetTop + el.offsetHeight > maxB) {
            maxB = el.offsetTop + el.offsetHeight;
          }
        }
        if (!any) return null;
        /* auto margins reflow away when the frame shrinks, fixed margins do
           not - only the fixed ones belong in the extent (auto parses as 0) */
        cs = d.defaultView.getComputedStyle(body);
        mt = parseFloat(cs.marginTop) || 0;
        mb = parseFloat(cs.marginBottom) || 0;
        ml = parseFloat(cs.marginLeft) || 0;
        mr = parseFloat(cs.marginRight) || 0;
        /* content that overflows every child box (absolute layers, wrapper
           min-heights): body.scrollHeight catches Flappy's tall splash card
           inside its 100% gamecontainer - html.scrollHeight alone missed it */
        sw = Math.max(html.scrollWidth || 0, body.scrollWidth || 0);
        sh = Math.max(html.scrollHeight || 0, body.scrollHeight || 0);
      } catch (e) { return null; }
      var w = maxR - Math.min(minL, 0) + ml + mr;
      var h = maxB - Math.min(minT, 0) + mt + mb;
      if (sh > html.clientHeight) h = Math.max(h, sh);
      if (sw > html.clientWidth) w = Math.max(w, sw);
      return { w: Math.round(w), h: Math.round(h) };
    }

    function fitFrame(force) {
      var hostW, hostH, ext, again, s, tx, ty;
      if (!doc || !host || !frame) return;
      hostW = host.clientWidth;
      hostH = host.clientHeight;
      if (!hostW || !hostH) return;
      if (!force && hostW === fit.w && hostH === fit.h) return;
      fit.w = hostW;
      fit.h = hostH;
      /* measure at the card box first */
      frame.style.transform = "none";
      frame.style.width = hostW + "px";
      frame.style.height = hostH + "px";
      ext = contentExtent(doc);
      if (!ext || ext.w < 2 || ext.h < 2) return;
      /* then size the frame to the game's own content box */
      frame.style.width = ext.w + "px";
      frame.style.height = ext.h + "px";
      /* sizing to the content can reflow content past that box (fixed
         margins): grow once more to the real overflow before scaling */
      again = contentExtent(doc);
      if (again && (again.w > ext.w || again.h > ext.h)) {
        ext = { w: Math.max(ext.w, again.w), h: Math.max(ext.h, again.h) };
        frame.style.width = ext.w + "px";
        frame.style.height = ext.h + "px";
      }
      /* scale the content box to contain inside the card */
      s = Math.min(hostW / ext.w, hostH / ext.h);
      tx = Math.round((hostW - ext.w * s) / 2);
      ty = Math.round((hostH - ext.h * s) / 2);
      frame.style.transformOrigin = "top left";
      frame.style.transform =
        "translate(" + tx + "px," + ty + "px) scale(" + s + ")";
    }

    /* ---- game document attachment ---- */
    /* The iframe's load event cannot be trusted alone: a cached game page
       can finish loading before this script boots, so a listener attached
       here would register too late, never fire, and leave the bridge
       permanently dark — HUD stuck at 0, game-over never detected, best
       score never saved. attachDoc therefore also runs at boot and
       defensively on every poll tick. It is idempotent and only rewires
       when the frame's document actually changed (which is also how
       restart() re-arms the bridge after reloading the game). */
    function attachDoc() {
      var d = null;
      try { d = frame.contentDocument || null; } catch (e) { d = null; }
      if (!d || d === doc) return;
      doc = d;
      over = false;
      reloading = false;
      try {
        /* first real interaction inside the game counts as "played" */
        doc.addEventListener("pointerdown", markPlayed, { once: true });
        doc.addEventListener("keydown", markPlayed, { once: true });
      } catch (e) { /* ignore */ }
      /* a new game document has its own layout: re-fit it to the card */
      fitFrame(true);
    }

    frame.addEventListener("load", function () {
      attachDoc();
      fitFrame(true);
    });
    attachDoc();
    fitFrame(true);

    /* rotate / resize changes the card box: re-measure after it settles */
    var fitTimer = null;
    function refitSoon() {
      if (fitTimer) window.clearTimeout(fitTimer);
      fitTimer = window.setTimeout(function () { fitFrame(true); }, 150);
    }
    window.addEventListener("resize", refitSoon);
    window.addEventListener("orientationchange", refitSoon);

    window.setInterval(function () {
      attachDoc();
      fitFrame();
      if (!doc || over || reloading) return;
      /* A document that is still parsing lies about visibility: a modal
         marked .hidden is not display:none until its stylesheet applies
         (the class alone does nothing), so the "visible" game-over reader
         would see the modal's layout box mid-load and fire a bogus
         "Game over 0" during every Play again reload. Only trust the DOM
         once the document is no longer loading. */
      if (doc.readyState === "loading") return;
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
