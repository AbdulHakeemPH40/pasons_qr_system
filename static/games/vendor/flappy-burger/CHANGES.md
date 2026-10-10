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

No other JavaScript or CSS logic was modified.

## Assets (required by the licence notes and trademark safety)

The upstream repository ships the original Flappy Bird sprites and sounds,
which are NOT redistributed here. Every file under `assets/` is Pasons-owned
replacement art drawn at the exact pixel sizes the vendored code and CSS
expect, so the game code stays byte-identical:

- `sky.png`, `ceiling.png`, `land.png` — warm cream canvas, gold hairline and
  lettuce-green ground edge (brand palette).
- `pipe.png`, `pipe-up.png`, `pipe-down.png` — deep-green columns and caps.
- `bird.png` — three-frame 34x96 sheet of a tilted sesame burger (the flap
  animation cycles the frames exactly as before).
- `splash.png` — "FLAPPY BURGER" title art (no original game logo).
- `scoreboard.png`, `replay.png`, `medal_*.png` — warm panel, replay pill and
  plain medal discs.
- `font_big_*.png`, `font_small_*.png` — digit sprites redrawn in cream with a
  forest outline.
- `sounds/sfx_*.ogg` — short synthesised tones (ffmpeg-generated), replacing
  the original game's sound effects.
- Removed: `font_big.psd`, `font_small.psd`, `thumb.png` (upstream originals,
  unreferenced by the game).
