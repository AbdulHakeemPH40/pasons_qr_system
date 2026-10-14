/**
 * Game Engine - Wraps chess.js to provide game state management
 */
import { Chess } from '../lib/chess.js';

export class ChessGame {
  constructor() {
    this.chess = new Chess();
    this.moveHistory = [];
    this.gameOver = false;
    this.result = null;
    this.resultReason = null;
  }

  /**
   * Reset to a new game.
   * Pasons extension (CHANGES.md): an optional FEN seeds the position, which
   * is how the browser tests set up deterministic fixtures (mate-in-1 etc).
   * Returns true when a FEN was loaded, false for the standard start (or an
   * invalid FEN, which falls back to the standard start).
   */
  reset(fen = '') {
    let loaded = false;
    this.chess = new Chess();
    if (fen) {
      try {
        loaded = this.chess.load(fen);
      } catch (e) {
        loaded = false;
        if (!loaded) this.chess = new Chess();
      }
    }
    this.moveHistory = [];
    this.gameOver = false;
    this.result = null;
    this.resultReason = null;
    return loaded;
  }

  /** Get the current board state as 2D array */
  getBoard() {
    return this.chess.board();
  }

  /** Get whose turn it is ('w' or 'b') */
  getTurn() {
    return this.chess.turn();
  }

  /** Get legal moves for a specific square */
  getLegalMoves(square) {
    return this.chess.moves({ square, verbose: true });
  }

  /** Get all legal moves */
  getAllLegalMoves() {
    return this.chess.moves({ verbose: true });
  }

  /** Attempt to make a move. Returns move object or null if illegal */
  makeMove(from, to, promotion) {
    try {
      const move = this.chess.move({ from, to, promotion });
      if (move) {
        this.moveHistory.push(move);
        this.checkGameEnd();
        return move;
      }
    } catch (e) {
      // Illegal move
    }
    return null;
  }

  /** Undo the last move */
  undoMove() {
    const move = this.chess.undo();
    if (move) {
      this.moveHistory.pop();
      this.gameOver = false;
      this.result = null;
      this.resultReason = null;
    }
    return move;
  }

  /** Check if the game has ended */
  checkGameEnd() {
    if (this.chess.isCheckmate()) {
      this.gameOver = true;
      this.result = this.getTurn() === 'w' ? '0-1' : '1-0';
      this.resultReason = 'checkmate';
    } else if (this.chess.isStalemate()) {
      this.gameOver = true;
      this.result = '½-½';
      this.resultReason = 'stalemate';
    } else if (this.chess.isDraw()) {
      this.gameOver = true;
      this.result = '½-½';
      if (this.chess.isInsufficientMaterial()) {
        this.resultReason = 'insufficient material';
      } else if (this.chess.isThreefoldRepetition()) {
        this.resultReason = 'threefold repetition';
      } else {
        this.resultReason = '50-move rule';
      }
    }
    return this.gameOver;
  }

  /** End game by resignation */
  resign(color) {
    this.gameOver = true;
    this.result = color === 'w' ? '0-1' : '1-0';
    this.resultReason = 'resignation';
  }

  /** End game by draw agreement */
  drawByAgreement() {
    this.gameOver = true;
    this.result = '½-½';
    this.resultReason = 'agreement';
  }

  /** End game by timeout */
  timeout(color) {
    this.gameOver = true;
    this.result = color === 'w' ? '0-1' : '1-0';
    this.resultReason = 'timeout';
  }

  /** Check if a specific side is in check */
  isInCheck() {
    return this.chess.inCheck();
  }

  /** Find the king's square for the given color */
  findKing(color) {
    const board = this.chess.board();
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const piece = board[row][col];
        if (piece && piece.type === 'k' && piece.color === color) {
          return piece.square;
        }
      }
    }
    return null;
  }

  /** Get the last move made */
  getLastMove() {
    if (this.moveHistory.length === 0) return null;
    return this.moveHistory[this.moveHistory.length - 1];
  }

  /** Get move history in SAN format */
  getMoveHistorySAN() {
    return this.moveHistory.map(m => m.san);
  }

  /** Get PGN of the game */
  getPGN() {
    return this.chess.pgn();
  }

  /** Get FEN string */
  getFEN() {
    return this.chess.fen();
  }

  /** Check if a move is a promotion */
  isPromotion(from, to) {
    const piece = this.chess.get(from);
    if (!piece || piece.type !== 'p') return false;
    const targetRank = to[1];
    return (piece.color === 'w' && targetRank === '8') ||
           (piece.color === 'b' && targetRank === '1');
  }

  /** Get captured pieces for each side */
  getCapturedPieces() {
    const captured = { w: [], b: [] };
    for (const move of this.moveHistory) {
      if (move.captured) {
        // The captured piece belongs to the opponent
        const capturedBy = move.color; // the mover captured
        const capturedPiece = {
          type: move.captured,
          color: capturedBy === 'w' ? 'b' : 'w'
        };
        captured[capturedBy].push(capturedPiece);
      }
    }
    return captured;
  }

  /** Get material advantage */
  getMaterialAdvantage() {
    const values = { p: 1, n: 3, b: 3, r: 5, q: 9 };
    const captured = this.getCapturedPieces();
    let whiteScore = 0, blackScore = 0;

    for (const piece of captured.w) {
      whiteScore += values[piece.type] || 0;
    }
    for (const piece of captured.b) {
      blackScore += values[piece.type] || 0;
    }

    return whiteScore - blackScore;
  }
}
