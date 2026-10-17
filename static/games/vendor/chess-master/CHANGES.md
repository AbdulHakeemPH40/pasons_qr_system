# Chess Master - port changes

Source: the client's Electron desktop app (`chess_electron/` in this repo),
ported to run as a static page inside the Games Zone same-origin iframe.
Upstream projects vendored inside it are unchanged except where listed below.

## Client brief (2026-10-14)

Mobile version only. No play-vs-friend, no play-vs-AI-model. Stockfish only,
difficulty levels 3-6 only (tough game). Same colours and same assets as the
Electron app.

## What was removed vs the Electron app

- **vs Friend mode** (local two-player) and its board logic paths.
- **vs AI Model (LLM) mode** entirely: `js/llm-engine.js`, the AI Settings
  modal (provider / model / API key), `chess-llm-settings` localStorage and
  every provider label. No network calls remain in the game.
- **Welcome mode-picker** (friend / computer / llm cards). The New Game modal
  is the start screen now.
- **Copy PGN button** (clipboard access is unreliable inside the iframe and
  the move list is visible in the drawer).
- The desktop split layout (sidebar next to the board); the sidebar is a
  mobile bottom-sheet drawer only.

## What was changed

- **Ladder extension (`js/score.js`, 2026-10-16).** The Games Zone reward
  ladder is climbed in order and only a WIN climbs it, so the shell has to
  know which level was played and how the game ended. `ScoreKeeper` now
  publishes both as plain text in two hidden spans it creates itself
  (`#chess--level` = the guest-facing level 1-4, `#chess--result` =
  `win` | `draw` | `loss`), written in `addResultBonus` and cleared in
  `reset`. The vendored markup and game logic are untouched; the shell reads
  them through the bridge in `apps/games/registry.py`. This is an
  observation only: nothing in the game knows about rewards.
- **Difficulty presets trimmed to 3-6** (`js/engine.js` DIFFICULTY_LEVELS:
  Club ~1600, Advanced ~2000, Expert ~2500, Master ~3000+). Looked up by id
  (`difficultyById`), so no code path can select a softer level.
- **Level labels shown as 1-4** (`js/ui.js` `levelLabel`): the guest reads
  Level 1-4 while the engine keeps its difficulty ids 3-6 (display 1 = Club
  ~1600 ... display 4 = Master ~3000+). UI-only renumbering: `data-diff`,
  `DIFFICULTY_LEVELS`, Skill Level, movetime and the score bonus are
  untouched. Every visible "Lv N" (player bar, mode indicator, history
  opponent) goes through the one `levelLabel` helper.
- **Worker URL** (`js/engine.js`): the Electron app created the Stockfish
  Worker from a bare relative string, which browsers resolve against the
  document, not the module; it only worked there because of the Electron
  protocol setup. Now `new URL('../lib/stockfish/stockfish.js', import.meta.url)`
  - module-relative and correct from any nesting.
- **FEN fixture hook** (`js/game.js` reset(fen) + `js/app.js`): optional
  `?autostart=1&level=N&color=w|b&fen=...` query seeds a position and skips
  the setup modal, so browser tests can drive deterministic scenarios
  (mate-in-1, free-capture). Normal loads never see it.
- **Cancel button on the setup modal** (`js/app.js`): the handler was gated
  behind `if (this.gameStarted)`, so on the start screen (no game running yet)
  tapping Cancel did nothing. It now always dismisses the modal: mid-game that
  returns to the running game, on the start screen it reveals the idle board
  (status "Set up a game to start") with the New Game button ready to reopen.
- **Header "New Game" button** (`css/styles.css` `#btn-new-game`): the label
  wrapped to two lines whenever the header got tight, which made the button
  look oversized. Now a compact one-line action (13px, `7px 12px`, `nowrap`,
  `flex-shrink:0`), scoped by ID so the full-size modal CTAs (Start Game, New
  Game rematch) keep their larger padding. Also frees room so the "Chess
  Master" title is no longer truncated.
- **Cache keys** (`index.html`): the stylesheet and the module entry, plus the
  nine `import` specifiers in `js/app.js`, now carry `?v=2026-10-14-19`. ES
  modules cache per specifier, so a stale `app.js` previously kept returning
  guests on old logic. The stable libs in `lib/` are left unversioned. Keep
  this in step with `GAMES_V` in `templates/games/play.html`.

## Pasons score extension (`js/score.js`)

The Games Zone shell reads a numeric per-round score through a bridge element.
Chess has none natively, so the game renders one into `#chess--score`:

- capture points for the HUMAN player: pawn 10, knight 30, bishop 30,
  rook 50, queen 90 (climbs live during play);
- result bonus at game over: win = 200 x level, draw = 50 x level (levels
  3-6), loss = 0.

Best score behaviour matches every other Games Zone title (best single-game
score on the guest's own device).

## Unchanged from the Electron app

- `lib/chess.js` (chess.js, BSD-2, Jeff Hlywa) - untouched.
- `lib/chess.js.map` (added 2026-10-17) - the build ends with a
  `sourceMappingURL` comment but ships no map, and Django's
  `collectstatic` aborts the whole manifest when a referenced file is
  missing. This empty, valid map satisfies the reference. No game code
  was changed.
- `lib/stockfish/stockfish.js` + `stockfish.wasm` (Stockfish.js 18, GPLv3,
  nmrugg/stockfish.js) - untouched. The engine loads its WASM from its own
  folder; no external network calls.
- `assets/pieces/*.svg` (Cburnett standard piece set) and `assets/chess_logo.png`
  - the same art assets.
- `js/board.js`, `js/game.js` rules handling, `js/clock.js`, `js/moves.js`,
  `js/sound.js`, `js/history.js` - carried over (history is device-local
  localStorage only).
- The colour palette (`css/styles.css` tokens: #312E2B chrome, #EBECD0 /
  #739552 board) - same theme.

## House rules honoured

- No third-party ad, analytics or font scripts.
- No external network calls from the guest page.
- No personal data; history and best score live in the guest's own
  localStorage.
