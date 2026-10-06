/**
 * Memory Match. Easy mode uses pictures only, so a toddler can play it.
 */
export function start(container, { roundSeconds, onEnd }) {
  const foods = ["burger", "fries", "pizza", "taco", "juice", "donut", "cake", "salad", "tea", "fruit"];
  const colors = ["#e7b56a", "#f0d36c", "#e7a15a", "#d7c56a", "#f0a36a", "#e8b7c8", "#d9c2ea", "#7fa06b", "#c9d7c2", "#f3c1d4"];
  let pairs = 6;
  let multiplier = 1;
  let moves = 0;
  let matched = 0;
  let open = [];
  let lock = false;
  let over = false;
  const started = performance.now();
  const board = document.createElement("div");
  board.className = "kp-memory";
  board.setAttribute("role", "group");
  board.setAttribute("aria-label", "Memory Match");
  container.appendChild(board);

  function finish(found) {
    if (over) return;
    over = true;
    const elapsed = (performance.now() - started) / 1000;
    const bonus = found === pairs ? Math.max(0, Math.round((roundSeconds - elapsed) * 2)) : 0;
    const score = Math.max(0, Math.round(pairs * 100 * multiplier - moves * 5 + bonus));
    onEnd({ score, durationMs: performance.now() - started });
  }

  function deal(count, factor) {
    pairs = count;
    multiplier = factor;
    board.innerHTML = "";
    const deck = foods.slice(0, count).flatMap((food, index) => [index, index]);
    deck.sort(() => Math.random() - 0.5);
    deck.forEach((index) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "kp-card-face";
      card.dataset.index = String(index);
      card.style.setProperty("--food", colors[index]);
      card.setAttribute("aria-label", "Hidden card");
      card.addEventListener("click", () => flip(card));
      board.appendChild(card);
    });
    board.style.gridTemplateColumns = `repeat(${count === 6 ? 4 : count === 8 ? 4 : 5}, 1fr)`;
  }

  function flip(card) {
    if (lock || over || card.classList.contains("is-open")) return;
    card.classList.add("is-open");
    open.push(card);
    if (open.length < 2) return;
    moves += 1;
    const [a, b] = open;
    open = [];
    if (a.dataset.index === b.dataset.index) {
      matched += 1;
      if (matched === pairs) finish(pairs);
      return;
    }
    lock = true;
    setTimeout(() => {
      a.classList.remove("is-open");
      b.classList.remove("is-open");
      lock = false;
    }, 800);
  }

  const picker = document.createElement("div");
  picker.className = "kp-memory-pick";
  [["Easy", 6, 1], ["Medium", 8, 1.5], ["Hard", 10, 2]].forEach(([label, count, factor], index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kp-btn kp-btn--quiet";
    button.textContent = label;
    button.addEventListener("click", () => deal(count, factor));
    picker.appendChild(button);
    if (index === 0) button.setAttribute("aria-current", "true");
  });
  container.prepend(picker);
  deal(6, 1);

  const timer = setTimeout(() => finish(matched), roundSeconds * 1000);
  return {
    destroy() {
      over = true;
      clearTimeout(timer);
      picker.remove();
      board.remove();
    },
  };
}
