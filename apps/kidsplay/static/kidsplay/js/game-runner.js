/**
 * Loads one game module. The game never talks to the network.
 */
const mount = document.getElementById("kp-game");
const status = document.getElementById("kp-status");
const slug = mount.dataset.slug;
const table = mount.dataset.table;
let muted = false;
let ended = false;

function csrf() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
    body: JSON.stringify(body),
  });
  return { ok: response.ok, status: response.status, data: await response.json() };
}

function showResult(data) {
  const cap = data.cap_reached
    ? "Great score! You've reached today's points limit — come back next time for more!"
    : "";
  status.textContent = data.points_awarded
    ? `Score ${data.score}. You earned ${data.points_awarded} points. Balance ${data.balance}.`
    : `Nice try! Score ${data.score}. Play again?`;
  if (cap) status.textContent += " " + cap;
  const again = document.createElement("button");
  again.className = "kp-btn";
  again.type = "button";
  again.textContent = "Play again";
  again.addEventListener("click", () => window.location.reload());
  status.after(again);
}

document.getElementById("kp-mute").addEventListener("click", (event) => {
  muted = !muted;
  event.currentTarget.textContent = muted ? "Sound off" : "Sound on";
  mount.dispatchEvent(new CustomEvent("kp-mute", { detail: muted }));
});

const started = await post("/api/kidsplay/game/start", { game: slug });
if (!started.ok) {
  status.textContent = started.data.error === "no_active_visit"
    ? "Scan your table QR to play."
    : "This game can't start right now.";
} else {
  const module = await import(`/static/kidsplay/games/${slug}/game.js`);
  const startedAt = performance.now();
  const running = module.start(mount, {
    roundSeconds: started.data.config.round_seconds,
    onEnd(result) {
      if (ended) return;
      ended = true;
      post("/api/kidsplay/game/finish", {
        token: started.data.token,
        score: result.score,
        duration_ms: Math.round(result.durationMs || performance.now() - startedAt),
      }).then((finished) => showResult(finished.data));
    },
  });
  window.addEventListener("pagehide", () => running.destroy());
}
