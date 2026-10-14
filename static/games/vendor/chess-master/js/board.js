/**
 * Board Renderer & Interaction Handler
 */

// Piece artwork: standard Cburnett SVGs bundled in assets/pieces/.
// White pieces are solid white with black outlines, black pieces are
// solid black — the two armies are instantly distinguishable, no mixing.
function pieceSrc(color, type) {
  return `assets/pieces/${color}${type.toUpperCase()}.svg`;
}

const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
const RANKS = ['8', '7', '6', '5', '4', '3', '2', '1'];

export class Board {
  constructor(containerId, game) {
    this.container = document.getElementById(containerId);
    this.game = game;
    this.selectedSquare = null;
    this.legalMoves = [];
    this.flipped = false;
    this.dragPiece = null;
    this.dragFrom = null;
    this.inputLocked = false;       // Lock board during bot turn
    this.humanColor = null;          // 'w', 'b', or null (both can move)

    this.onMove = null; // callback(from, to)
    this.onPromotionNeeded = null; // callback(from, to)

    this.render();
    this.bindEvents();
  }

  /** Lock or unlock board input */
  setInputLocked(locked) {
    this.inputLocked = locked;
    this.container.classList.toggle('locked', locked);
    if (locked) this.deselect();
  }

  /** Set which color the human controls (null = both) */
  setHumanColor(color) {
    this.humanColor = color;
  }

  /** Check if the current turn belongs to the human */
  isHumanTurn() {
    if (!this.humanColor) return true; // vs Friend mode
    return this.game.getTurn() === this.humanColor;
  }

  /** Render the board squares */
  render() {
    this.container.innerHTML = '';

    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const actualRow = this.flipped ? 7 - row : row;
        const actualCol = this.flipped ? 7 - col : col;

        const file = FILES[actualCol];
        const rank = RANKS[actualRow];
        const squareName = file + rank;

        const isLight = (actualRow + actualCol) % 2 === 0;
        const square = document.createElement('div');
        square.className = `square ${isLight ? 'square-light' : 'square-dark'}`;
        square.dataset.square = squareName;

        // Add coordinates
        if (col === 0) {
          const coord = document.createElement('span');
          coord.className = 'coordinate coord-rank';
          coord.textContent = rank;
          square.appendChild(coord);
        }
        if (row === 7) {
          const coord = document.createElement('span');
          coord.className = 'coordinate coord-file';
          coord.textContent = file;
          square.appendChild(coord);
        }

        this.container.appendChild(square);
      }
    }

    this.updatePieces();
  }

  /** Update piece positions on the board */
  updatePieces() {
    // Remove all existing pieces
    this.container.querySelectorAll('.piece').forEach(p => p.remove());

    const board = this.game.getBoard();

    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const piece = board[row][col];
        if (piece) {
          const squareName = piece.square;
          const squareEl = this.container.querySelector(`[data-square="${squareName}"]`);
          if (squareEl) {
            const pieceEl = document.createElement('img');
            pieceEl.className = `piece ${piece.color === 'w' ? 'piece-white' : 'piece-black'}`;
            pieceEl.src = pieceSrc(piece.color, piece.type);
            pieceEl.alt = `${piece.color === 'w' ? 'White' : 'Black'} ${piece.type}`;
            pieceEl.dataset.square = squareName;
            pieceEl.draggable = true;
            squareEl.appendChild(pieceEl);
          }
        }
      }
    }
  }

  /** Bind click and drag events */
  bindEvents() {
    this.container.addEventListener('click', (e) => this.handleClick(e));
    this.container.addEventListener('dragstart', (e) => this.handleDragStart(e));
    this.container.addEventListener('dragover', (e) => this.handleDragOver(e));
    this.container.addEventListener('drop', (e) => this.handleDrop(e));
    this.container.addEventListener('dragend', (e) => this.handleDragEnd(e));
  }

  /** Handle square click */
  handleClick(e) {
    // Block input if locked or not human's turn
    if (this.inputLocked || !this.isHumanTurn()) return;

    const squareEl = e.target.closest('.square');
    if (!squareEl) return;

    const square = squareEl.dataset.square;

    // If a piece is already selected
    if (this.selectedSquare) {
      // Check if clicking on a legal move target
      const isLegalTarget = this.legalMoves.some(m => m.to === square);

      if (isLegalTarget) {
        this.attemptMove(this.selectedSquare, square);
        return;
      }

      // Clicking on own piece - reselect
      const piece = this.getPieceAt(square);
      if (piece && piece.color === this.game.getTurn()) {
        if (square === this.selectedSquare) {
          this.deselect();
        } else {
          this.selectSquare(square);
        }
        return;
      }

      // Clicking elsewhere - deselect
      this.deselect();
      return;
    }

    // No piece selected - try to select one
    const piece = this.getPieceAt(square);
    if (piece && piece.color === this.game.getTurn() && !this.game.gameOver) {
      this.selectSquare(square);
    }
  }

  /** Handle drag start */
  handleDragStart(e) {
    // Block drag if locked or not human's turn
    if (this.inputLocked || !this.isHumanTurn()) {
      e.preventDefault();
      return;
    }

    const pieceEl = e.target.closest('.piece');
    if (!pieceEl) {
      e.preventDefault();
      return;
    }

    const square = pieceEl.dataset.square;
    const piece = this.getPieceAt(square);

    if (!piece || piece.color !== this.game.getTurn() || this.game.gameOver) {
      e.preventDefault();
      return;
    }

    this.dragFrom = square;
    this.selectSquare(square);
    e.dataTransfer.effectAllowed = 'move';
  }

  /** Handle drag over */
  handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }

  /** Handle drop */
  handleDrop(e) {
    e.preventDefault();
    const squareEl = e.target.closest('.square');
    if (!squareEl || !this.dragFrom) return;

    const targetSquare = squareEl.dataset.square;
    const isLegalTarget = this.legalMoves.some(m => m.to === targetSquare);

    if (isLegalTarget) {
      this.attemptMove(this.dragFrom, targetSquare);
    }

    this.dragFrom = null;
  }

  /** Handle drag end */
  handleDragEnd(e) {
    this.dragFrom = null;
  }

  /** Attempt to make a move */
  attemptMove(from, to) {
    // Check for promotion
    if (this.game.isPromotion(from, to)) {
      if (this.onPromotionNeeded) {
        this.onPromotionNeeded(from, to);
      }
      return;
    }

    if (this.onMove) {
      this.onMove(from, to);
    }
    this.deselect();
  }

  /** Select a square and show legal moves */
  selectSquare(square) {
    this.deselect();
    this.selectedSquare = square;
    this.legalMoves = this.game.getLegalMoves(square);

    // Highlight selected square
    const squareEl = this.container.querySelector(`[data-square="${square}"]`);
    if (squareEl) squareEl.classList.add('selected');

    // Show legal move indicators
    for (const move of this.legalMoves) {
      const targetEl = this.container.querySelector(`[data-square="${move.to}"]`);
      if (targetEl) {
        if (move.captured) {
          // Capture - show ring
          const ring = document.createElement('div');
          ring.className = 'capture-ring';
          targetEl.appendChild(ring);
        } else {
          // Empty square - show dot
          const dot = document.createElement('div');
          dot.className = 'move-dot';
          targetEl.appendChild(dot);
        }
      }
    }
  }

  /** Deselect current selection */
  deselect() {
    this.selectedSquare = null;
    this.legalMoves = [];

    // Remove all highlights
    this.container.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
    this.container.querySelectorAll('.move-dot').forEach(el => el.remove());
    this.container.querySelectorAll('.capture-ring').forEach(el => el.remove());
  }

  /** Get piece at a square */
  getPieceAt(square) {
    const board = this.game.getBoard();
    const file = FILES.indexOf(square[0]);
    const rank = 8 - parseInt(square[1]);
    if (file === -1 || rank < 0 || rank > 7) return null;
    return board[rank][file];
  }

  /** Update board highlights (last move, check) */
  updateHighlights() {
    // Clear existing highlights
    this.container.querySelectorAll('.last-move').forEach(el => el.classList.remove('last-move'));
    this.container.querySelectorAll('.check').forEach(el => el.classList.remove('check'));

    // Highlight last move
    const lastMove = this.game.getLastMove();
    if (lastMove) {
      const fromEl = this.container.querySelector(`[data-square="${lastMove.from}"]`);
      const toEl = this.container.querySelector(`[data-square="${lastMove.to}"]`);
      if (fromEl) fromEl.classList.add('last-move');
      if (toEl) toEl.classList.add('last-move');
    }

    // Highlight king in check
    if (this.game.isInCheck()) {
      const kingSquare = this.game.findKing(this.game.getTurn());
      if (kingSquare) {
        const kingEl = this.container.querySelector(`[data-square="${kingSquare}"]`);
        if (kingEl) kingEl.classList.add('check');
      }
    }
  }

  /** Flip the board */
  flip() {
    this.flipped = !this.flipped;
    this.deselect();
    this.render();
    this.updateHighlights();
  }

  /** Full refresh of the board */
  refresh() {
    this.deselect();
    this.updatePieces();
    this.updateHighlights();
  }
}
