/**
 * Score extension (Pasons, see CHANGES.md).
 *
 * The Games Zone shell reads a numeric per-round score through the bridge
 * (registry.py -> "#chess--score", bare digits). Chess has no native score,
 * so this module defines one, in two parts:
 *
 *   1. Capture points, counted live for the HUMAN player only:
 *        pawn 10, knight 30, bishop 30, rook 50, queen 90
 *      The counter climbs during play, which keeps the shell HUD alive.
 *
 *   2. Result bonus, added once at game over:
 *        win  200 x difficulty   (level 3 -> 600 ... level 6 -> 1200)
 *        draw  50 x difficulty   (level 3 -> 150 ... level 6 -> 300)
 *        loss  0
 *      Beating a harder engine scores more, which suits the "tough chess"
 *      brief (levels 3-6 only).
 *
 * Best = best single-game score on the guest's own device, like every other
 * Games Zone title. Pure play: the number never buys anything.
 */

export const PIECE_POINTS = { p: 10, n: 30, b: 30, r: 50, q: 90 };

export class ScoreKeeper {
  constructor(elementId = 'chess--score') {
    this.el = document.getElementById(elementId);
    this.capturePoints = 0;
    this.resultBonus = 0;
    // Ladder extension (Pasons, see CHANGES.md): the Games Zone shell has to
    // know WHICH level was played and WHETHER it was won, because the reward
    // ladder is climbed in order and only a win climbs it. Both are rendered
    // as plain text into small hidden elements the bridge can read. Created
    // here so the vendored markup stays untouched.
    this.levelEl = ScoreKeeper.bridgeElement('chess--level');
    this.resultEl = ScoreKeeper.bridgeElement('chess--result');
    this.render();
  }

  /** A hidden <span id=...> next to the score element, for the bridge. */
  static bridgeElement(id) {
    let el = document.getElementById(id);
    if (el) return el;
    el = document.createElement('span');
    el.id = id;
    el.hidden = true;
    el.style.display = 'none';
    const anchor = document.getElementById('chess--score');
    if (anchor && anchor.parentNode) anchor.parentNode.appendChild(el);
    else document.body.appendChild(el);
    return el;
  }

  /** Points for one captured piece type (p/n/b/r/q). */
  static piecePoints(type) {
    return PIECE_POINTS[type] || 0;
  }

  /** Record a capture made by the human player. */
  addCapture(type) {
    this.capturePoints += ScoreKeeper.piecePoints(type);
    this.render();
  }

  /** Undo support: take one capture back. */
  removeCapture(type) {
    this.capturePoints = Math.max(0, this.capturePoints - ScoreKeeper.piecePoints(type));
    this.render();
  }

  /**
   * Apply the end-of-game bonus.
   * @param {string} result '1-0' | '0-1' | '1/2-1/2'
   * @param {number} difficulty 3-6
   * @param {string} humanColor 'w' | 'b'
   */
  addResultBonus(result, difficulty, humanColor) {
    const level = Math.max(3, Math.min(6, difficulty | 0));
    const humanWon =
      (result === '1-0' && humanColor === 'w') ||
      (result === '0-1' && humanColor === 'b');
    const drawn = result === '1/2-1/2';
    if (humanWon) {
      this.resultBonus = 200 * level;
    } else if (drawn) {
      this.resultBonus = 50 * level;
    } else {
      this.resultBonus = 0;
    }
    // Ladder extension (Pasons): publish the guest-facing level (1-4, which
    // is levelLabel(difficulty) = difficulty - 2) and the outcome. Only a
    // WIN climbs the ladder, so the shell must be able to tell a win from a
    // draw or a loss; the score alone cannot.
    this.setLevel(level - 2);
    this.setResult(humanWon ? 'win' : drawn ? 'draw' : 'loss');
    this.render();
  }

  /** Guest-facing level 1-4, for the ladder. */
  setLevel(displayLevel) {
    this.level = displayLevel | 0;
    if (this.levelEl) this.levelEl.textContent = String(this.level);
  }

  /** 'win' | 'draw' | 'loss', for the ladder. */
  setResult(outcome) {
    this.outcome = outcome || '';
    if (this.resultEl) this.resultEl.textContent = this.outcome;
  }

  /** Total score: capture points + result bonus. */
  total() {
    return this.capturePoints + this.resultBonus;
  }

  /** Reset for a new game. */
  reset() {
    this.capturePoints = 0;
    this.resultBonus = 0;
    this.setLevel(0);
    this.setResult('');
    this.render();
  }

  /** Render bare digits into the bridge element (the shell parseInts it). */
  render() {
    if (this.el) this.el.textContent = String(this.total());
  }
}
