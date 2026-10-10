# Changes to vendored Hextris (GPL-3.0)

Upstream: github.com/Hextris/hextris (vendored 2026-10-10, licence in
`LICENSE.md`). This modified version remains under GPL-3.0; sources ship in
this folder.

1. `index.html`: removed the Google AdSense script tag
   (`pagead2.googlesyndication.com/pagead/js/adsbygoogle.js`). Guest pages of
   the Pasons platform never carry third-party advertising.
2. `index.html`: removed the Google Fonts stylesheet link
   (`fonts.googleapis.com/css?family=Exo+2`). Guest pages load no external
   resources; the game falls back to its local font stack.
3. `js/main.js`: removed the trailing IIFE that injected the upstream
   analytics script `http://hextris.io/a.js` into the document head. It is
   replaced by a `/* Pasons: ... */` comment at the same spot. No game logic
   was touched; the injector only loaded a remote tracking script.
4. `index.html`: removed the inline Google Analytics loader
   (`//www.google-analytics.com/analytics.js`, property UA-51272720-2).
   Because upstream code calls `ga(...)` in a few places, a no-op
   `window.ga` stub replaces the loader so those calls stay safe.
5. `js/initialization.js`: removed the second Google Analytics loader
   (property UA-51272720-1) and its `ga('create'/'send')` calls, marked
   with a `/* Pasons: ... */` comment at the same spot.
6. `js/main.js`: removed the `$.get('http://54.183.184.126/' + score)` call
   in `checkGameOver()` that reported the final score to a hard-coded
   third-party IP on every game over, replaced by a `/* Pasons: ... */`
   comment. Pure telemetry; local high scores are unaffected.

Apart from the analytics removals above, no JavaScript logic was modified.
The `index.html` removals are marked with `<!-- Pasons: ... -->` comments at
the exact spots. The games load no third-party scripts, fonts or beacons.
