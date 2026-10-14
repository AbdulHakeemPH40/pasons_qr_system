# Memory Match — changes from upstream

Upstream: github.com/mmenavas/memory-game (MIT), "Memory Workout" by Maximo
Mena. Vendored unmodified on 2026-10-11. Changes below record every
modification (MIT does not require it; this folder keeps the convention used
by the other vendored games).

## 2026-10-13 — fruit photos replaced with Pasons food cards

The upstream game ships 15 stock fruit photographs in `images/fruits/`.
Those are replaced with Pasons-owned food artwork:

- `images/fruits/` removed.
- `images/food/food-01.jpg` … `food-15.jpg` added (flat brand-style dish
  art generated for this project: mandi, biryani, kebab, shawarma, burger,
  pizza, fries, chicken, salad, soup, fish, hummus, falafel, kunafa, tea).
- `css/MemoryGame.css` — the 15 `.back.card-N` rules now point at
  `../images/food/food-NN.jpg`. The `.back.matching` example comment updated
  to match. No other CSS changes.
- `index.html` — page title and menu-bar name renamed "Fruit Matcher" →
  "Food Matcher".

The game code (`js/MemoryGame.js`, `js/Card.js`, `js/BrowserInterface.js`)
is untouched; `imagesAvailable` stays 15 (the 5x6 grid needs 15 pairs).

### Replacing with real dish photos

The food cards are drop-in placeholders. To use real photos, overwrite
`images/food/food-01.jpg` … `food-15.jpg` with same-aspect images
(4:3, 480×360 or larger, JPG). No code change needed. Keep one dish per
image and make the 15 visually distinct, or pairs become hard to tell apart.
