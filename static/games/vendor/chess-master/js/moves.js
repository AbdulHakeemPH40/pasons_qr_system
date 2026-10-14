/**
 * Move History Panel - Displays moves in standard algebraic notation
 */
export class MovePanel {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
  }

  /** Update the move list display */
  update(moveHistory) {
    if (moveHistory.length === 0) {
      this.container.innerHTML = '<div class="move-empty">No moves yet. White to play.</div>';
      return;
    }

    let html = '';
    const moves = moveHistory.map(m => m.san);

    for (let i = 0; i < moves.length; i += 2) {
      const moveNum = Math.floor(i / 2) + 1;
      const whiteMove = moves[i];
      const blackMove = moves[i + 1] || '';
      const isLatestWhite = i === moves.length - 1;
      const isLatestBlack = i + 1 === moves.length - 1;

      html += `
        <div class="move-row">
          <span class="move-number">${moveNum}.</span>
          <span class="move-cell ${isLatestWhite ? 'latest' : ''}">${whiteMove}</span>
          <span class="move-cell ${isLatestBlack ? 'latest' : ''}">${blackMove}</span>
        </div>
      `;
    }

    this.container.innerHTML = html;

    // Auto-scroll to bottom
    this.container.scrollTop = this.container.scrollHeight;
  }

  /** Clear the move list */
  clear() {
    this.container.innerHTML = '<div class="move-empty">No moves yet. White to play.</div>';
  }
}
