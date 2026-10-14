# Games Zone — open-source credits and licences

The three games in this folder are vendored open-source projects. They run
unmodified except where a per-game `CHANGES.md` says otherwise. Each game
folder keeps the upstream licence file. Nothing here is advertised, tracked
or monetised; the games are pure play while guests wait.

| Game | Folder | Upstream | Licence | Credit line |
|---|---|---|---|---|
| 2048 | `2048/` | github.com/gabrielecirulli/2048 | MIT (`2048/LICENSE.txt`) | 2048 by Gabriele Cirulli, MIT licence |
| Flappy Burger | `flappy-burger/` | github.com/nebez/floppybird | Apache-2.0 (`flappy-burger/LICENSE`) | Flappy-style engine by Nebez Felkner, Apache-2.0; art replaced with Pasons-owned assets |
| Memory Match | `memory-match/` | github.com/mmenavas/memory-game | MIT (`memory-match/LICENSE.txt`) | Memory Game by mmenavas, MIT licence |

Hextris (GPL-3.0) and JavaScript-Snake (MIT) were vendored here earlier and
removed on 2026-10-13 at the client's request. Their sources remain in git
history for licence compliance.

## Licence obligations we honour

- **MIT (2048, Memory Match):** the licence and copyright notice travel
  with the code in each folder.
- **Apache-2.0 (Flappy Burger):** licence kept; changes documented in
  `flappy-burger/CHANGES.md`; the original Flappy Bird artwork and sounds are
  NOT redistributed — every sprite and sound effect here is Pasons-owned
  replacement art generated for this project.

## House rules honoured in every vendored game

- No third-party ad, analytics or font scripts (stripped where upstream had
  them; see per-game CHANGES.md).
- No external network calls from guest pages.
- No personal data collected by the games themselves; best scores live in the
  guest's own localStorage.
