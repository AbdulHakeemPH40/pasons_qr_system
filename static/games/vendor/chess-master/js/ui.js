/**
 * UI Manager - Handles modals, status updates, and UI components
 *
 * Pasons port (CHANGES.md): trimmed to vs Stockfish only. The Electron
 * original carried a welcome mode-picker (friend / computer / LLM), an
 * LLM settings modal with API keys, and model-name plumbing. All of that is
 * gone: the New Game modal (difficulty 3-6, colour, time control) is the
 * start screen.
 */
/**
 * Display level for the guest: engine difficulty id (3-6) -> shown 1-4.
 *
 * UI-only renumbering (client request): the Stockfish hardness mapping
 * in js/engine.js DIFFICULTY_LEVELS is untouched (skill 6/10/15/20),
 * only the number the guest reads changes. 1 = Club, 2 = Advanced,
 * 3 = Expert, 4 = Master. Every "Lv N" the guest can see goes through
 * this one function.
 */
export function levelLabel(difficultyId) {
  return Math.max(1, Math.min(4, (difficultyId | 0) - 2));
}

export class UIManager {
  constructor() {
    this.promotionModal = document.getElementById('promotion-modal');
    this.gameoverModal = document.getElementById('gameover-modal');
    this.newgameModal = document.getElementById('newgame-modal');
    this.confirmModal = document.getElementById('confirm-modal');
    this.statusText = document.getElementById('status-text');
    this.statusDot = document.querySelector('.status-dot');

    this.confirmCallback = null;
    this.promotionCallback = null;

    // Stockfish-only state: difficulty 3-6 and the human's colour.
    this.selectedDifficulty = 3;      // 3-6
    this.selectedColor = 'w';         // 'w', 'b', 'random'

    this.bindModalEvents();
    this.bindOptionEvents();
  }

  /** Bind modal button events */
  bindModalEvents() {
    // Promotion pieces
    document.querySelectorAll('.promotion-piece').forEach(btn => {
      btn.addEventListener('click', () => {
        const piece = btn.dataset.piece;
        this.hidePromotion();
        if (this.promotionCallback) this.promotionCallback(piece);
      });
    });

    // Confirm modal
    document.getElementById('btn-confirm-yes').addEventListener('click', () => {
      this.hideConfirm();
      if (this.confirmCallback) this.confirmCallback(true);
    });

    document.getElementById('btn-confirm-no').addEventListener('click', () => {
      this.hideConfirm();
      if (this.confirmCallback) this.confirmCallback(false);
    });

    // Close modal on overlay click (never the setup modal: a backdrop tap
    // must not leave a fresh load with a dead, unplayable board).
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay && overlay.id !== 'newgame-modal') {
          overlay.classList.add('hidden');
        }
      });
    });
  }

  /** Bind difficulty / colour option events (3-6 only in the markup) */
  bindOptionEvents() {
    // Difficulty selector
    document.querySelectorAll('.diff-option').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.diff-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.selectedDifficulty = parseInt(btn.dataset.diff);
      });
    });

    // Color selector
    document.querySelectorAll('.color-option').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.color-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.selectedColor = btn.dataset.color;
      });
    });
  }

  /** Get current game configuration from UI */
  getGameConfig() {
    let color = this.selectedColor;
    if (color === 'random') {
      color = Math.random() < 0.5 ? 'w' : 'b';
    }

    return {
      mode: 'computer',
      difficulty: this.selectedDifficulty,
      humanColor: color,
    };
  }

  /** Show promotion dialog */
  showPromotion(color, callback) {
    this.promotionCallback = callback;
    const pieces = document.getElementById('promotion-pieces');
    pieces.querySelectorAll('.promotion-piece').forEach(btn => {
      btn.innerHTML = '';
      const img = document.createElement('img');
      img.src = `assets/pieces/${color}${btn.dataset.piece.toUpperCase()}.svg`;
      img.alt = btn.dataset.piece;
      btn.appendChild(img);
    });

    this.promotionModal.classList.remove('hidden');
  }

  /** Hide promotion dialog */
  hidePromotion() {
    this.promotionModal.classList.add('hidden');
  }

  /** Show game over modal */
  showGameOver(result, reason) {
    const icon = document.getElementById('gameover-icon');
    const title = document.getElementById('gameover-title');
    const reasonEl = document.getElementById('gameover-reason');

    let titleText = '';
    let reasonText = '';
    let iconText = '&#127942;';

    if (result === '1-0') {
      titleText = 'White Wins!';
    } else if (result === '0-1') {
      titleText = 'Black Wins!';
    } else {
      titleText = 'Draw!';
      iconText = '&#129309;';
    }

    switch (reason) {
      case 'checkmate':
        reasonText = result === '1-0' ? 'White wins by checkmate' : 'Black wins by checkmate';
        break;
      case 'resignation':
        reasonText = result === '1-0' ? 'Black resigned' : 'White resigned';
        break;
      case 'timeout':
        reasonText = result === '1-0' ? 'Black ran out of time' : 'White ran out of time';
        break;
      case 'stalemate':
        reasonText = 'Game drawn by stalemate';
        break;
      case 'agreement':
        reasonText = 'Game drawn by agreement';
        break;
      case 'insufficient material':
        reasonText = 'Draw - insufficient material';
        break;
      case 'threefold repetition':
        reasonText = 'Draw - threefold repetition';
        break;
      case '50-move rule':
        reasonText = 'Draw - 50-move rule';
        break;
      default:
        reasonText = reason;
    }

    icon.innerHTML = iconText;
    title.textContent = titleText;
    reasonEl.textContent = reasonText;
    this.gameoverModal.classList.remove('hidden');
  }

  /** Hide game over modal */
  hideGameOver() {
    this.gameoverModal.classList.add('hidden');
  }

  /** Show new game modal (the start screen) */
  showNewGame() {
    this.newgameModal.classList.remove('hidden');
  }

  /** Hide new game modal */
  hideNewGame() {
    this.newgameModal.classList.add('hidden');
  }

  /** Show/hide thinking indicator for a color */
  showThinking(color) {
    const el = document.getElementById(`thinking-${color === 'w' ? 'white' : 'black'}`);
    if (el) el.classList.remove('hidden');
  }

  hideThinking(color) {
    const el = document.getElementById(`thinking-${color === 'w' ? 'white' : 'black'}`);
    if (el) el.classList.add('hidden');
  }

  hideAllThinking() {
    this.hideThinking('w');
    this.hideThinking('b');
  }

  /** Update player names: You vs Stockfish (Lv N) */
  updatePlayerNames(humanColor, difficulty) {
    const whiteName = document.getElementById('name-white');
    const blackName = document.getElementById('name-black');
    const botLabel = `Stockfish (Lv ${levelLabel(difficulty)})`;

    if (humanColor === 'w') {
      whiteName.textContent = 'You';
      blackName.textContent = botLabel;
    } else {
      whiteName.textContent = botLabel;
      blackName.textContent = 'You';
    }
  }

  /** Update mode indicator in header */
  updateModeIndicator(humanColor, difficulty) {
    const indicator = document.getElementById('mode-indicator');
    if (!indicator) return;
    const text = indicator.querySelector('.mode-indicator-text');
    const colorText = humanColor === 'w' ? '(White)' : '(Black)';
    text.textContent = `vs Stockfish Lv ${levelLabel(difficulty)} ${colorText}`;
  }

  /** Show confirm dialog */
  showConfirm(title, message, callback) {
    this.confirmCallback = callback;
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    this.confirmModal.classList.remove('hidden');
  }

  /** Hide confirm dialog */
  hideConfirm() {
    this.confirmModal.classList.add('hidden');
  }

  /** Update game status text */
  updateStatus(text, color) {
    this.statusText.textContent = text;
    if (color === 'w') {
      this.statusDot.className = 'status-dot white-dot';
    } else if (color === 'b') {
      this.statusDot.className = 'status-dot black-dot';
    }
  }

  /** Update clock display */
  updateClock(color, timeStr, isActive, isLow) {
    const clockEl = document.getElementById(`clock-${color === 'w' ? 'white' : 'black'}`);
    clockEl.textContent = timeStr;
    clockEl.classList.toggle('active', isActive);
    clockEl.classList.toggle('low-time', isLow);
  }

  /** Update captured pieces display */
  updateCapturedPieces(capturedByWhite, capturedByBlack, advantage) {
    const whiteEl = document.getElementById('captured-by-white');
    const blackEl = document.getElementById('captured-by-black');

    // White's bar shows the BLACK pieces White captured (dark icons)
    this.renderCaptured(whiteEl, capturedByWhite, 'cap-black', advantage > 0 ? advantage : 0);
    // Black's bar shows the WHITE pieces Black captured (light icons)
    this.renderCaptured(blackEl, capturedByBlack, 'cap-white', advantage < 0 ? Math.abs(advantage) : 0);
  }

  /** Render captured piece icons with the color of the captured piece */
  renderCaptured(el, pieces, colorClass, advantage) {
    el.innerHTML = '';
    for (const p of pieces) {
      const color = colorClass === 'cap-black' ? 'b' : 'w';
      const img = document.createElement('img');
      img.className = `cap-piece ${colorClass}`;
      img.src = `assets/pieces/${color}${p.type.toUpperCase()}.svg`;
      img.alt = p.type;
      el.appendChild(img);
    }
    if (advantage > 0) {
      const adv = document.createElement('span');
      adv.className = 'cap-advantage';
      adv.textContent = `+${advantage}`;
      el.appendChild(adv);
    }
  }

  /** Update game info panel */
  updateInfo(timeControl, status, moveCount) {
    document.getElementById('info-time-control').textContent = timeControl;
    document.getElementById('info-status').textContent = status;
    document.getElementById('info-moves').textContent = moveCount;
  }

  /** Show a toast notification */
  showToast(message) {
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
      background: #262421; color: #fff; padding: 12px 24px; border-radius: 8px;
      border: 1px solid #3D3B38; font-size: 14px; z-index: 2000;
      animation: fadeIn 0.2s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }
}
