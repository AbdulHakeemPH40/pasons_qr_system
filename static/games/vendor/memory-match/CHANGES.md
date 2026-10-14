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

## 2026-10-14 — real dish photos, 14-image pool

The generated placeholder cards are replaced with 14 client-supplied dish
photos (source originals live outside the repo in `static/img/games_images/`,
kept locally only). Each photo is center-cropped to 4:3 and resized to
480×360 JPG by `.cortex/experiments/process_food_images.py`.

- `images/food/food-01.jpg` … `food-14.jpg` overwritten with the photos.
- `images/food/food-15.jpg` removed (only 14 dishes supplied).
- `js/BrowserInterface.js` — `imagesAvailable` 15 → 14. The old `5x6` board
  needs 15 pairs; with a 14-image pool `getRandomCardValue` would never find
  a free value and the tab would hang.
- `index.html` — "Don't do it!" grid `5x6` (15 pairs) → `7x4` (14 pairs).
  7 rows × 4 columns also gives bigger tiles on portrait phones (4 columns
  of ~97px instead of 6 of ~65px).
- `css/MemoryGame.css` — the `.back.card-15` rule removed.

Card mapping after the 2026-10-14 removal (deterministic, alphabetical by
source filename):

| Card | Dish |
|---|---|
| food-01 | Chicken Burger |
| food-02 | Chicken Fried Rice Bowl |
| food-03 | Fish mangi curry |
| food-04 | Garli Fish |
| food-05 | Gulab Jamun |
| food-06 | Idlis and Chutneys |
| food-07 | Masala Chai |
| food-08 | Mushroom Soup |
| food-09 | Paneer Curry |
| food-10 | Sandwiches |
| food-11 | Shrimp Sandwich |
| food-12 | paneer masala |

2026-10-14 (second pass): the client asked to drop **Ginger fish** (old
food-05, it looked too similar to Garli Fish at card size) and **Mutton
Biryani** (old food-10). The game ran on 12 dishes until the replacements
arrived:

- `images/food/` renumbered contiguously to `food-01.jpg` … `food-12.jpg`
  (the value pool in `MemoryGame.js` is numeric 1..N, so gaps are not
  possible).
- `js/BrowserInterface.js` — `imagesAvailable` 14 → 12.
- `index.html` — "Don't do it!" grid `7x4` (14 pairs) → `6x4` (12 pairs).
- `css/MemoryGame.css` — the `.back.card-13` and `.back.card-14` rules
  removed.
- Source originals `Mutton Biryani.png` and `Ginger fish.png` deleted from
  `static/img/games_images/`.

2026-10-14 (third pass): the two replacement dishes arrived — **Avocado
Blend** and **Mango Dessert** — and were swapped in as promised:

- `images/food/food-13.jpg` (Avocado Blend) and `food-14.jpg` (Mango
  Dessert) added, 4:3 center-crop, 480×360 JPG. The two are appended
  rather than re-alphabetised into the pool so the existing food-01..12
  mapping table above stays valid. Re-run
  `.cortex/experiments/process_food_images.py` to regenerate all 14
  (deterministic; the original 12 come out byte-identical).
- `js/BrowserInterface.js` — `imagesAvailable` 12 → 14.
- `index.html` — "Don't do it!" grid `6x4` (12 pairs) → `7x4` (14 pairs).
- `css/MemoryGame.css` — `.back.card-13` and `.back.card-14` rules restored.

Final card mapping (14 pairs):

| Card | Dish |
|---|---|
| food-01 | Chicken Burger |
| food-02 | Chicken Fried Rice Bowl |
| food-03 | Fish mangi curry |
| food-04 | Garli Fish |
| food-05 | Gulab Jamun |
| food-06 | Idlis and Chutneys |
| food-07 | Masala Chai |
| food-08 | Mushroom Soup |
| food-09 | Paneer Curry |
| food-10 | Sandwiches |
| food-11 | Shrimp Sandwich |
| food-12 | paneer masala |
| food-13 | Avocado Blend |
| food-14 | Mango Dessert |

2026-10-14 (fourth pass): **points and countdown timer** added on request.
The upstream game scores accuracy at the end ("Score: X / 100") and has no
clock. Both now live inside the game model and UI.

Scoring rules (`js/MemoryGame.js`):

- A matched pair is +100 points.
- Each consecutive match after the first adds a streak bonus of +25,
  capped at +100 per match (so matches five and beyond pay +200).
- A mismatch is -25 points (never below 0) and resets the streak.
- Clearing the board before the clock expires adds +15 per whole second
  left (the time bonus). A round that runs out of time keeps the points
  earned but gets no bonus. The bonus is paid once per round.
- `MemoryGame.points`, `MemoryGame.streak`, `MemoryGame.bestStreak`,
  `MemoryGame.addTimeBonus(seconds)` and `MemoryGame.timeUp()` are new.
  The end modal shows points, matched pairs, attempts and best streak.

Countdown rules (`js/BrowserInterface.js`, `index.html`):

- Time budget is 15 seconds + 15 seconds per pair: Easy (2x3) 1:00,
  Medium (3x4) 1:45, Hard (4x5) 2:45, "Don't do it!" (7x4) 3:45. Each
  difficulty option shows its budget in the picker before the guest
  starts.
- The menu bar shows a "Time" chip and a "Pts" chip next to the gear.
  The last 10 seconds turn the timer red with a gentle pulse (disabled
  under prefers-reduced-motion).
- The timer pauses while the page is hidden (tab switch, phone call,
  waiter), so a backgrounded phone never loses the round.
- On expiry the round ends with "Time's up!" and the points earned. On a
  win the modal reports the time bonus. Both paths show the end-game
  modal, so the platform shell picks up game-over as before.

Bug fixed along the way: upstream kept the per-turn flip state
(`cardSelection`, `revealedCards`, `revealedValues`) in a `play()`
closure that `initialize()` never reset. Restarting mid-round via the
gear could therefore end a fresh game early (the old matched count
carried over) or count phantom mistakes. The state now lives on the
model (`_selection`, `_matched`, `_seenValues`) and is reset with
`resetRoundState()` on every new game.

Platform integration:

- The shell HUD score now reads `#memory--points` (bridge kind "text")
  instead of counting revealed cards, so the best score on the phone is
  a best points total. Old pair-count bests are simply replaced on the
  next finished round.
- The page's own script and stylesheet tags now carry a `?v=` version
  (matched to `GAMES_V` in `templates/games/play.html`). Without it a
  guest's browser could serve a stale cached `MemoryGame.js` while
  loading the fresh interface, which breaks the round silently. Bump
  both together whenever the game changes.
- The "objects" bridge kind is gone from `static/games/core/shell.js`
  (nothing used it after this change).
- `apps/games/tests.py` locks the new bridge contract and the visible
  time budgets on the difficulty picker.

## 2026-10-14 — iOS 26 liquid-glass UI and motion pass

The game surface is restyled to the platform's liquid-glass design
language (`static/css/tokens.css`): deep-green felt board, frosted glass
tiles and sheets, gold hairline rims, spring motion. It runs in a
same-origin iframe and cannot inherit the platform CSS, so the glass
recipe is re-declared inside `MemoryGame.css` with the same values.

- `css/MemoryGame.css` — rewritten around the glass recipe. The board is a
  deep-green felt gradient matching the shell's `.game-host` (the iframe
  seam disappears); the bottom bar is a frosted glass strip (blur +
  saturate, bright top edge) with cream text; time/points chips get
  tracked caps labels and tabular numerals; the gear sits in a frosted
  circle; the settings and end-game modals are light liquid-glass sheets
  (blur 22 / saturate 180, 26px radius) over a dark scrim, materialising
  with a scale + fade spring instead of a bare fade. Structural selectors
  and the layout math the JS depends on are unchanged (flip-container
  float grid, .flipper 90%/5%, `.clicked` flip contract, `.back.card-N`).
- `images/card.svg` — the face-down tile is redrawn: frosted white-glass
  gradient with a warm sheen, gold hairline rim, bright top edge, and the
  question monogram embossed in deep green (was the upstream orange
  gradient with a flat white "?").
- Motion (all CSS classes driven by the existing status codes):
  - **deal-in** — a fresh board staggers in (28ms per card, capped) when
    the game starts; a resize re-layout does not re-deal.
  - **match** — a matched pair rings in gold with a warm glow (persistent
    through re-layouts) and settles with a one-shot spring pop
    (`.just-matched`, dropped on re-layout so it never replays).
  - **miss** — a missed pair gets a brief shake and a warm red ring for
    the 1s it stays face up.
  - **press** — tiles scale down on pointer-down (110ms), the button and
    gear likewise.
- `js/MemoryGame.js` — `status.args` is now set on the match path (codes 2
  and 4) as well as the miss path, so the interface knows which pair to
  ring. One line; no scoring or game-rule changes.
- `js/BrowserInterface.js` — adds/removes the `matched` / `just-matched` /
  `miss` / `deal-in` classes, keeps a `matchedSet` of matched indices so
  the gold ring survives a resize re-layout, and clears it on each new
  game. `buildLayout()` takes a `fresh` flag (true on start, false on
  resize). Flip timing, scoring, timer and modal logic are untouched.
- `index.html` — the gear anchor gets the `memory--gear-btn` glass-circle
  class and an alt text. All IDs and the difficulty time-budget strings
  are byte-identical (locked by `apps/games/tests.py`).

Accessibility: `prefers-reduced-motion` drops the deal-in, pop, shake,
press scaling and the timer pulse (flips switch state instantly, the game
stays fully playable); `prefers-reduced-transparency` swaps every glass
surface for a near-solid fill with no backdrop blur. The display face is
the platform's Fraunces (served from `/static/fonts/`, same-origin — no
external requests).
