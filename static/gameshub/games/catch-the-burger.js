/**
 * Catch the Burger — one-touch 2D runner.
 *
 * Tap to hop. Burgers in the air are worth points, everything else ends the
 * round. Gravity and collisions are integrated by hand rather than through the
 * physics plugin: one moving object does not need a physics world, and keeping
 * it explicit makes the jump feel testable.
 */

import { createBackdrop, drawBurger } from "./common.js";

function overlaps(a, b, shrink = 0) {
  return (
    Math.abs(a.x - b.x) * 2 < a.w + b.w - shrink && Math.abs(a.y - b.y) * 2 < a.h + b.h - shrink
  );
}

export function createGame(ctx) {
  const { Phaser, host, theme, tuning, playfield, emit, reducedMotion } = ctx;
  const W = playfield.width;
  const H = playfield.height;
  const toColor = (hex) => Number.parseInt(String(hex).replace("#", ""), 16);

  let game = null;

  class RunnerScene extends Phaser.Scene {
    constructor() {
      super({ key: "Main" });
    }

    create() {
      this.reducedMotion = reducedMotion;
      this.backdrop = createBackdrop(this, theme, {
        width: W,
        height: H,
        groundY: tuning.groundY,
      });

      this.player = {
        x: tuning.playerX,
        y: tuning.groundY - tuning.playerSize / 2,
        w: tuning.playerSize,
        h: tuning.playerSize,
        vy: 0,
        onGround: true,
      };

      this.body = this.add
        .rectangle(this.player.x, this.player.y, this.player.w, this.player.h, toColor(theme.accent))
        .setDepth(6);
      this.shadowY = this.player.y + tuning.playerSize / 2 - 4;
      this.shadow = this.add
        .rectangle(this.player.x, this.shadowY, this.player.w - 18, 10, toColor(theme.ground), 0.32)
        .setDepth(4);

      this.obstacles = [];
      this.pickups = [];
      this.speed = tuning.startSpeed;
      this.elapsed = 0;
      this.burgers = 0;
      this.finished = false;
      this.nextSpawn = 1.1;

      this.score = 0;
      emit.score(0);
      emit.feedback("Tap to hop");

      this.input.on("pointerdown", () => this.jump());
      if (this.input.keyboard) {
        this.input.keyboard.on("keydown-SPACE", (e) => {
          e.preventDefault();
          this.jump();
        });
        this.input.keyboard.on("keydown-UP", () => this.jump());
        this.input.keyboard.on("keydown-W", () => this.jump());
      }
    }

    jump() {
      if (this.finished) return;
      if (!this.player.onGround) return;
      this.player.vy = tuning.jumpVelocity;
      this.player.onGround = false;
    }

    spawnObstacle() {
      const tall = Math.random() < 0.5;
      const w = tall ? 34 : 62;
      const h = tall ? 92 : 52;
      const x = W + w;
      const y = tuning.groundY - h / 2;
      const rect = this.add
        .rectangle(x, y, w, h, toColor(theme.ground))
        .setDepth(5)
        .setAlpha(0.92);
      this.obstacles.push({ x, y, w, h, rect });

      if (Math.random() < tuning.burgerChance) {
        const by = tuning.groundY - 120 - Math.random() * 120;
        const burger = drawBurger(this, W + w + 90, by, 46, theme);
        this.pickups.push({ x: W + w + 90, y: by, w: 44, h: 44, node: burger, taken: false });
      }
    }

    collect(pickup) {
      pickup.taken = true;
      pickup.node.destroy();
      this.burgers += 1;
      this.score += tuning.burgerScore;
      emit.score(this.score);
      emit.feedback(`+${tuning.burgerScore} burger`);
    }

    die() {
      if (this.finished) return;
      this.finished = true;
      this.tweens.add({
        targets: this.body,
        angle: 26,
        alpha: 0.75,
        duration: reducedMotion ? 1 : 220,
      });
      emit.feedback(`${this.burgers} burgers caught`);
      emit.end({ reason: "game-over", score: this.score, won: false });
    }

    update(_time, delta) {
      const dt = Math.min(delta / 1000, 1 / 20);
      this.backdrop.update(delta);

      if (this.finished) return;

      this.elapsed += dt;
      this.speed = Math.min(tuning.maxSpeed, tuning.startSpeed + this.elapsed * tuning.speedRampPerSecond);

      // player integration
      this.player.vy += tuning.gravity * dt;
      this.player.y += this.player.vy * dt;
      const floorY = tuning.groundY - tuning.playerSize / 2;
      if (this.player.y >= floorY) {
        this.player.y = floorY;
        this.player.vy = 0;
        this.player.onGround = true;
      }
      this.body.setPosition(this.player.x, this.player.y);

      // The shadow stays on the ground and reacts to the height of the hop.
      const lift = this.shadowY - (this.player.y + tuning.playerSize / 2 - 4);
      this.shadow.setScale(Math.max(0.55, 1 - lift / 420), 1);
      this.shadow.setAlpha(Math.max(0.08, 0.32 - lift / 520));

      // survival score
      const survival = Math.floor(this.elapsed * tuning.survivalScorePerSecond);
      const total = this.burgers * tuning.burgerScore + survival;
      if (total !== this.score) {
        this.score = total;
        emit.score(this.score);
      }

      // spawn
      this.nextSpawn -= dt;
      if (this.nextSpawn <= 0) {
        this.spawnObstacle();
        const t = Math.min(1, this.elapsed / 75);
        const gap =
          tuning.spawnGapMax - (tuning.spawnGapMax - tuning.spawnGapMin) * t;
        this.nextSpawn = gap * (0.86 + Math.random() * 0.32);
      }

      // move + cull
      const step = this.speed * dt;
      for (const o of this.obstacles) {
        o.x -= step;
        o.rect.setPosition(o.x, o.y);
      }
      this.obstacles = this.obstacles.filter((o) => {
        if (o.x < -140) {
          o.rect.destroy();
          return false;
        }
        return true;
      });

      for (const p of this.pickups) {
        p.x -= step;
        p.node.setPosition(p.x, p.y);
      }
      this.pickups = this.pickups.filter((p) => {
        if (p.taken || p.x < -140) {
          if (!p.taken) p.node.destroy();
          return false;
        }
        return true;
      });

      // collisions
      for (const p of this.pickups) {
        if (!p.taken && overlaps(this.player, p, 6)) this.collect(p);
      }
      for (const o of this.obstacles) {
        if (overlaps(this.player, o, tuning.hitboxShrink)) {
          this.die();
          return;
        }
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
        scene: [RunnerScene],
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
  slug: "catch-the-burger",
  control: "Tap, or press Space / Up",
};
