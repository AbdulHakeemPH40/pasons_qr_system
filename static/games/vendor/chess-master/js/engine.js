/**
 * Stockfish Engine Wrapper
 * Communicates with Stockfish WASM via Web Worker using UCI protocol.
 * Provides a clean async API for getting the best move.
 *
 * Pasons port notes (see CHANGES.md):
 * - Only difficulty levels 3-6 are offered (tough game, client request);
 *   the preset list below is trimmed to exactly those four entries and
 *   looked up by id, so no code path can reach a softer level.
 * - The Worker URL is built from import.meta.url. The Electron original
 *   passed a bare relative string, which the browser resolves against the
 *   DOCUMENT, not this module, and that only worked there because the page
 *   sat next to the lib folder. Module-relative resolution is correct from
 *   any nesting.
 */

/** Difficulty presets mapping to Stockfish Skill Level + movetime (3-6 only) */
export const DIFFICULTY_LEVELS = [
  { id: 3, name: 'Club',    skillLevel: 6,  moveTime: 600,  elo: '~1600' },
  { id: 4, name: 'Advanced', skillLevel: 10, moveTime: 1000, elo: '~2000' },
  { id: 5, name: 'Expert',  skillLevel: 15, moveTime: 2000, elo: '~2500' },
  { id: 6, name: 'Master',  skillLevel: 20, moveTime: 3000, elo: '~3000+' },
];

/** Preset for a difficulty id (3-6); falls back to the lowest offered level. */
export function difficultyById(id) {
  return DIFFICULTY_LEVELS.find((d) => d.id === id) || DIFFICULTY_LEVELS[0];
}

export class StockfishEngine {
  constructor() {
    this.worker = null;
    this.ready = false;
    this.searching = false;
    this.onBestMove = null;    // callback(move)
    this.onInfo = null;        // callback(infoString)
    this._pendingResolve = null;
    this._messageQueue = [];
  }

  /** Initialize the Stockfish Web Worker */
  async init() {
    if (this.worker && this.ready) return;

    return new Promise((resolve, reject) => {
      try {
        // Module-relative worker URL: stockfish.js sits next to this file's
        // parent in lib/stockfish/, and loads stockfish.wasm from its own
        // folder (no external network calls).
        const workerUrl = new URL('../lib/stockfish/stockfish.js', import.meta.url);
        this.worker = new Worker(workerUrl);

        this.worker.onmessage = (event) => {
          this._handleMessage(event.data);
        };

        this.worker.onerror = (error) => {
          console.error('Stockfish worker error:', error);
          reject(error);
        };

        // Initialize UCI protocol
        this._sendCommand('uci');

        // Wait for 'uciok' response
        const checkReady = setInterval(() => {
          if (this._uciok) {
            clearInterval(checkReady);
            this._sendCommand('isready');
          }
        }, 50);

        // Wait for 'readyok'
        const readyCheck = setInterval(() => {
          if (this._readyok) {
            clearInterval(readyCheck);
            this.ready = true;
            resolve();
          }
        }, 50);

        // Timeout after 15 seconds
        setTimeout(() => {
          if (!this.ready) {
            clearInterval(checkReady);
            clearInterval(readyCheck);
            reject(new Error('Stockfish initialization timeout'));
          }
        }, 15000);

      } catch (err) {
        reject(err);
      }
    });
  }

  /** Handle incoming messages from the Stockfish worker */
  _handleMessage(message) {
    if (typeof message !== 'string') return;

    const line = message.trim();

    if (line === 'uciok') {
      this._uciok = true;
      return;
    }

    if (line === 'readyok') {
      this._readyok = true;
      return;
    }

    // Parse 'bestmove' response
    if (line.startsWith('bestmove')) {
      this.searching = false;
      const parts = line.split(' ');
      const move = parts[1]; // e.g., "e2e4" or "e7e8q"

      if (this._pendingResolve) {
        this._pendingResolve(move);
        this._pendingResolve = null;
      }

      if (this.onBestMove) {
        this.onBestMove(move);
      }
      return;
    }

    // Parse 'info' lines (evaluation, depth, etc.)
    if (line.startsWith('info') && this.onInfo) {
      this.onInfo(line);
    }
  }

  /** Send a UCI command to the worker */
  _sendCommand(cmd) {
    if (this.worker) {
      this.worker.postMessage(cmd);
    }
  }

  /** Set the skill level (difficulty) */
  setSkillLevel(level) {
    this._sendCommand(`setoption name Skill Level value ${level}`);
  }

  /** Set move time limit */
  setMoveTime(ms) {
    this._moveTime = ms;
  }

  /**
   * Get the best move for a position.
   * @param {string} fen - The FEN string of the current position
   * @param {object} difficulty - Difficulty preset { skillLevel, moveTime }
   * @returns {Promise<string>} - The best move in UCI format (e.g., "e2e4")
   */
  async getBestMove(fen, difficulty = DIFFICULTY_LEVELS[0]) {
    if (!this.ready) {
      await this.init();
    }

    // Stop any current search
    if (this.searching) {
      this._sendCommand('stop');
      await new Promise(r => setTimeout(r, 100));
    }

    this.searching = true;

    // Set difficulty
    this.setSkillLevel(difficulty.skillLevel);

    // Set position
    this._sendCommand(`position fen ${fen}`);

    // Request best move with time limit
    return new Promise((resolve) => {
      this._pendingResolve = resolve;
      this._sendCommand(`go movetime ${difficulty.moveTime}`);
    });
  }

  /**
   * Parse a UCI move string into from/to/promotion components.
   * UCI format: "e2e4", "e7e8q" (promotion)
   */
  static parseUCIMove(uciMove) {
    if (!uciMove || uciMove === '(none)') return null;

    const from = uciMove.substring(0, 2);
    const to = uciMove.substring(2, 4);
    const promotion = uciMove.length > 4 ? uciMove[4] : undefined;

    return { from, to, promotion };
  }

  /** Reset the engine for a new game */
  newGame() {
    this._sendCommand('ucinewgame');
    this._sendCommand('isready');
  }

  /** Stop any current search */
  stop() {
    if (this.searching) {
      this._sendCommand('stop');
      this.searching = false;
    }
  }

  /** Terminate the worker */
  destroy() {
    if (this.worker) {
      this._sendCommand('quit');
      this.worker.terminate();
      this.worker = null;
      this.ready = false;
      this.searching = false;
    }
  }
}
