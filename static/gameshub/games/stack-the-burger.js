/**
 * Stack the Burger — one-touch stacking.
 *
 * A layer slides across the top of the tower. Tap to drop it. Only the part
 * still sitting on the layer below survives; the rest falls away and the tower
 * gets narrower. Drop it dead centre to hold the width.
 */

import { createBackdrop } from "./common.js";

function overlapOf(top, bottom) {
  const left = Math.max(top.x - top.w / 2, bottom.x - bottom.w / 2);
  const right = Math.min(top.x + top.w / 2, bottom.x + bottom.w / 2);
  return { left, right, width: right - left, center: (left + right) / 2 };
}

export function createGame(ctx) {
  const { Phaser, host, theme, tuning, playfield, emit, reducedMotion } = ctx;
  const W = playfield.width;
  const H = playfield.height;
  const toColor = (hex) => Number.parseInt(String(hex).replace("#", ""), 16);

  const LAYER_COLORS = [toColor(theme.accent), toColor(theme.near), toColor(theme.ground)];

  let game = null;

  class StackScene extends Phaser.Scene {
    constructor() {
      super({ key: "Main" });
    }

    create() {
      this.reducedMotion = reducedMotion;
      this.backdrop = createBackdrop(this, theme, {
        width: W,
        height: H,
        groundY: tuning.baseY + tuning.layerHeight / 2,
      });

      this.spawnY = 232;
      this.layers = [];
      this.placed = 0;
      this.perfects = 0;
      this.finished = false;
      this.score = 0;

      // the base the tower stands on
      this.pushLayer(W / 2, tuning.baseY, tuning.layerWidth, true);

      this.direction = 1;
      this.speed = tuning.moveSpeed;
      this.moving = this.makeMovingLayer();

      emit.score(0);
      emit.feedback("Tap to drop the layer");

      this.input.on("pointerdown", () => this.drop());
      if (this.input.keyboard) {
        this.input.keyboard.on("keydown-SPACE", (e) => {
          e.preventDefault();
          this.drop();
        });
        this.input.keyboard.on("keydown-ENTER", () => this.drop());
      }
    }

    pushLayer(x, y, w, still = false) {
      const index = this.layers.length;
      const node = this.add
        .rectangle(x, y, w, tuning.layerHeight, LAYER_COLORS[index % LAYER_COLORS.length])
        .setDepth(5);
      node.setDisplaySize(w, tuning.layerHeight);
      const layer = { x, y, w, h: tuning.layerHeight, node, still };
      this.layers.push(layer);
      return layer;
    }

    /**
     * The topmost layer that has already landed.
     *
     * Never assume this is `layers[layers.length - 1]`: the sliding layer is
     * pushed onto the same array the moment it is created, so the last element
     * is usually the one still in the air. Reading the wrong layer makes every
     * drop look perfectly centred and the tower never narrows.
     */
    topSettled() {
      for (let i = this.layers.length - 1; i >= 0; i -= 1) {
        if (this.layers[i].still) return this.layers[i];
      }
      return null;
    }

    makeMovingLayer() {
      const below = this.topSettled();
      const x = below.w > 0 ? 70 : W / 2;
      const layer = this.pushLayer(x, this.spawnY, below.w, false);
      layer.node.setAlpha(0.96);
      return layer;
    }

    drop() {
      if (this.finished || this.movingTween) return;

      const moving = this.moving;
      const below = this.topSettled();
      const result = overlapOf(moving, below);

      if (result.width <= 1) {
        this.tweens.add({
          targets: moving.node,
          y: H + 160,
          alpha: 0,
          duration: reducedMotion ? 1 : 380,
        });
        this.endRound("game-over");
        return;
      }

      const perfect = Math.abs(moving.x - below.x) <= tuning.perfectTolerance;
      const newWidth = perfect ? below.w : Math.max(tuning.minWidth, result.width);
      const newX = perfect ? below.x : result.center;

      // the slice that missed the tower falls away
      if (!perfect && result.width < moving.w - 1) {
        const overhang = moving.w - result.width;
        const side = moving.x > below.x ? 1 : -1;
        const sliceX = newX + side * (newWidth / 2 + overhang / 2);
        const slice = this.add
          .rectangle(sliceX, moving.y, overhang, tuning.layerHeight, moving.node.fillColor)
          .setDepth(4);
        this.tweens.add({
          targets: slice,
          y: H + 160,
          alpha: 0,
          angle: side * 12,
          duration: reducedMotion ? 1 : 420,
          onComplete: () => slice.destroy(),
        });
      }

      moving.x = newX;
      moving.w = newWidth;
      moving.still = true;
      moving.node.setPosition(newX, moving.y);
      moving.node.setDisplaySize(newWidth, tuning.layerHeight);
      moving.node.setAlpha(1);

      this.placed += 1;
      this.speed = Math.min(
        tuning.maxMoveSpeed,
        tuning.moveSpeed + this.placed * tuning.moveSpeedPerLayer,
      );

      if (perfect) {
        this.perfects += 1;
        this.score += tuning.perfectBonus + tuning.layerScore;
        emit.feedback("Dead centre — bonus");
      } else {
        this.score += tuning.layerScore;
        emit.feedback(`${this.placed} layer${this.placed === 1 ? "" : "s"} stacked`);
      }
      emit.score(this.score);

      if (newWidth <= tuning.minWidth + 1) {
        this.endRound("game-over");
        return;
      }

      // climb: shift the tower down so the next layer lands in the same place
      this.movingTween = this.tweens.add({
        targets: this.layers.map((l) => l.node),
        y: "+=" + tuning.layerHeight,
        duration: reducedMotion ? 1 : 170,
        ease: "Sine.easeOut",
        onComplete: () => {
          this.layers.forEach((l) => {
            l.y += tuning.layerHeight;
          });
          this.movingTween = null;
          this.moving = this.makeMovingLayer();
        },
      });
    }

    endRound(reason) {
      if (this.finished) return;
      this.finished = true;
      if (this.movingTween) {
        this.movingTween.stop();
        this.movingTween = null;
      }
      emit.feedback(`${this.placed} layers — ${this.perfects} perfect`);
      emit.end({ reason, score: this.score, won: false });
    }

    update(_time, delta) {
      const dt = Math.min(delta / 1000, 1 / 20);
      this.backdrop.update(delta);
      if (this.finished || this.movingTween || !this.moving) return;

      const moving = this.moving;
      moving.x += this.direction * this.speed * dt;
      const half = moving.w / 2;
      const left = 18 + half;
      const right = W - 18 - half;

      if (moving.x <= left) {
        moving.x = left;
        this.direction = 1;
      } else if (moving.x >= right) {
        moving.x = right;
        this.direction = -1;
      }
      moving.node.setPosition(moving.x, moving.y);
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
        scene: [StackScene],
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
  slug: "stack-the-burger",
  control: "Tap, or press Space / Enter",
};
