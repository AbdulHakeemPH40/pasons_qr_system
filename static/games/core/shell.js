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
    /* Where this guest stands: the chess ladder rung, or the run of rounds
       behind a dessert. Embedded by the server (apps/rewards), so the climb
       is decided there and this shell only draws it. */
    var progress = {};
    var progressEl = document.getElementById("games-progress");
    if (progressEl) {
      try { progress = JSON.parse(progressEl.textContent) || {}; } catch (e) { progress = {}; }
    }
    var storage = window.GamesStorage || {
      get: function () { return 0; },
      submit: function (s, v) { return v; }
    };

    /* Some games end on a screen of their own that is worth more than our
       result sheet: chess-master names the winner, says how the game ended
       and offers a Review Board button, and the board behind it is exactly
       what a guest wants to study after a loss. For those games (`bridge.
       defer`) the shell builds its result but keeps it CLOSED, and waits in
       a small dock at the bottom edge of the card instead. The guest opens
       the sheet with one tap, when they are ready (client 2026-10-19:
       "no need immediate banner, allow review first"). */
    var defer = bridge.defer === true;
    var dock = null;

    var best = storage.get(slug);
    var score = 0;
    var over = false;
    var played = false;
    var reloading = false;
    var doc = null;
    /* Proof of play, as honest as a browser can make it: how long the round
       ran and how much the guest actually touched it. Both go to the reward
       engine so a one-tap "round" counts for nothing. Neither is proof - a
       bot can fake them - but faking them is the work the engine wants. */
    var startedAt = 0;
    var actions = 0;

    function elapsedSeconds() {
      if (!startedAt) return 0;
      return Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    }

    function noteAction() {
      actions += 1;
      if (!startedAt) startedAt = Date.now();
      markPlayed();
    }

    function paintBest() {
      bestEl.textContent = best > 0 ? "Best " + best : "Best —";
    }

    function exitHref() {
      var b = document.querySelector(".sheet-back");
      return (b && b.getAttribute("href")) || "/";
    }

    /* ---- analytics beacon: GameEvent rows for the play funnel ---- */
    /* Fire-and-forget, so only the "played" signal travels this way. The
       "finished" signal needs its answer read, because the server decides
       whether the round earned a coupon: see claimRound below. */
    function beacon(kind, value) {
      var url = host.dataset.beacon;
      if (!url) return;
      try {
        var body = new FormData();
        body.append("slug", slug);
        body.append("kind", kind);
        body.append("score", String(value | 0));
        if (host.dataset.qr) body.append("qr", host.dataset.qr);
        if (host.dataset.token) body.append("token", host.dataset.token);
        var token = host.dataset.csrf;
        if (token) body.append("csrfmiddlewaretoken", token);
        if (navigator.sendBeacon) navigator.sendBeacon(url, body);
        else fetch(url, { method: "POST", body: body, keepalive: true });
      } catch (e) {
        /* analytics must never break a game */
      }
    }

    /* ---- reward claim: the finished signal, with its answer ----
       sendBeacon cannot read a response, so the finished round goes out as a
       fetch. The round token (embedded by the server in the page) tells the
       backend a play page for this game was really loaded; the per-guest
       cooldown and the per-brand cap are what actually limit the payout. */
    /* A plain-text bridge reader, for the two facts the reward ladder needs:
       which level was played, and how it ended. The score alone cannot tell
       a win from a draw. Returns "" when the game publishes nothing. */
    function readBridgeText(key) {
      var cfg = bridge[key];
      if (!doc || !cfg || !cfg.sel) return "";
      try {
        var el = doc.querySelector(cfg.sel);
        return el ? String(el.textContent || "").trim() : "";
      } catch (e) {
        return "";
      }
    }

    function claimRound(value) {
      var url = host.dataset.beacon;
      if (!url) return null;
      var body = new FormData();
      body.append("slug", slug);
      body.append("kind", "finished");
      body.append("score", String(value | 0));
      /* Proof of play + the ladder facts. All of it is decided server side
         (apps/rewards); sending it is the only way the engine can tell a
         climbed rung from a jumped one. */
      body.append("duration", String(elapsedSeconds()));
      body.append("actions", String(actions));
      body.append("level", readBridgeText("level"));
      body.append("result", readBridgeText("result"));
      if (host.dataset.qr) body.append("qr", host.dataset.qr);
      if (host.dataset.token) body.append("token", host.dataset.token);
      var token = host.dataset.csrf;
      if (token) body.append("csrfmiddlewaretoken", token);
      return fetch(url, {
        method: "POST",
        body: body,
        credentials: "same-origin"
      }).then(function (response) { return response.json(); });
    }

    /* Renders the won coupon into the game-over overlay as the SILVER WIN
       TICKET (client-approved design, 2026-10-16): four cropped corners, a
       dashed tear line with a notch scooped out of both sides, the code ABOVE
       the line and a usage stub below it. One ticket, two faces: a warm gold
       dessert face, and a plain silver discount face where the number is the
       prize. A reward can only be issued to a VERIFIED guest now (name +
       mobile, or Google), so there is no "add your details" nudge here - that
       line lives on the refusal card instead, which is where it is true. */
    function renderReward(box, data) {
      var reward = data.reward || {};
      box.innerHTML = "";
      box.className = "game-reward game-reward--ticket";

      /* Which face: a percentage coupon shows its number, anything else shows
         the prize words. Falls back to reading the label, so a payload with
         no `kind` still draws the right face. */
      var kind = reward.kind || "";
      if (!kind) kind = /%|\boff\b/i.test(reward.label || "") ? "percent" : "dessert";
      var variant = kind === "percent" ? "discount" : "dessert";

      /* The game that was won, and the level for the games that climb. */
      var name = "";
      var title = document.querySelector(".sheet-title");
      if (title) name = (title.textContent || "").trim();
      var level = readBridgeText("level");
      if (level) name = (name ? name + " - Level " : "Level ") + level;

      var shell = document.createElement("div");
      shell.className = "game-reward__shell";
      shell.setAttribute("data-variant", variant);
      var ticket = document.createElement("article");
      ticket.className = "game-reward__ticket";
      ticket.setAttribute("data-variant", variant);
      ticket.setAttribute("aria-live", "polite");

      ticket.innerHTML =
        '<div class="game-reward__brushed" aria-hidden="true"></div>' +
        '<div class="game-reward__sheen" aria-hidden="true"></div>' +
        '<div class="game-reward__body">' +
          '<header class="game-reward__top">' +
            '<span class="game-reward__brand">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
                '<circle cx="12" cy="12" r="9"></circle>' +
                '<path d="M8.5 13.5c1 1.6 2.2 2.4 3.5 2.4s2.5-.8 3.5-2.4"></path>' +
                '<circle cx="9.2" cy="10" r="0.9" fill="currentColor" stroke="none"></circle>' +
                '<circle cx="14.8" cy="10" r="0.9" fill="currentColor" stroke="none"></circle>' +
              '</svg>Pasons Group</span>' +
            '<span class="game-reward__game"></span>' +
          '</header>' +
          '<div class="game-reward__prizeblock">' +
            '<p class="game-reward__kicker">You won</p>' +
            '<p class="game-reward__value"></p>' +
            '<p class="game-reward__sub"></p>' +
          '</div>' +
          '<div class="game-reward__codewrap">' +
            '<div><p class="game-reward__codelabel">Your code</p>' +
            '<p class="game-reward__codevalue"></p></div>' +
            '<span class="game-reward__seal" aria-hidden="true">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="#7A5E17" stroke-width="1.5" ' +
              'stroke-linecap="round" stroke-linejoin="round">' +
                '<path d="M12 3.2l2.3 4.9 5.2.7-3.8 3.7.95 5.3L12 15.3 7.35 17.8l.95-5.3L4.5 8.8l5.2-.7z"></path>' +
              '</svg></span>' +
          '</div>' +
        '</div>' +
        '<div class="game-reward__perf" aria-hidden="true"></div>' +
        '<footer class="game-reward__stub">' +
          '<div><p class="game-reward__stublabel">How to use</p>' +
          '<p class="game-reward__stubcopy">Show this code to our staff before you pay</p></div>' +
          '<div class="game-reward__stubaside">' +
            '<p class="game-reward__stubvalid"></p>' +
            '<p class="game-reward__stubfine">one use only</p>' +
          '</div>' +
        '</footer>';

      ticket.querySelector(".game-reward__game").textContent = name || "Games Zone";
      if (kind === "percent") {
        var pct = parseInt(reward.percent, 10);
        if (!pct) {
          var m = String(reward.label || "").match(/\d+/);
          pct = m ? parseInt(m[0], 10) : 0;
        }
        ticket.querySelector(".game-reward__value").innerHTML =
          pct + '<span class="pct">%</span> <em>off</em>';
        ticket.querySelector(".game-reward__sub").textContent =
          "your whole bill, food and drinks";
      } else {
        var words = document.createElement("em");
        words.textContent = reward.label || "Free dessert";
        ticket.querySelector(".game-reward__value").appendChild(words);
        ticket.querySelector(".game-reward__sub").textContent =
          "chef's pick of the day, on the house";
      }
      ticket.querySelector(".game-reward__codevalue").textContent = reward.code || "";
      /* Validity read from the real expiry, so the stub cannot go stale. */
      var valid = "Valid 14 days";
      if (reward.expires_at) {
        var days = Math.round(
          (new Date(reward.expires_at).getTime() - Date.now()) / 86400000
        );
        if (days >= 1) valid = "Valid " + days + " day" + (days === 1 ? "" : "s");
      }
      ticket.querySelector(".game-reward__stubvalid").textContent = valid;

      shell.appendChild(ticket);
      box.appendChild(shell);
      box.hidden = false;

      /* Reveal + pointer tilt, the motion the client approved in the draft. */
      if (window.requestAnimationFrame) {
        requestAnimationFrame(function () { ticket.classList.add("is-in"); });
      } else {
        ticket.classList.add("is-in");
      }
      var reduce = window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      var fine = window.matchMedia &&
        window.matchMedia("(pointer: fine)").matches;
      if (fine && !reduce && window.requestAnimationFrame) {
        var targetRX = 0, targetRY = 0, curRX = 0, curRY = 0, rafId = 0;
        var maxTilt = 7;
        var tick = function () {
          curRX += (targetRX - curRX) * 0.12;
          curRY += (targetRY - curRY) * 0.12;
          ticket.style.transform =
            "rotateX(" + curRX.toFixed(2) + "deg) rotateY(" + curRY.toFixed(2) + "deg)";
          if (Math.abs(targetRX - curRX) > 0.01 || Math.abs(targetRY - curRY) > 0.01) {
            rafId = window.requestAnimationFrame(tick);
          } else {
            rafId = 0;
          }
        };
        shell.addEventListener("pointermove", function (e) {
          if (e.pointerType && e.pointerType !== "mouse") return;
          var r = ticket.getBoundingClientRect();
          targetRY = ((e.clientX - r.left) / r.width - 0.5) * maxTilt * 2;
          targetRX = -((e.clientY - r.top) / r.height - 0.5) * maxTilt * 2;
          if (!rafId) rafId = window.requestAnimationFrame(tick);
        });
        shell.addEventListener("pointerleave", function () {
          targetRX = 0;
          targetRY = 0;
          if (!rafId) rafId = window.requestAnimationFrame(tick);
          ticket.style.animationPlayState = "running";
        });
        shell.addEventListener("pointerenter", function () {
          ticket.style.animationPlayState = "paused";
        });
      }
    }

    /* No reward, so say why and where the guest now stands. The climb IS the
       rule, so a refusal that says nothing would just read as a broken game.
       Text only, same card, never louder than the win. */
    function renderProgress(box, data) {
      if (!data || !data.message) return;
      box.innerHTML = "";
      var note = document.createElement("p");
      note.className = "game-reward__hint";
      note.textContent = data.message;
      box.appendChild(note);

      var p = data.progress || {};
      var line = "";
      if (p.mode === "ladder" && p.levels) {
        line = "Level " + (p.rung || 1) + " of " + p.levels + " unlocked.";
      }
      if (line) {
        var where = document.createElement("p");
        where.className = "game-reward__tag";
        where.textContent = line;
        box.appendChild(where);
      }
      if (data.verified === false) {
        /* A refusal is the one moment the guest is TOLD they cannot be paid,
           so the form belongs here, not on another page. This used to be a
           plain link to the QR landing page: tapping it walked the guest out
           of a finished round and dropped them on the QR page, where only the
           Instagram card opened the sheet. That is why the sign-in felt
           Instagram-only (reported 2026-10-17).

           The play page already carries the sheet (.ig-draw), and it sits at
           z-index 50 over this overlay at z-index 2, so the control opens the
           form in place and the round stays on screen behind it. A play page
           loaded without a QR has no sheet and no form action, so there the
           link comes back rather than a button that cannot finish. */
        var hasSheet = !!document.querySelector(".ig-draw");
        var nudge;
        if (hasSheet) {
          nudge = document.createElement("button");
          nudge.type = "button";
          nudge.setAttribute("data-id-open", "form");
        } else {
          nudge = document.createElement("a");
          nudge.href = exitHref();
        }
        nudge.className = "game-reward__nudge";
        nudge.textContent = "Add your name and mobile to claim rewards";
        box.appendChild(nudge);
      }
      box.hidden = false;
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

    /* The dock: a finished result waiting for the guest, on games whose own
       end screen deserves the screen first. Bottom edge of the card, out of
       the way of the board, one tap away from the full result. */
    function removeDock() {
      if (dock && dock.parentNode) dock.parentNode.removeChild(dock);
      dock = null;
    }

    function setDock(main, go, won) {
      if (!dock) return;
      var label = dock.querySelector(".game-dock__main");
      var action = dock.querySelector(".game-dock__go");
      if (label) label.textContent = main;
      if (action) action.textContent = go;
      dock.dataset.state = won ? "won" : "done";
      dock.setAttribute("aria-label", main + ", " + go);
    }

    function showDock() {
      removeDock();
      dock = document.createElement("button");
      dock.type = "button";
      dock.className = "game-dock";
      dock.dataset.state = "done";
      var main = document.createElement("span");
      main.className = "game-dock__main";
      var go = document.createElement("span");
      go.className = "game-dock__go";
      dock.appendChild(main);
      dock.appendChild(go);
      dock.addEventListener("click", openResult);
      host.appendChild(dock);
      setDock(score + (score === 1 ? " point" : " points"), "See result");
    }

    function openResult() {
      if (!over) return;
      removeDock();
      overlay.dataset.state = "over";
      overlay.scrollTop = 0;
    }

    /* Builds the result sheet into the (hidden) overlay and returns its
       reward slot, so the caller decides WHEN the guest sees it. */
    function buildResult() {
      overlay.innerHTML = "";
      /* How the round ended, when the game publishes it (chess-master does:
         win / draw / loss). A loss and a win must not read the same: "Game
         over" over a lost game told the guest nothing about what happened. */
      var outcome = readBridgeText("result");
      var heading = "Game over";
      if (outcome === "win") heading = "You won";
      else if (outcome === "draw") heading = "Draw";
      else if (outcome === "loss") heading = "You lost";
      var t = document.createElement("p");
      t.className = "game-overlay__title";
      t.textContent = heading;
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

      /* Reward slot. Left empty and hidden until the server answers, so the
         game-over screen is never held back waiting on the network, and a
         failed claim simply shows the ordinary overlay. */
      var prizeBox = document.createElement("div");
      prizeBox.className = "game-reward";
      prizeBox.hidden = true;
      overlay.appendChild(prizeBox);
      return prizeBox;
    }

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
      /* One request carries both the finished signal and the reward claim. */
      var claim = claimRound(score);
      var prizeBox = buildResult();

      if (defer) {
        /* Leave the sheet closed: the game's own end screen owns this
           moment, and the board behind it stays readable. */
        showDock();
      } else {
        overlay.dataset.state = "over";
      }

      if (claim) {
        claim
          .then(function (data) {
            if (!data) return;
            /* A win shows the coupon. Anything else shows why not, and where
               the guest now stands on the climb. */
            if (data.reward) {
              renderReward(prizeBox, data);
              /* On a deferred game the dock is the only thing on screen, so
                 the win has to reach it. A prize waiting behind a tap the
                 guest does not know about is a prize they never see. */
              if (defer) {
                setDock(
                  "You won " + (data.reward.label || "a prize"),
                  "Open ticket",
                  true
                );
              }
            } else {
              renderProgress(prizeBox, data);
            }
            if (data.progress) paintLadder(data.progress);
          })
          .catch(function () {
            /* a reward must never break the game-over screen */
          });
      }
    }

    /* A deferred result never blocks the game, so the guest can start another
       round from the game's OWN end screen (chess: "New Game"). That path
       never touches this shell, so the finished round has to be recognised
       as over: the game-over UI is gone AND the result marker the game
       publishes is cleared again. "Review Board" only hides the modal and
       keeps the marker, which is exactly how the two are told apart. Without
       this the second round could never end. */
    function resetRound() {
      over = false;
      played = false;
      score = 0;
      scoreEl.textContent = "0";
      startedAt = 0;
      actions = 0;
      overlay.dataset.state = "hidden";
      overlay.innerHTML = "";
      removeDock();
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
      /* a fresh round is a fresh proof of play */
      startedAt = 0;
      actions = 0;
      overlay.dataset.state = "hidden";
      overlay.innerHTML = "";
      removeDock();

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

    /* ---- the pre-game prompt (a guest who is not verified) ---- */
    /* Shown before the game starts and never in its way: one tap drops it
       and the game has been running underneath the whole time. Client rule
       2026-10-16: playing is open to everyone at every level, this only says
       what verifying is worth. */
    var nudge = document.getElementById("game-nudge");
    var nudgeClose = document.getElementById("game-nudge-close");
    if (nudge && nudgeClose) {
      nudgeClose.addEventListener("click", function () {
        if (nudge.parentNode) nudge.parentNode.removeChild(nudge);
      });
    }

    /* ---- ladder locking (the chess setup modal) ---- */
    /* The guest-facing level is `levelAttr` minus `levelOffset`, and any
       level above the unlocked rung is disabled. A courtesy only: the server
       refuses the claim again at the end of the round (apps/rewards), so the
       UI can never unlock a rung on its own. */
    function applyLadder() {
      var cfg = bridge.lock;
      if (!cfg || !cfg.sel || !doc) return;
      var rung = parseInt(progress.rung, 10) || 1;
      var offset = parseInt(cfg.levelOffset, 10) || 0;
      var attr = cfg.levelAttr || "data-level";
      var els;
      try { els = doc.querySelectorAll(cfg.sel); } catch (e) { return; }
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        var raw = parseInt(el.getAttribute(attr), 10);
        if (isNaN(raw)) continue;
        var locked = raw - offset > rung;
        if ("disabled" in el) el.disabled = locked;
        el.setAttribute("aria-disabled", locked ? "true" : "false");
        el.style.opacity = locked ? "0.35" : "";
        el.style.cursor = locked ? "not-allowed" : "";
        /* keep the vendored tooltip when unlocked, replace it when locked */
        if (el.getAttribute("data-pasons-title") === null) {
          el.setAttribute("data-pasons-title", el.getAttribute("title") || "");
        }
        el.setAttribute(
          "title",
          locked
            ? "This level is not open yet."
            : el.getAttribute("data-pasons-title")
        );
      }
    }

    /* ---- where this guest stands on the climb ---- */
    function paintLadder(p) {
      var el = document.getElementById("game-ladder");
      if (!el) return;
      p = p || progress;
      var text = "";
      if (p.mode === "ladder" && p.levels) {
        text = "Level " + (parseInt(p.rung, 10) || 1) + " of " + p.levels + " unlocked.";
      }
      if (!text) {
        el.hidden = true;
        el.textContent = "";
        return;
      }
      el.textContent = text;
      el.hidden = false;
    }
    paintLadder(progress);

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
        /* Every real interaction counts, not just the first one: the reward
           engine needs to see that the round was played out. pointerdown and
           keydown only - hover, focus and scrolling are not playing. */
        doc.addEventListener("pointerdown", noteAction);
        doc.addEventListener("keydown", noteAction);
      } catch (e) { /* ignore */ }
      /* a new game document has its own layout: re-fit it to the card */
      fitFrame(true);
      /* and its own setup screen: re-apply the ladder lock to it */
      applyLadder();
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
      if (!doc || reloading) return;
      /* A document that is still parsing lies about visibility: a modal
         marked .hidden is not display:none until its stylesheet applies
         (the class alone does nothing), so the "visible" game-over reader
         would see the modal's layout box mid-load and fire a bogus
         "Game over 0" during every Play again reload. Only trust the DOM
         once the document is no longer loading. */
      if (doc.readyState === "loading") return;
      if (over) {
        /* A finished round on a deferred game can be followed by another one
           started from the game's own end screen, which this shell never
           sees. Watch for that here, or the second round could never end. */
        if (defer && !readBridgeText("result")) resetRound();
        return;
      }
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
