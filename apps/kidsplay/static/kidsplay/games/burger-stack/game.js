/**
 * Burger Stack. Tap to drop a sliding layer. A miss ends the round.
 * @param {HTMLElement} container
 * @param {{roundSeconds: number, onEnd: Function}} opts
 */
export function start(container, { roundSeconds, onEnd }) {
  const canvas = document.createElement("canvas");
  canvas.width = 360;
  canvas.height = 480;
  canvas.style.width = "100%";
  canvas.setAttribute("aria-label", "Burger Stack. Tap to drop a layer.");
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const colors = ["#e7b56a", "#8a4b2f", "#f0d36c", "#7fa06b", "#d4533a"];
  let width = 160;
  let x = 40;
  let dir = 1;
  let speed = 2.2;
  let stacked = 0;
  let score = 0;
  let over = false;
  let left = roundSeconds;
  const started = performance.now();
  let paused = false;
  const layers = [];

  function drop() {
    if (over || paused) return;
    const base = layers.length ? layers[layers.length - 1] : { x: 100, width: 160 };
    const overlap = Math.min(x + width, base.x + base.width) - Math.max(x, base.x);
    if (overlap <= 4) {
      finish();
      return;
    }
    const perfect = Math.abs(x - base.x) <= 5;
    x = Math.max(x, base.x);
    width = perfect ? base.width : overlap;
    layers.push({ x, width, color: colors[stacked % colors.length] });
    stacked += 1;
    score += perfect ? 2 : 1;
    if (stacked % 5 === 0) speed += 0.6;
  }

  function finish() {
    if (over) return;
    over = true;
    onEnd({ score, durationMs: performance.now() - started });
  }

  function frame() {
    if (over) return;
    if (!paused) {
      x += dir * speed;
      if (x < 8 || x + width > 352) dir *= -1;
      left = Math.max(0, roundSeconds - (performance.now() - started) / 1000);
      if (left <= 0) finish();
    }
    ctx.clearRect(0, 0, 360, 480);
    ctx.fillStyle = "#fff8e8";
    ctx.fillRect(0, 0, 360, 480);
    ctx.fillStyle = colors[stacked % colors.length];
    ctx.fillRect(x, 36, width, 22);
    layers.forEach((layer, index) => {
      ctx.fillStyle = layer.color;
      ctx.fillRect(layer.x, 430 - index * 24, layer.width, 22);
    });
    ctx.fillStyle = "#31452d";
    ctx.font = "700 22px system-ui";
    ctx.fillText(String(Math.ceil(left)), 16, 28);
    if (!over) requestAnimationFrame(frame);
  }

  function onPointer() { drop(); }
  canvas.addEventListener("pointerdown", onPointer);
  function onHide() { paused = document.hidden; }
  document.addEventListener("visibilitychange", onHide);
  requestAnimationFrame(frame);

  return {
    destroy() {
      over = true;
      canvas.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("visibilitychange", onHide);
      canvas.remove();
    },
  };
}
