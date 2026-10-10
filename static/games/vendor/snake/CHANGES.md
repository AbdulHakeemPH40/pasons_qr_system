# Changes to vendored Snake (MIT)

Upstream: github.com/patorjk/JavaScript-Snake (vendored 2026-10-10, licence in
`LICENSE`). Shipped as "Snake".

1. `index.html`: removed the upstream Google Tag Manager analytics block
   (`https://www.googletagmanager.com/gtag/js?id=G-1EFCMZ1JX6`, a `gtag`
   loader and its `config` call). Guest pages of the Pasons platform make no
   external network calls; the spot is marked with a `<!-- Pasons: ... -->`
   comment. No game logic was touched: `gtag` was only ever called by that
   removed block.
2. Removed `css/images/Thumbs.db`, a leftover Windows Explorer thumbnail
   cache that shipped with the upstream repository and is referenced by
   nothing.
3. `js/snake.js` (`recordScore`): removed the blocking `alert()` shown on a
   new high score. The host shell already presents the game-over overlay and
   the stored best score, and a native `alert` freezes the guest page (it
   also interrupts the shell's overlay). The score is still saved; the spot
   is marked with a `/* Pasons: ... */` comment.
4. `index.html` (`go_full_screen`): removed the `alert()` in the fullscreen
   error fallback; the existing `console.error(err)` stays. The game is
   embedded in a phone-frame shell with no `allowfullscreen`, so fullscreen
   is intentionally unavailable and this path is a silent no-op.
5. Added `css/dark-snake.css` and `css/green-snake.css`, taken unmodified
   from the upstream repository (`src/css/`). Their images
   (`dark-snakeblock.png`, `dead-dark-snakeblock.png`, and the shared
   `snakeblock.png` / `deadblock.png`) were already shipped here; the two
   files were simply missed when this folder was first copied. The image
   URLs inside them were rewritten from the upstream build paths
   (`src/css/images/...`) to this folder's layout (`./images/...`), matching
   how the vendored `main-snake.css` already references its images.
6. `index.html` (`THEMES`): the dropdown lists 14 community themes, but only
   three have a stylesheet in the upstream repository. The other eleven
   (`light`, `matrix`, `Senura`, `head`, `black`, `neon`, `clean`, `blue`,
   `golden`, `cotton-candy`, `og`) resolve to missing files, so choosing one
   produced a 404 and left the board unstyled. The array now lists only the
   three themes that ship here: Main (default), Dark and Green. The saved
   theme index falls back to the default when it is out of range, so no
   stored preference breaks.

No other JavaScript, CSS or asset was modified.
