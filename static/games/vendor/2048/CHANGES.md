# Changes to vendored 2048 (MIT)

Upstream: github.com/gabrielecirulli/2048 (vendored 2026-10-10, licence in
`LICENSE.txt`).

1. `index.html`: removed `target-densitydpi=160dpi` from the viewport meta
   tag. The property is deprecated and makes Chrome log a console warning on
   every load; guest pages of the Pasons platform keep a clean console.
   Layout is unaffected (the game already ships its own mobile media query).

2. `style/main.css` (2026-10-14): the stock marketing text below the board
   is hidden (`display: none`) inside the Pasons play card - the
   "how to play" copy, the upstream site note and the credits paragraphs.
   The board is the point of the card, the platform already explains the
   controls, and the prose doubled the page height so the board could never
   fill its card. Upstream attribution is retained in the source form
   (`LICENSE.txt`, this file, `static/games/vendor/CREDITS.md`) as MIT
   requires. No JavaScript was modified.

3. `index.html` (2026-10-14): every stylesheet and script URL now carries a
   `?v=` cache key. Without it a guest's browser could pair a cached copy of
   the old CSS with a fresh page, so Pasons CSS patches (item 2) would not
   reach returning visitors. The key is bumped whenever a Pasons-side file
   in this folder changes.

No JavaScript was modified.
