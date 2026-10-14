/**
 * Chess Master - Game History & Statistics
 * Persists win/loss/draw results to localStorage so they survive app restarts.
 */

const STORAGE_KEY = 'chess-game-history';
const MAX_ENTRIES = 200;

export class GameHistory {
  constructor() {
    this.entries = this._load();
  }

  /** Load history from localStorage */
  _load() {
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  /** Persist history to localStorage */
  _save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.entries));
    } catch (e) {
      console.warn('Could not save game history:', e);
    }
  }

  /**
   * Record a finished game.
   * @param {object} opts
   *   result:     '1-0' | '0-1' | '1/2-1/2'
   *   reason:     'checkmate' | 'resignation' | 'timeout' | 'stalemate' | 'agreement' | ...
   *   mode:       'friend' | 'computer' | 'llm'
   *   humanColor: 'w' | 'b'  (meaningful only in bot modes)
   *   opponent:   display name of the opponent (e.g. 'Stockfish', 'Grok 4.6')
   *   moves:      number of half-moves played
   *   timeControl: string like '10 min' or '5+10'
   */
  record({ result, reason, mode, humanColor, opponent, moves, timeControl }) {
    const entry = {
      id: Date.now(),
      date: new Date().toISOString(),
      result,
      reason,
      mode,
      humanColor,
      opponent: opponent || 'Unknown',
      moves: moves || 0,
      timeControl: timeControl || '',
      outcome: this._computeOutcome(result, mode, humanColor),
    };

    this.entries.unshift(entry); // newest first
    if (this.entries.length > MAX_ENTRIES) {
      this.entries.length = MAX_ENTRIES;
    }
    this._save();
    return entry;
  }

  /**
   * Compute the outcome from the human player's perspective.
   * - Bot modes:  'win' | 'loss' | 'draw'
   * - Friend mode: 'white' | 'black' | 'draw' (no single "human")
   */
  _computeOutcome(result, mode, humanColor) {
    if (result === '1/2-1/2') return 'draw';

    if (mode === 'friend') {
      return result === '1-0' ? 'white' : 'black';
    }

    const humanWon =
      (result === '1-0' && humanColor === 'w') ||
      (result === '0-1' && humanColor === 'b');
    return humanWon ? 'win' : 'loss';
  }

  /** Get all entries (newest first) */
  getAll() {
    return this.entries;
  }

  /**
   * Compute aggregate statistics.
   * Returns { total, draws, whiteWins, blackWins, botGames: { total, wins, losses, draws }, byMode }
   */
  getStats() {
    const stats = {
      total: 0,
      draws: 0,
      whiteWins: 0,
      blackWins: 0,
      botGames: { total: 0, wins: 0, losses: 0, draws: 0 },
      byMode: {},
    };

    for (const e of this.entries) {
      stats.total++;

      if (!stats.byMode[e.mode]) {
        stats.byMode[e.mode] = { total: 0, wins: 0, losses: 0, draws: 0 };
      }
      const m = stats.byMode[e.mode];
      m.total++;

      if (e.outcome === 'draw') {
        stats.draws++;
        m.draws++;
      } else if (e.outcome === 'white') {
        stats.whiteWins++;
      } else if (e.outcome === 'black') {
        stats.blackWins++;
      }

      // Bot-mode record from human perspective
      if (e.mode !== 'friend') {
        stats.botGames.total++;
        if (e.outcome === 'win') { stats.botGames.wins++; m.wins++; }
        else if (e.outcome === 'loss') { stats.botGames.losses++; m.losses++; }
        else { stats.botGames.draws++; }
      }
    }

    return stats;
  }

  /** Clear all history */
  clear() {
    this.entries = [];
    this._save();
  }
}
