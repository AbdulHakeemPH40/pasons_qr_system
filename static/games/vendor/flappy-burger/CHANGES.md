# Changes to vendored floppybird (Apache-2.0), shipped as "Flappy Burger"

Upstream: github.com/nebez/floppybird (vendored 2026-10-10, licence in
`LICENSE`).

## Code

1. `index.html`: removed the upstream analytics script
   (`https://yummy.nebez.dev/script.js`). Marked with a
   `<!-- Pasons: ... -->` comment at the same spot.
2. `js/main.js`: added a small audio gate (`pasonsAudioUnlocked`). The splash
   screen plays a swoosh sound on page load, before the guest has interacted
   with the page, so browsers' autoplay policy blocked it and logged a console
   error. The gate skips the splash swoosh until the guest's first gesture
   (pointerdown / keydown / touchstart), after which all sounds play normally.
   Change is marked with `Pasons:` comments in the file.
3. `js/main.js` (2026-10-14, liquid-glass pass): credits-link gestures are
   stopped at `#footer` so tapping a credit link never starts the game
   underneath it. Marked with a `Pasons:` comment.

## iOS 26 liquid-glass pass (2026-10-14)

Same design language as Memory Match (`MemoryGame.css`): warm cream canvas,
forest green, gold hairlines, Fraunces display, blur + saturate glass.

- `index.html`: `#splash` is now a liquid-glass card carrying the client's
  chicken-burger photo (`assets/burger-card.jpg`), the Fraunces title and a
  gold "Tap to start" pill. `#scoreboard` is a glass sheet ("Round over",
  medal well, Score/Best rows, green "Play again" pill). Credits are glass
  chips and open in a new tab (`target="_blank" rel="noopener"`), labels
  reworded. `<title>` is now "Flappy Burger".
  **Contract kept:** every id main.js and the platform bridge rely on
  (`#bigscore`, `#scoreboard`, `#medal`, `#currentscore`, `#highscore`,
  `#replay`) and the digit `<img alt>` rows are unchanged.
- `css/main.css`: rewritten around `--fb-*` tokens (mirror of the Memory Match
  `--mm-*` palette). Sky/land/ceiling recolored warm; HUD score is a dark
  forest glass pill; sheet rows use `::before` labels so `.empty()` can never
  remove them; press feedback on `#replay` uses background only (transit
  owns its transform). Materialize + gold pulse motion, plus
  `prefers-reduced-motion` (drift/materialize/pulse off, slides near-instant;
  pipe animation kept, it is the gameplay) and `prefers-reduced-transparency`
  (glass fills go near-solid) fallbacks.
- World keyframes `animSky`/`animLand`/`animCeiling` now step over the full
  tile width of the regenerated art (276 / 336 / 64 px) so the loops are
  seamless; `animLand` is bottom-anchored (`0 100%`). `animPipe`, `animBird`
  and all gameplay geometry are untouched.

## Splash hero: transparent client cutout (2026-10-14)

- `assets/burger-cutout.webp` — NEW: the client's transparent Chicken Burger
  cutout (`Chicken Burger Cutout.png`), alpha-trimmed and resized to 720x592
  WebP (quality 82). It replaces `burger-card.jpg` as the splash hero: the
  burger now floats on the glass card instead of sitting in a photo frame.
- `index.html`: the `.fb-photo` frame is replaced by a `.fb-hero` stage. The
  alt text (`Pasons chicken burger`) and every main.js/bridge id contract
  are kept.
- `css/main.css`: `.fb-hero` carries a warm lens glow behind the cutout and
  a grounded contact shadow below it. The shadow is a gradient ellipse
  (pseudo-element), never `filter: drop-shadow`, following the platform rule
  from the landing-page bfcache ghost-layer bug. A gentle 4s idle float
  (`fbFloat` / `fbFloatShadow`, 6px rise, shadow tightens on lift) animates
  the hero; both animations are disabled under `prefers-reduced-motion`.
- Generator: `.cortex/experiments/process_flappy_cutout.py` (deterministic).

## Sky redesign: visible cloud field with parallax (2026-10-14)

The old `sky.png` baked its clouds into the gradient at 3-6 luminance points
of contrast, so they rendered as invisible smudges. The sky is rebuilt as a
gradient plus a real two-layer cloud field:

- `css/main.css` `#sky` is now a full-height warm CSS gradient
  (cream -> leaf mist -> sage -> deep sage). No tile: the sky fills any
  frame height with no flat band above it and no seam.
- `assets/clouds-far.png` - NEW (276x200 CSS, 552x400 @2x): soft distant
  puffs, drifts slowly (`animCloudsFar`, 16s per 276px loop).
- `assets/clouds-near.png` - NEW (336x150 CSS, 672x300 @2x): bold near
  puffs with warm taupe undersides, drifts faster (`animCloudsNear`, 8s
  per 336px loop). Different speeds give the sky real depth (parallax).
- Both layers are seam-safe (art drawn on a 3x-wide canvas, middle third
  cropped, so blur never breaks the x-wrap), sit behind the pipes/player,
  carry `pointer-events: none`, and use the `.animated` class so the game's
  pause/resume freezes the drift with everything else.
- Keyframes step exactly one tile width (276 / 336 px). `animSky` is gone.
- `prefers-reduced-motion`: both cloud animations are disabled.
- `assets/sky.png` is superseded by the gradient + cloud tiles; kept on
  disk but no longer referenced.
- Generator: `.cortex/experiments/gen_flappy_sky_layers.py` (deterministic;
  draws at 4x, downsamples to 2x for clean soft edges).

### Contrast pass + cache busting (same day, second pass)

The first pass left the far layer faint over the cream upper band
(translucent white on cream = the original bug in milder form). Fixed:

- Cloud bodies are now FULL opacity white; underside rims are deeper warm
  taupe and offset chunkier, so a puff reads against both cream and sage.
- Edge blur reduced (crisper puffs).
- The sky gradient brings sage up earlier (24% / 55% stops instead of
  38% / 72%), so the upper cloud band always has tint behind it.
- Measured live at 390px: cloud contrast now 21.5 (upper) / 60.6 (mid) /
  43.0 (lower) luminance points vs the sky baseline. The original baked
  clouds measured 3-6.
- Cache busting: `index.html` css/js links and the `clouds-*.png` urls in
  main.css carry `?v=2026-10-14-10`, in step with GAMES_V, so a guest's
  browser can never pair stale subresources with fresh markup.

## Visible credits removed (2026-10-14)

At the client's request the on-screen credit chips and the platform credit
line are gone from the guest UI. Licence compliance is unchanged: Apache-2.0
clause 4(c) requires the attribution notices to be retained **in the Source
form**, not displayed on screen, and clause 4(d)'s NOTICE-display rule does
not apply (this work ships no NOTICE file). MIT's notice clause is likewise
satisfied by the licence files travelling with the code. What remains:

- `index.html`: the former `#footer` block is now an HTML comment holding the
  full attribution (Original concept: Dong Nguyen; Engine: Nebez Briefkani;
  Source: github.com/nebez/floppybird).
- `LICENSE` and `static/games/vendor/CREDITS.md` unchanged.
- `js/main.js`: the `#footer` gesture guard (added 2026-10-14 above) was
  removed together with the footer; the audio gate is unaffected.
- `css/main.css`: the `#footer` chip rules were removed.
- Platform: the `game-credit` line was dropped from `templates/games/play.html`
  and its styles from `theme-warm.css`; the hub card still shows the licence
  chip. `apps/games/registry.py` keeps `Game.license` / `Game.credit` as the
  source-form attribution record, and
  `test_visible_credits_removed_but_licence_attribution_retained` locks both
  halves (credit not rendered, attribution still on disk).

## Fit-to-card layout fixes (2026-10-14)

The play card now runs top to bottom, and the game shrinks to fit it instead
of being cut off. Three changes here:

- `css/main.css` `#gamecontainer`: the `min-height: 525px` floor was removed.
  It made the splash card centre inside a box taller than the play card, so
  on short screens the card bottom was cropped. The container is `height:
  100%` and fills its frame exactly.
- `css/main.css` `.fb-card`: `max-width` widened from `284px` to
  `min(340px, 92%)` so the splash fills the bigger game card.
- `css/main.css` `.fb-hero img`: switched to `width: auto; max-width: 88%`
  plus `max-height: min(46vh, 250px)` (aspect-safe, the smaller constraint
  wins) so the burger shrinks on short frames instead of pushing the card
  past it.

The shared shell (`static/games/core/shell.js`) sizes the frame to the game's
own content box and scales it to contain inside the card, so nothing is ever
cropped; it uses layout measurements (`offsetWidth` and friends) because the
splash's `fbMaterialize` transform would otherwise lie about the card's size
mid-animation.

## Assets (required by the licence notes and trademark safety)

The upstream repository ships the original Flappy Bird sprites and sounds,
which are NOT redistributed here. Every file under `assets/` is Pasons-owned
replacement art drawn at the exact pixel sizes the vendored code and CSS
expect, so the game code stays byte-identical:

- `sky.png`, `ceiling.png`, `land.png` — warm cream canvas, gold hairline and
  lettuce-green ground edge (brand palette). Regenerated 2026-10-14 as warm
  gradient sky with soft clouds (276x320), gold-rimmed grass scallops
  (336x48) and a gold ceiling strip (64x16), tile widths matching the
  scroll keyframes. **Superseded the same day** by the CSS gradient sky +
  `clouds-far.png` / `clouds-near.png` (see the sky redesign section);
  `ceiling.png` and `land.png` unchanged and still in use.
- `pipe.png`, `pipe-up.png`, `pipe-down.png` — deep-green columns and caps.
- `bird.png` — three-frame 34x96 sheet of a tilted sesame burger (the flap
  animation cycles the frames exactly as before).
- `splash.png` — "FLAPPY BURGER" title art (no original game logo).
  **Superseded 2026-10-14** by the HTML glass card + `burger-card.jpg`; kept
  on disk but no longer referenced.
- `scoreboard.png`, `replay.png`, `medal_*.png` — warm panel, replay pill and
  plain medal discs. **2026-10-14:** `scoreboard.png` superseded by the CSS
  glass sheet (kept on disk, unreferenced); `replay.png` redrawn as a 24x24
  gold circular-arrow glyph inside the glass pill; `medal_*.png` unchanged.
- `font_big_*.png`, `font_small_*.png` — digit sprites redrawn in cream with a
  forest outline. Regenerated 2026-10-14 as clean glyphs: `font_big` cream
  with forest stroke (dark HUD pill), `font_small` forest (light sheet rows).
- `burger-card.jpg` — 2026-10-14: the client's Chicken Burger photo,
  center-cropped 4:3 to 480x360 (same pipeline as the Memory Match food
  cards), shown on the splash card. **Superseded the same day** by
  `burger-cutout.webp` (transparent cutout hero, see above) and removed;
  regenerable from `process_flappy_splash_photo.py`.
- `sounds/sfx_*.ogg` — short synthesised tones (ffmpeg-generated), replacing
  the original game's sound effects.
- Removed: `font_big.psd`, `font_small.psd`, `thumb.png` (upstream originals,
  unreferenced by the game).
