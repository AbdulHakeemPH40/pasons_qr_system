/**
 * Memory Match — pairs.
 *
 * Tap a tile to turn it over, tap another, find all six pairs before the clock
 * runs out. Tap is the control; arrow keys and Enter do the same thing for
 * anyone not using a touch screen.
 */

import { createBackdrop } from "./common.js";

const SYMBOLS = ["circle", "square", "triangle", "diamond", "ring", "bars"];

function drawSymbol(scene, kind, color, size) {
  const g = scene.add.graphics();
  g.fillStyle(color, 1);
  g.lineStyle(4, color, 1);
  const r = size;

  if (kind === "circle") g.fillCircle(0, 0, r);
  else if (kind === "square") g.fillRect(-r, -r, r * 2, r * 2);
  else if (kind === "triangle") g.fillTriangle(0, -r, r, r, -r, r);
  else if (kind === "diamond") g.fillPoints([{ x: 0, y: -r }, { x: r, y: 0 }, { x: 0, y: r }, { x: -r, y: 0 }], true);
  else if (kind === "ring") {
    g.fillCircle(0, 0, r);
    g.fillStyle(0xffffff, 1);
    g.fillCircle(0, 0, r * 0.46);
  } else {
    for (let i = -1; i <= 1; i += 1) g.fillRect(-r, i * (r * 0.72) - r * 0.18, r * 2, r * 0.36);
  }
  return g;
}

export function createGame(ctx) {
  const { Phaser, host, theme, tuning, playfield, emit, reducedMotion } = ctx;
  const W = playfield.width;
  const H = playfield.height;
  const toColor = (hex) => Number.parseInt(String(hex).replace("#", ""), 16);

  let game = null;

  class MatchScene extends Phaser.Scene {
    constructor() {
      super({ key: "Main" });
    }

    create() {
      this.reducedMotion = reducedMotion;
      this.backdrop = createBackdrop(this, theme, { width: W, height: H, groundY: H });

      const cols = tuning.cols;
      const rows = tuning.rows;
      const gap = tuning.tileGap;
      const marginX = 26;
      const gridTop = 118;
      const tileW = (W - marginX * 2 - gap * (cols - 1)) / cols;
      const tileH = 104;

      // six symbols, each twice, shuffled
      const deck = [...SYMBOLS, ...SYMBOLS];
      for (let i = deck.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [deck[i], deck[j]] = [deck[j], deck[i]];
      }

      this.tiles = deck.map((symbol, index) => {
        const col = index % cols;
        const row = Math.floor(index / cols);
        const x = marginX + col * (tileW + gap) + tileW / 2;
        const y = gridTop + row * (tileH + gap) + tileH / 2;

        const node = this.add.container(x, y).setDepth(4);
        const back = this.add.graphics();
        back.fillStyle(toColor(theme.ground), 1);
        back.fillRoundedRect(-tileW / 2, -tileH / 2, tileW, tileH, 14);
        node.add(back);

        const face = this.add.graphics();
        face.fillStyle(0xffffff, 0.92);
        face.fillRoundedRect(-tileW / 2, -tileH / 2, tileW, tileH, 14);
        face.setVisible(false);
        node.add(face);

        const mark = drawSymbol(this, symbol, toColor(theme.near), 21);
        mark.setVisible(false);
        node.add(mark);

        const ring = this.add.graphics();
        ring.lineStyle(3, toColor(theme.accent), 1);
        ring.strokeRoundedRect(-tileW / 2 - 3, -tileH / 2 - 3, tileW + 6, tileH + 6, 16);
        ring.setVisible(false);
        node.add(ring);

        const tile = { node, back, face, mark, ring, symbol, up: false, matched: false };
        node.setSize(tileW, tileH);
        node.setInteractive({ useHandCursor: true });
        node.on("pointerdown", () => this.flip(tile));
        return tile;
      });

      this.cursor = 0;
      this.paintCursor();

      this.input.keyboard.on("keydown-LEFT", () => this.moveCursor(-1, 0));
      this.input.keyboard.on("keydown-RIGHT", () => this.moveCursor(1, 0));
      this.input.keyboard.on("keydown-UP", () => this.moveCursor(0, -1));
      this.input.keyboard.on("keydown-DOWN", () => this.moveCursor(0, 1));
      this.input.keyboard.on("keydown-ENTER", () => this.flip(this.tiles[this.cursor]));
      this.input.keyboard.on("keydown-SPACE", (e) => {
        e.preventDefault();
        this.flip(this.tiles[this.cursor]);
      });

      this.first = null;
      this.locked = false;
      this.matched = 0;
      this.seconds = tuning.roundSeconds;
      this.finished = false;

      this.clock = this.add
        .text(W / 2, 62, this.formatTime(), {
          fontFamily: "system-ui, sans-serif",
          fontSize: "30px",
          fontStyle: "600",
          color: "#31452D",
        })
        .setOrigin(0.5)
        .setDepth(6);

      emit.score(0);
      emit.feedback("Find all six pairs");
    }

    formatTime() {
      return `${Math.max(0, Math.ceil(this.seconds))}s`;
    }

    moveCursor(dx, dy) {
      const cols = tuning.cols;
      const rows = tuning.rows;
      let col = this.cursor % cols;
      let row = Math.floor(this.cursor / cols);
      col = Math.max(0, Math.min(cols - 1, col + dx));
      row = Math.max(0, Math.min(rows - 1, row + dy));
      this.cursor = row * cols + col;
      this.paintCursor();
    }

    paintCursor() {
      this.tiles.forEach((t, i) => t.ring.setVisible(i === this.cursor && !t.matched));
    }

    flip(tile) {
      if (this.finished || this.locked || tile.up || tile.matched) return;

      tile.up = true;
      tile.back.setVisible(false);
      tile.face.setVisible(true);
      tile.mark.setVisible(true);

      if (!reducedMotion) {
        tile.node.setScale(0.86, 1);
        this.tweens.add({ targets: tile.node, scaleX: 1, scaleY: 1, duration: 130 });
      }

      if (!this.first) {
        this.first = tile;
        emit.feedback("Now find its pair");
        return;
      }

      const first = this.first;
      this.first = null;
      this.locked = true;

      if (first.symbol === tile.symbol) {
        first.matched = true;
        tile.matched = true;
        this.matched += 1;
        this.locked = false;
        this.paintCursor();
        emit.score(this.matched * tuning.pairScore);
        emit.feedback(`Pair found — ${this.matched} of ${tuning.pairs}`);

        if (this.matched === tuning.pairs) this.finish("complete");
      } else {
        this.time.delayedCall(tuning.flipBackDelayMs, () => {
          [first, tile].forEach((t) => {
            t.up = false;
            t.back.setVisible(true);
            t.face.setVisible(false);
            t.mark.setVisible(false);
          });
          this.locked = false;
          emit.feedback("Not a pair — try again");
        });
      }
    }

    finish(reason) {
      if (this.finished) return;
      this.finished = true;

      let score = this.matched * tuning.pairScore;
      if (reason === "complete") {
        score += Math.ceil(Math.max(0, this.seconds)) * tuning.timeBonusPerSecond;
      }
      emit.score(score);
      emit.feedback(
        reason === "complete"
          ? `All pairs found — ${Math.ceil(Math.max(0, this.seconds))}s left`
          : `Time's up — ${this.matched} of ${tuning.pairs} pairs`,
      );
      emit.end({ reason, score, won: reason === "complete" });
    }

    update(_time, delta) {
      this.backdrop.update(delta);
      if (this.finished) return;

      this.seconds -= delta / 1000;
      if (this.clock) this.clock.setText(this.formatTime());
      if (this.seconds <= 0) {
        this.seconds = 0;
        this.finish("time-up");
      }
    }
  }

  return {
    start() {
      game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: host,
        backgroundColor: theme.sky,
        banner: false,
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_BOTH,
          width: W,
          height: H,
        },
        fps: { target: playfield.targetFps },
        render: { antialias: true, roundPixels: true },
        scene: [MatchScene],
      });
    },
    pause() {
      if (game) game.scene.pause("Main");
    },
    resume() {
      if (game) game.scene.resume("Main");
    },
    restart() {
      if (!game) return;
      game.scene.stop("Main");
      game.scene.start("Main");
    },
    destroy() {
      if (game) {
        game.destroy(true);
        game = null;
      }
    },
  };
}

export const meta = {
  slug: "memory-match",
  control: "Tap two tiles, or use the arrow keys and Enter",
};
