/**
 * Shared playfield dressing.
 *
 * Two flat scenery layers plus the ground strip, drawn from the restaurant
 * background pack. Purely decorative: it never takes input, never moves a
 * collider, and is never the only place a piece of information appears.
 *
 * Parallax is skipped when the player asked for reduced motion.
 */

const WAVE_TEXTURE_WIDTH = 320;

/**
 * Paint one rolling-hill strip into a reusable texture.
 *
 * Deliberately a 2D canvas rather than Graphics.generateTexture(): generate
 * texture reads the rendered pixels back off the GPU, which costs a visible
 * stall on the mid-range Android hardware this has to run on.
 */
function hillTexture(scene, key, color, height, amplitude, phase) {
  const canvas = document.createElement("canvas");
  canvas.width = WAVE_TEXTURE_WIDTH;
  canvas.height = height;

  const ctx = canvas.getContext("2d");
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(0, height);
  for (let x = 0; x <= WAVE_TEXTURE_WIDTH; x += 8) {
    const y =
      height * 0.55 +
      Math.sin((x / WAVE_TEXTURE_WIDTH) * Math.PI * 2 + phase) * amplitude +
      Math.sin((x / WAVE_TEXTURE_WIDTH) * Math.PI * 6 + phase) * amplitude * 0.28;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(WAVE_TEXTURE_WIDTH, height);
  ctx.closePath();
  ctx.fill();

  scene.textures.addCanvas(key, canvas);
  return key;
}

/**
 * @param {Phaser.Scene} scene
 * @param {object} theme - a background pack from conf.py
 * @param {object} opts
 * @param {number} opts.width
 * @param {number} opts.height
 * @param {number} opts.groundY - top of the ground strip
 * @param {number} [opts.groundHeight]
 * @returns {{update: function(number): void}}
 */
export function createBackdrop(scene, theme, { width, height, groundY, groundHeight = 8 }) {
  const toColor = (hex) => Number.parseInt(String(hex).replace("#", ""), 16);
  const uid = `${scene.scene.key}-${Math.random().toString(36).slice(2, 7)}`;

  scene.cameras.main.setBackgroundColor(theme.sky);

  hillTexture(scene, `gp-far-${uid}`, theme.far, 150, 22, 0.6);
  hillTexture(scene, `gp-near-${uid}`, theme.near, 190, 30, 2.1);

  const far = scene.add
    .tileSprite(0, groundY - 40, width, 150, `gp-far-${uid}`)
    .setOrigin(0, 1)
    .setScrollFactor(0)
    .setDepth(-30);

  const near = scene.add
    .tileSprite(0, groundY + 2, width, 190, `gp-near-${uid}`)
    .setOrigin(0, 1)
    .setScrollFactor(0)
    .setDepth(-20);

  scene.add
    .rectangle(width / 2, groundY + groundHeight / 2, width, groundHeight, toColor(theme.ground))
    .setScrollFactor(0)
    .setDepth(-10);

  return {
    update(delta) {
      if (scene.reducedMotion) return;
      const dt = delta / 1000;
      far.tilePositionX += 11 * dt;
      near.tilePositionX += 26 * dt;
    },
  };
}

/** Draw a burger out of flat shapes. Returns the container. */
export function drawBurger(scene, x, y, size, theme, depth = 5) {
  const toColor = (hex) => Number.parseInt(String(hex).replace("#", ""), 16);
  const c = scene.add.container(x, y).setDepth(depth);
  const w = size;
  const h = size * 0.82;

  const top = scene.add.graphics();
  top.fillStyle(toColor(theme.accent), 1);
  top.fillRoundedRect(-w / 2, -h / 2, w, h * 0.34, [h * 0.17, h * 0.17, 3, 3]);
  c.add(top);

  const fill = scene.add.graphics();
  fill.fillStyle(0x79b36b, 1);
  fill.fillRoundedRect(-w / 2 - 2, -h / 2 + h * 0.32, w + 4, h * 0.17, 4);
  c.add(fill);

  const patty = scene.add.graphics();
  patty.fillStyle(0x8a5a34, 1);
  patty.fillRoundedRect(-w / 2, -h / 2 + h * 0.48, w, h * 0.2, 4);
  c.add(patty);

  const bottom = scene.add.graphics();
  bottom.fillStyle(toColor(theme.accent), 1);
  bottom.fillRoundedRect(-w / 2, -h / 2 + h * 0.68, w, h * 0.32, [3, 3, h * 0.16, h * 0.16]);
  c.add(bottom);

  return c;
}
