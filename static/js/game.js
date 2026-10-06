// Vanilla JS Dish Match Game (Spec Part C.5)
(function () {
  const config = window.GAME_CONFIG || {};
  const gridEl = document.getElementById("grid");
  const timerEl = document.getElementById("game-timer");
  const modalEl = document.getElementById("game-modal");
  const modalContentEl = document.getElementById("modal-content");
  const boardContainer = document.getElementById("game-board-container");

  if (!gridEl) return;

  const icons = config.icons || ["🍲", "🍗", "☕", "🍨", "🥗", "🍔"];
  const deck = [...icons, ...icons].sort(() => Math.random() - 0.5);

  let flippedCards = [];
  let matchedCount = 0;
  let moves = 0;
  let startTime = Date.now();
  let timeLeft = config.timeLimit || 60;
  let timerInterval = null;
  let isGameOver = false;

  deck.forEach((icon, index) => {
    const tile = document.createElement("div");
    tile.classList.add("tile");
    tile.dataset.icon = icon;
    tile.dataset.index = index;
    tile.textContent = "❓";

    tile.addEventListener("click", () => onCardClick(tile));
    gridEl.appendChild(tile);
  });

  timerInterval = setInterval(() => {
    if (isGameOver) return;
    timeLeft--;
    if (timerEl) timerEl.textContent = timeLeft + "s";

    if (timeLeft <= 0) {
      clearInterval(timerInterval);
      handleGameOver(false, "Time is up! Try again next time.");
    }
  }, 1000);

  function onCardClick(tile) {
    if (isGameOver || tile.classList.contains("flipped") || tile.classList.contains("matched") || flippedCards.length >= 2) {
      return;
    }

    tile.classList.add("flipped");
    tile.textContent = tile.dataset.icon;
    flippedCards.push(tile);

    if (flippedCards.length === 2) {
      moves++;
      const [card1, card2] = flippedCards;
      if (card1.dataset.icon === card2.dataset.icon) {
        card1.classList.add("matched");
        card2.classList.add("matched");
        matchedCount += 2;
        flippedCards = [];

        if (matchedCount === deck.length) {
          clearInterval(timerInterval);
          handleGameOver(true);
        }
      } else {
        setTimeout(() => {
          card1.classList.remove("flipped");
          card1.textContent = "❓";
          card2.classList.remove("flipped");
          card2.textContent = "❓";
          flippedCards = [];
        }, 600);
      }
    }
  }

  function handleGameOver(isSuccess) {
    isGameOver = true;
    const timeSpent = Math.round((Date.now() - startTime) / 1000);

    if (!isSuccess) {
      modalContentEl.innerHTML = `
        <h2 style="font-size: 1.3rem; margin-bottom: 8px;">Time Expired</h2>
        <p class="muted" style="margin-bottom: 16px;">Don't worry, feel free to try again on your next visit!</p>
        <a href="../" class="btn btn-secondary">Return to Menu</a>
      `;
      modalEl.style.display = "block";
      boardContainer.style.opacity = "0.4";
      return;
    }

    // Submit results to server
    modalContentEl.innerHTML = `<p class="muted">Verifying game completion...</p>`;
    modalEl.style.display = "block";

    fetch(config.resultUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": config.csrfToken
      },
      body: JSON.stringify({
        moves: moves,
        time_seconds: timeSpent
      })
    })
    .then(res => res.json())
    .then(data => {
      boardContainer.style.display = "none";
      if (data.won) {
        modalContentEl.innerHTML = `
          <div style="font-size: 2.5rem; margin-bottom: 8px;">🎉</div>
          <h2 style="font-size: 1.4rem; color: var(--forest); margin: 0 0 6px;">You've Succeeded!</h2>
          <p style="font-size: 0.9rem; margin-bottom: 12px;">Here is your exclusive dining voucher:</p>
          <div style="background: rgba(255,255,255,0.9); padding: 12px; border-radius: var(--r-lg); border: 2px dashed var(--leaf); margin-bottom: 12px;">
            <p style="font-size: 1.4rem; font-weight: 800; letter-spacing: 2px; color: var(--leaf); margin: 0 0 4px;">${data.coupon_code}</p>
            <p style="font-size: 1rem; font-weight: 700; color: var(--forest); margin: 0;">${data.discount}</p>
          </div>
          <p class="caption" style="margin-bottom: 4px;">VALID AT: <strong>${data.outlet_name}</strong></p>
          <p class="muted" style="font-size: 0.78rem; margin-bottom: 16px;">Expires: ${data.expires_at} · Show this code to your waiter</p>
          <a href="../" class="btn btn-primary btn-block">Back to Options</a>
        `;
      } else {
        modalContentEl.innerHTML = `
          <div style="font-size: 2.2rem; margin-bottom: 8px;">👏</div>
          <h2 style="font-size: 1.3rem; margin: 0 0 8px;">Great Effort!</h2>
          <p class="muted" style="font-size: 0.88rem; margin-bottom: 16px;">${data.message || "Thank you for playing with us today! Try again tomorrow."}</p>
          <a href="../" class="btn btn-secondary btn-block">Back to Options</a>
        `;
      }
    })
    .catch(() => {
      modalContentEl.innerHTML = `
        <p class="muted">Connection error submitting game result.</p>
        <a href="../" class="btn btn-secondary">Back to Options</a>
      `;
    });
  }
})();
