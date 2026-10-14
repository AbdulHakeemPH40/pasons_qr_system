/**
 * Chess Master - Main Application Controller (Pasons port, see CHANGES.md)
 *
 * Ported from the Electron desktop app to run inside the Games Zone
 * same-origin iframe. Trimmed to the client brief:
 *   - vs Stockfish ONLY (no vs Friend, no vs AI Model / LLM)
 *   - difficulty levels 3-6 ONLY (tough game)
 *   - mobile layout (the play page is always a phone card)
 * Plus a Games Zone score extension (js/score.js) rendered into
 * #chess--score for the shell bridge.
 */
import { ChessGame } from './game.js?v=2026-10-14-19';
import { Board } from './board.js?v=2026-10-14-19';
import { ChessClock } from './clock.js?v=2026-10-14-19';
import { MovePanel } from './moves.js?v=2026-10-14-19';
import { SoundManager } from './sound.js?v=2026-10-14-19';
import { UIManager, levelLabel } from './ui.js?v=2026-10-14-19';
import { StockfishEngine, DIFFICULTY_LEVELS, difficultyById } from './engine.js?v=2026-10-14-19';
import { GameHistory } from './history.js?v=2026-10-14-19';
import { ScoreKeeper } from './score.js?v=2026-10-14-19';

class App {
  constructor() {
    this.game = new ChessGame();
    this.clock = new ChessClock();
    this.sound = new SoundManager();
    this.ui = new UIManager();
    this.movePanel = new MovePanel('move-list');
    this.board = new Board('chess-board', this.game);
    this.stockfish = new StockfishEngine();
    this.history = new GameHistory();
    this.score = new ScoreKeeper('chess--score');

    this.selectedTimeControl = { time: 600, inc: 0 };
    this.gameStarted = false;

    // Stockfish-only: the human always plays one colour against the engine.
    this.gameMode = 'computer';
    this.humanColor = 'w';
    this.botColor = 'b';
    this.botThinking = false;

    this.init();
  }

  /** Initialize the application */
  init() {
    this.bindBoardCallbacks();
    this.bindClockCallbacks();
    this.bindUIEvents();
    this.renderStats();
    this.bindHistoryEvents();
    this.board.setInputLocked(true);
    this.updateStatus();

    // Deterministic test hooks (see CHANGES.md): ?autostart=1&level=N&color=
    // w|b&fen=... skips the setup modal so browser tests can seed a position
    // (e.g. mate-in-1) and drive the bridge end to end. Plain loads never
    // see them.
    const params = new URLSearchParams(window.location.search);
    if (params.get('autostart') === '1') {
      const level = parseInt(params.get('level') || '3', 10);
      const color = params.get('color') === 'b' ? 'b' : 'w';
      const fen = params.get('fen') || '';
      this.ui.selectedDifficulty = difficultyById(level).id;
      this.ui.selectedColor = color;
      this.startNewGame({
        mode: 'computer',
        difficulty: difficultyById(level).id,
        humanColor: color,
        fen,
      });
    } else {
      this.ui.showNewGame();
    }
  }

  /** Bind history/stats panel events */
  bindHistoryEvents() {
    const clearBtn = document.getElementById('btn-clear-history');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        this.ui.showConfirm(
          'Clear History?',
          'All saved game results will be deleted. This cannot be undone.',
          (confirmed) => {
            if (confirmed) {
              this.history.clear();
              this.renderStats();
              this.ui.showToast('Game history cleared');
            }
          }
        );
      });
    }
  }

  /** Bind board interaction callbacks */
  bindBoardCallbacks() {
    this.board.onMove = (from, to) => {
      this.executeMove(from, to);
    };

    this.board.onPromotionNeeded = (from, to) => {
      const color = this.game.getTurn();
      this.ui.showPromotion(color, (piece) => {
        this.executeMove(from, to, piece);
      });
    };
  }

  /** Bind clock callbacks */
  bindClockCallbacks() {
    this.clock.onFlag = (color) => {
      this.game.timeout(color);
      this.endGame();
    };

    this.clock.onTick = () => {
      this.updateClockDisplay();
    };
  }

  /** Bind UI button events */
  bindUIEvents() {
    // New Game button
    document.getElementById('btn-new-game').addEventListener('click', () => {
      this.ui.showNewGame();
    });

    // Time control selection
    document.querySelectorAll('.time-option').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.time-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.selectedTimeControl = {
          time: parseInt(btn.dataset.time),
          inc: parseInt(btn.dataset.inc)
        };
      });
    });

    // Start game button
    document.getElementById('btn-start-game').addEventListener('click', () => {
      this.ui.hideNewGame();
      const config = this.ui.getGameConfig();
      this.startNewGame(config);
    });

    // Cancel new game: always dismiss the setup modal so the tap never does
    // nothing (a Cancel that ignores taps is a broken control). Mid-game this
    // returns to the running game; on the start screen it reveals the idle
    // board, whose status reads "Set up a game to start" with the New Game
    // button ready to reopen the dialog. Never a dead end.
    document.getElementById('btn-cancel-newgame').addEventListener('click', () => {
      this.ui.hideNewGame();
    });

    // Rematch button
    document.getElementById('btn-rematch').addEventListener('click', () => {
      this.ui.hideGameOver();
      this.startNewGame({
        mode: 'computer',
        difficulty: this.ui.selectedDifficulty,
        humanColor: this.humanColor,
      });
    });

    // Close game over modal (review board)
    document.getElementById('btn-close-modal').addEventListener('click', () => {
      this.ui.hideGameOver();
    });

    // Resign button
    document.getElementById('btn-resign').addEventListener('click', () => {
      if (this.game.gameOver || !this.gameStarted) return;
      const color = this.game.getTurn();
      const colorName = color === 'w' ? 'White' : 'Black';
      this.ui.showConfirm(
        'Resign?',
        `${colorName} will lose the game. Are you sure?`,
        (confirmed) => {
          if (confirmed) {
            this.game.resign(color);
            this.endGame();
          }
        }
      );
    });

    // Draw button
    document.getElementById('btn-draw').addEventListener('click', () => {
      if (this.game.gameOver || !this.gameStarted) return;
      this.ui.showConfirm(
        'Offer Draw?',
        'Do you want to offer a draw?',
        (confirmed) => {
          if (confirmed) {
            this.game.drawByAgreement();
            this.endGame();
          }
        }
      );
    });

    // Undo button (undoes the bot's reply and the human's move)
    document.getElementById('btn-undo').addEventListener('click', () => {
      if (this.game.moveHistory.length === 0 || this.botThinking) return;

      const undoOne = () => {
        const undone = this.game.undoMove();
        if (undone && undone.captured && undone.color === this.humanColor) {
          // The human's capture is no longer part of the game.
          this.score.removeCapture(undone.captured);
        }
        return undone;
      };

      undoOne(); // bot's move
      if (this.game.moveHistory.length > 0) undoOne(); // human's move

      this.board.refresh();
      this.movePanel.update(this.game.moveHistory);
      this.updateStatus();
      this.updateCaptured();
      this.updateInfo();
      this.sound.playMove();
    });

    // Flip board button
    document.getElementById('btn-flip').addEventListener('click', () => {
      this.board.flip();
    });

    // Sidebar tabs
    document.querySelectorAll('.sidebar-tabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.sidebar-tabs .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
      });
    });

    // Mobile moves drawer (bottom sheet)
    const mobileMovesBtn = document.getElementById('btn-mobile-moves');
    const drawerBackdrop = document.getElementById('drawer-backdrop');
    const setMobileDrawer = (open) => {
      document.body.classList.toggle('mobile-panel-open', open);
      drawerBackdrop.classList.toggle('hidden', !open);
      mobileMovesBtn.classList.toggle('open', open);
      mobileMovesBtn.innerHTML = open ? '&#10005;' : '&#9776;';
      mobileMovesBtn.setAttribute('aria-label', open ? 'Close moves panel' : 'Open moves panel');
    };
    mobileMovesBtn.addEventListener('click', () => {
      setMobileDrawer(!document.body.classList.contains('mobile-panel-open'));
    });
    drawerBackdrop.addEventListener('click', () => setMobileDrawer(false));
  }

  /** Start a new Stockfish game with the given configuration */
  startNewGame(config = null) {
    // Stop any ongoing bot search
    this.stockfish.stop();
    this.botThinking = false;
    this.ui.hideAllThinking();

    if (config) {
      this.humanColor = config.humanColor || 'w';
      this.botColor = this.humanColor === 'w' ? 'b' : 'w';
    }

    // Reset game state (optional FEN seeds a test position)
    const fen = config && config.fen ? config.fen : '';
    const loaded = this.game.reset(fen);
    if (!loaded && fen) {
      this.ui.showToast('Test position not valid, starting from the standard position');
    }
    this.score.reset();
    this.clock.setTimeControl(this.selectedTimeControl.time, this.selectedTimeControl.inc);
    this.clock.reset();
    this.gameStarted = true;

    // Configure board
    this.board.setHumanColor(this.humanColor);
    this.board.setInputLocked(false);

    // Update UI
    this.board.refresh();
    this.movePanel.clear();
    this.updateStatus();
    this.updateClockDisplay();
    this.updateCaptured();
    this.updateInfo();
    this.ui.updatePlayerNames(this.humanColor, this.ui.selectedDifficulty);
    this.ui.updateModeIndicator(this.humanColor, this.ui.selectedDifficulty);

    // Flip board if human plays black
    if (this.humanColor === 'b') {
      if (!this.board.flipped) this.board.flip();
    } else if (this.board.flipped) {
      this.board.flip();
    }

    // Start white's clock
    this.clock.start('w');
    this.sound.playGameStart();

    // If the engine plays white, it moves first
    if (this.botColor === 'w') {
      this.scheduleBotMove();
    }
  }

  /** Execute a move (called by human or bot) */
  executeMove(from, to, promotion) {
    const move = this.game.makeMove(from, to, promotion);

    if (!move) {
      this.sound.playIllegal();
      return false;
    }

    // Score extension: captures by the human score points.
    if (move.captured && move.color === this.humanColor) {
      this.score.addCapture(move.captured);
    }

    // Play appropriate sound
    if (move.san.includes('O-O')) {
      this.sound.playCastle();
    } else if (move.captured) {
      this.sound.playCapture();
    } else {
      this.sound.playMove();
    }

    // Check for check
    if (this.game.isInCheck()) {
      this.sound.playCheck();
    }

    // Update board
    this.board.refresh();

    // Update move history
    this.movePanel.update(this.game.moveHistory);

    // Switch clock
    this.clock.switchClock();
    this.updateClockDisplay();

    // Update captured pieces
    this.updateCaptured();

    // Update status
    this.updateStatus();
    this.updateInfo();

    // Check if game is over
    if (this.game.gameOver) {
      this.endGame();
      return true;
    }

    // If it's now the bot's turn, schedule bot move
    if (this.game.getTurn() === this.botColor) {
      this.scheduleBotMove();
    }

    return true;
  }

  /** Schedule the bot to make a move */
  scheduleBotMove() {
    if (this.game.gameOver || this.botThinking) return;

    this.botThinking = true;
    this.board.setInputLocked(true);
    this.ui.showThinking(this.botColor);
    this.updateStatus();

    // Small delay for UX (let the UI update)
    setTimeout(() => this.makeBotMove(), 300);
  }

  /** Make the bot's move */
  async makeBotMove() {
    try {
      const move = await this.getStockfishMove();

      if (move && !this.game.gameOver) {
        this.botThinking = false;
        this.ui.hideThinking(this.botColor);
        this.board.setInputLocked(false);
        this.executeMove(move.from, move.to, move.promotion);
      } else {
        // No valid move (shouldn't happen if game isn't over)
        this.botThinking = false;
        this.ui.hideThinking(this.botColor);
        this.board.setInputLocked(false);
      }
    } catch (err) {
      console.error('Bot move error:', err);
      this.botThinking = false;
      this.ui.hideThinking(this.botColor);
      this.board.setInputLocked(false);
      this.ui.showToast(`Engine error: ${err.message}`);
    }
  }

  /** Get a move from Stockfish (levels 3-6) */
  async getStockfishMove() {
    const fen = this.game.getFEN();
    const difficulty = difficultyById(this.ui.selectedDifficulty);

    const uciMove = await this.stockfish.getBestMove(fen, difficulty);
    return StockfishEngine.parseUCIMove(uciMove);
  }

  /** End the game */
  endGame() {
    this.clock.stop();
    this.stockfish.stop();
    this.botThinking = false;
    this.ui.hideAllThinking();
    this.board.setInputLocked(false);
    this.sound.playGameEnd();
    this.updateStatus();
    this.updateInfo();

    // Score extension: result bonus BEFORE the game-over modal shows, so the
    // shell's final bridge read (triggered by the modal) sees the total.
    this.score.addResultBonus(
      this.game.result,
      this.ui.selectedDifficulty,
      this.humanColor
    );

    // Record result in persistent history
    this.recordGameResult();

    // Show game over modal after a short delay
    setTimeout(() => {
      this.ui.showGameOver(this.game.result, this.game.resultReason);
    }, 500);
  }

  /** Record the finished game into persistent history */
  recordGameResult() {
    if (!this.game.result) return;

    const opponent = `Stockfish (Lv ${levelLabel(this.ui.selectedDifficulty)})`;

    const timeStr = this.selectedTimeControl.inc > 0
      ? `${this.selectedTimeControl.time / 60}+${this.selectedTimeControl.inc}`
      : `${this.selectedTimeControl.time / 60} min`;

    this.history.record({
      result: this.game.result,
      reason: this.game.resultReason,
      mode: 'computer',
      humanColor: this.humanColor,
      opponent,
      moves: this.game.moveHistory.length,
      timeControl: timeStr,
    });

    this.renderStats();
  }

  /** Render the Stats tab: summary numbers + history list */
  renderStats() {
    const summaryEl = document.getElementById('stats-summary');
    const listEl = document.getElementById('stats-history');
    if (!summaryEl || !listEl) return;

    const stats = this.history.getStats();
    const entries = this.history.getAll();

    // --- Summary cards ---
    let html = '';

    if (stats.botGames.total > 0) {
      const b = stats.botGames;
      html += `
        <div class="stats-section-title">Your Record (vs Stockfish)</div>
        <div class="stats-cards">
          <div class="stat-card stat-win"><div class="stat-num">${b.wins}</div><div class="stat-label">Wins</div></div>
          <div class="stat-card stat-loss"><div class="stat-num">${b.losses}</div><div class="stat-label">Losses</div></div>
          <div class="stat-card stat-draw"><div class="stat-num">${b.draws}</div><div class="stat-label">Draws</div></div>
        </div>`;
    }

    html += `
      <div class="stats-section-title">All Games</div>
      <div class="stats-cards">
        <div class="stat-card"><div class="stat-num">${stats.total}</div><div class="stat-label">Played</div></div>
        <div class="stat-card stat-win"><div class="stat-num">${stats.whiteWins}</div><div class="stat-label">White Won</div></div>
        <div class="stat-card stat-loss"><div class="stat-num">${stats.blackWins}</div><div class="stat-label">Black Won</div></div>
        <div class="stat-card stat-draw"><div class="stat-num">${stats.draws}</div><div class="stat-label">Draws</div></div>
      </div>`;

    summaryEl.innerHTML = html;

    // --- History list ---
    if (entries.length === 0) {
      listEl.innerHTML = '<div class="move-empty">No games recorded yet.</div>';
      return;
    }

    const REASON_LABELS = {
      checkmate: 'Checkmate',
      resignation: 'Resignation',
      timeout: 'Timeout',
      stalemate: 'Stalemate',
      agreement: 'Agreement',
      repetition: 'Repetition',
      insufficient: 'Insufficient material',
      '50-move': '50-move rule',
    };

    listEl.innerHTML = entries.slice(0, 50).map(e => {
      let icon, cls;
      if (e.outcome === 'win') { icon = '&#127942;'; cls = 'hist-win'; }
      else if (e.outcome === 'loss') { icon = '&#128148;'; cls = 'hist-loss'; }
      else { icon = '&#129309;'; cls = 'hist-draw'; }

      const date = new Date(e.date);
      const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        + ' ' + date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

      const title = `${e.outcome === 'win' ? 'You Won' : e.outcome === 'loss' ? 'You Lost' : 'Draw'} \u2014 ${e.opponent}`;

      const reason = REASON_LABELS[e.reason] || e.reason || '';

      return `
        <div class="history-item ${cls}">
          <span class="history-icon">${icon}</span>
          <div class="history-info">
            <div class="history-title">${title}</div>
            <div class="history-meta">${reason} &middot; ${e.moves} moves &middot; ${e.timeControl} &middot; ${dateStr}</div>
          </div>
        </div>`;
    }).join('');
  }

  /** Update status bar */
  updateStatus() {
    if (this.game.gameOver) {
      let text = '';
      switch (this.game.resultReason) {
        case 'checkmate':
          text = `Checkmate! ${this.game.result === '1-0' ? 'White' : 'Black'} wins`;
          break;
        case 'resignation':
          text = `${this.game.result === '1-0' ? 'Black' : 'White'} resigned`;
          break;
        case 'timeout':
          text = `${this.game.result === '1-0' ? 'Black' : 'White'} ran out of time`;
          break;
        case 'stalemate':
          text = 'Draw by stalemate';
          break;
        case 'agreement':
          text = 'Draw by agreement';
          break;
        default:
          text = `Draw - ${this.game.resultReason}`;
      }
      this.ui.updateStatus(text, null);
    } else if (this.botThinking) {
      this.ui.updateStatus('Stockfish is thinking...', this.botColor);
    } else {
      const turn = this.game.getTurn();
      const turnName = turn === 'w' ? 'White' : 'Black';
      let text = this.gameStarted ? `${turnName} to move` : 'Set up a game to start';
      if (this.gameStarted && this.game.isInCheck()) {
        text += ' \u2014 Check!';
      }
      this.ui.updateStatus(text, turn);
    }
  }

  /** Update clock display */
  updateClockDisplay() {
    const whiteActive = this.clock.activeColor === 'w' && this.clock.running;
    const blackActive = this.clock.activeColor === 'b' && this.clock.running;

    this.ui.updateClock('w', this.clock.getDisplayTime('w'), whiteActive, this.clock.isLowTime('w'));
    this.ui.updateClock('b', this.clock.getDisplayTime('b'), blackActive, this.clock.isLowTime('b'));
  }

  /** Update captured pieces display */
  updateCaptured() {
    const captured = this.game.getCapturedPieces();
    const advantage = this.game.getMaterialAdvantage();
    this.ui.updateCapturedPieces(captured.w, captured.b, advantage);
  }

  /** Update info panel */
  updateInfo() {
    const timeStr = this.selectedTimeControl.inc > 0
      ? `${this.selectedTimeControl.time / 60}+${this.selectedTimeControl.inc}`
      : `${this.selectedTimeControl.time / 60} min`;

    const status = !this.gameStarted ? 'Not started' : this.game.gameOver ? 'Finished' : 'In Progress';
    const moveCount = this.game.moveHistory.length;

    this.ui.updateInfo(timeStr, status, moveCount);
  }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.chessApp = new App();
});
