/**
 * Food Catcher. Drag the plate. Good food scores, bad food costs a life.
 */
export function start(container, { roundSeconds, onEnd }) {
  const canvas = document.createElement("canvas");
  canvas.width = 360;
  canvas.height = 480;
  canvas.style.width = "100%";
  canvas.setAttribute("aria-label", "Food Catcher. Drag the plate.");
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const good = ["#e7b56a", "#7fa06b", "#f0a36a"];
  const bad = ["#6b6258", "#8a3b2a"];
  let plate = 140;
  let score = 0;
  let lives = 3;
  let over = false;
  let paused = false;
  const started = performance.now();
  const items = [];
  let spawnIn = 0;

  function finish() {
    if (over) return;
    over = true;
    onEnd({ score, durationMs: performance.now() - started });
  }

  function pointer(event) {
    const rect = canvas.getBoundingClientRect();
    plate = ((event.clientX - rect.left) / rect.width) * 360 - 36;
    plate = Math.max(8, Math.min(280, plate));
  }

  function frame(now) {
    if (over) return;
    const elapsed = (now - started) / 1000;
    if (!paused) {
      if (elapsed >= roundSeconds) finish();
      spawnIn -= 1;
      if (spawnIn <= 0) {
        const isBad = Math.random() < 0.28;
        const golden = !isBad && Math.random() < 0.08;
        items.push({
          x: 20 + Math.random() * 300,
          y: -20,
          bad: isBad,
          golden,
          color: isBad ? bad[Math.floor(Math.random() * bad.length)] : good[Math.floor(Math.random() * good.length)],
          speed: 2.4 + elapsed * 0.08,
        });
        spawnIn = Math.max(18, 46 - elapsed);
      }
      items.forEach((item) => { item.y += item.speed; });
      items.forEach((item) => {
        const caught = item.y > 430 && item.x > plate - 8 && item.x < plate + 80;
        if (caught) {
          if (item.bad) lives -= 1;
          else score += item.golden ? 5 : 1;
          item.y = 999;
        }
      });
      if (lives <= 0) finish();
    }
    ctx.clearRect(0, 0, 360, 480);
    ctx.fillStyle = "#f4f8ef";
    ctx.fillRect(0, 0, 360, 480);
    ctx.fillStyle = "#31452d";
    ctx.fillRect(plate, 448, 72, 14);
    items.filter((item) => item.y < 500).forEach((item) => {
      ctx.fillStyle = item.golden ? "#d5c98a" : item.color;
      ctx.beginPath();
      ctx.arc(item.x, item.y, item.bad ? 12 : 14, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.fillStyle = "#31452d";
    ctx.font = "700 20px system-ui";
    ctx.fillText(`${score}   lives ${lives}`, 16, 28);
    if (!over) requestAnimationFrame(frame);
  }

  canvas.addEventListener("pointerdown", pointer);
  canvas.addEventListener("pointermove", pointer);
  function onHide() { paused = document.hidden; }
  document.addEventListener("visibilitychange", onHide);
  requestAnimationFrame(frame);
  return {
    destroy() {
      over = true;
      canvas.removeEventListener("pointerdown", pointer);
      canvas.removeEventListener("pointermove", pointer);
      document.removeEventListener("visibilitychange", onHide);
      canvas.remove();
    },
  };
}
