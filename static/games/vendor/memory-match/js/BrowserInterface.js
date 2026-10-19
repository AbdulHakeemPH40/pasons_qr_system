/**
 * Author: Maximo Mena
 * GitHub: mmenavas
 * Twitter: @menamaximo
 * Project: Memory Workout
 * Description: The game interface
 */

/**
 * @TODO Refactor code.
 */
(function($) {

  /************ Start hard coded settings ******************/

  // How long a non matching card is displayed once clicked.
  var nonMatchingCardTime = 1000;

  // Shuffle card images: How many different images are available to shuffle
  // from?
  var imagesAvailable = 14;

  // Countdown budget: 15s + 15s per pair (Pasons extension, see CHANGES.md).
  // 2x3 = 60s, 3x4 = 105s, 4x5 = 165s, 7x4 = 225s.
  var timeBaseSeconds = 15;
  var timePerPairSeconds = 15;

  /************ End hard coded settings ******************/

  // ---- Countdown + points display (Pasons extension) ----
  var timerId = null;
  var remainingMs = 0;
  var lastTickAt = 0;
  var paused = false;

  // Glass pass: which card indices have been matched this round, so the
  // gold ring survives a resize re-layout. Cleared with each new game.
  var matchedSet = {};

  // Turn guard and input lock. A missed pair stays face up for
  // `nonMatchingCardTime`, but the model conceals both cards the instant the
  // pair resolves. A tap landing inside that window was therefore read
  // against a card the guest could still see: the flip was accepted, the
  // `.clicked` class was toggled OFF (hiding the food they had just turned
  // over), and the pending timeout then stripped the face off the card that
  // had become the new turn's first pick. The card looked face down while
  // the model still held it as selected, so every later tap on it was
  // refused as "already facing up" and the board felt stuck. The board is
  // locked for the window instead, which is what a memory game does: both
  // cards show, both go down, then you may play. `turnId` also lets a
  // pending timeout notice that a new board was dealt and leave it alone.
  var turnId = 0;
  var boardLocked = false;

  var timerEl = document.getElementById('memory--timer');
  var pointsEl = document.getElementById('memory--points');

  var budgetFor = function (rows, columns) {
    var pairs = (rows * columns) / 2;
    return (timeBaseSeconds + timePerPairSeconds * pairs) * 1000;
  };

  var formatTime = function (ms) {
    var total = Math.max(0, Math.ceil(ms / 1000));
    var minutes = Math.floor(total / 60);
    var seconds = total % 60;
    return minutes + ':' + (seconds < 10 ? '0' : '') + seconds;
  };

  var renderTimer = function () {
    if (!timerEl) {
      return;
    }
    timerEl.textContent = formatTime(remainingMs);
    timerEl.classList.toggle('urgent', remainingMs <= 10000 && remainingMs > 0);
  };

  var renderPoints = function () {
    // The shell HUD polls #memory--points as the score (bridge kind "text"),
    // so this element must always hold bare digits.
    if (pointsEl) {
      pointsEl.textContent = String($.points);
    }
  };

  var stopTimer = function () {
    if (timerId !== null) {
      window.clearInterval(timerId);
      timerId = null;
    }
  };

  var tick = function () {
    if (paused) {
      lastTickAt = Date.now();
      return;
    }
    var now = Date.now();
    remainingMs -= (now - lastTickAt);
    lastTickAt = now;
    if (remainingMs <= 0) {
      remainingMs = 0;
      renderTimer();
      endOnTimeout();
      return;
    }
    renderTimer();
  };

  var startTimer = function (ms) {
    stopTimer();
    remainingMs = ms;
    lastTickAt = Date.now();
    paused = false;
    renderTimer();
    timerId = window.setInterval(tick, 250);
  };

  // A guest who backgrounds the app (phone call, waiter) must not lose the
  // round to a clock that kept running while the page was hidden.
  document.addEventListener('visibilitychange', function () {
    paused = document.hidden;
    if (!paused) {
      lastTickAt = Date.now();
    }
  });

  // Handle clicking on settings icon
  var settings = document.getElementById('memory--settings-icon');
  var modal = document.getElementById('memory--settings-modal');
  var handleOpenSettings = function (event) {
    event.preventDefault();
    modal.classList.toggle('show');
  };
  settings.addEventListener('click', handleOpenSettings);

  // Handle settings form submission
  var reset = document.getElementById('memory--settings-reset');
  var handleSettingsSubmission = function (event) {
    event.preventDefault();

    var selectWidget = document.getElementById("memory--settings-grid").valueOf();
    var grid = selectWidget.options[selectWidget.selectedIndex].value;
    var gridValues = grid.split('x');
    var cards = $.initialize(Number(gridValues[0]), Number(gridValues[1]), imagesAvailable);

    if (cards) {
      document.getElementById('memory--settings-modal').classList.remove('show');
      document.getElementById('memory--end-game-modal').classList.remove('show');
      document.getElementById('memory--end-game-message').innerText = "";
      document.getElementById('memory--end-game-score').innerText = "";
      var summary = document.getElementById('memory--end-game-summary');
      if (summary) {
        summary.innerText = "";
      }
      renderPoints();
      matchedSet = {};
      // A fresh board: release any lock left by the previous round and make
      // its pending miss timeout bail instead of clearing faces here.
      turnId++;
      boardLocked = false;
      buildLayout($.cards, $.settings.rows, $.settings.columns, true);
      startTimer(budgetFor($.settings.rows, $.settings.columns));
    }

  };
  reset.addEventListener('click', handleSettingsSubmission);

  // Show the end-of-round modal. Points are written to the score line; the
  // shell HUD freezes its score when it sees this modal appear, so every
  // point must be settled BEFORE this is called (time bonus included).
  var showEndGame = function (message) {
    var pairs = Math.floor($.cards.length / 2);
    var matched = Math.floor($._matched / 2);

    document.getElementById('memory--end-game-message').textContent = message;
    document.getElementById('memory--end-game-score').textContent =
        'Points: ' + $.points;

    var summary = document.getElementById('memory--end-game-summary');
    if (summary) {
      summary.textContent =
          matched + '/' + pairs + ' pairs \u00b7 ' +
          $.attempts + ' attempts \u00b7 best streak ' + $.bestStreak;
    }

    renderPoints();
    document.getElementById('memory--end-game-modal').classList.toggle('show');
  };

  // Countdown reached zero: keep the points earned, end the round.
  var endOnTimeout = function () {
    if ($.isGameOver) {
      return;
    }
    stopTimer();
    $.timeUp();
    showEndGame('Time\u2019s up!');
  };

  // Build the node list of the board. Rebuilt on every layout, so it must be
  // asked for fresh instead of cached.
  var cardNodes = function () {
    return document.getElementById('memory--cards').childNodes;
  };

  // Paint one card to match the model. Never `toggle`: the model holds the
  // truth, and toggling a stale class is what hid a card mid-turn.
  var paintCard = function (index, isFaceUp) {
    var node = cardNodes()[index];
    if (node) {
      node.classList.toggle('clicked', !!isFaceUp);
    }
  };

  // Handle clicking on card
  var handleFlipCard = function (event) {

    event.preventDefault();

    if ($.isGameOver || boardLocked) {
      return;
    }

    var index = this.index;
    var status = $.play(index);

    if (status.code == 3) {
      // A missed pair: keep both faces up for the window even though the
      // model has already concealed them.
      paintCard(status.args[0], true);
      paintCard(status.args[1], true);
    }
    else {
      // First card of a turn, a match, the final pair, or a card that is
      // already up: the screen follows the model.
      paintCard(index, $.cards[index].isRevealed);
      if (status.args) {
        paintCard(status.args[0], $.cards[status.args[0]].isRevealed);
        paintCard(status.args[1], $.cards[status.args[1]].isRevealed);
      }
    }

    renderPoints();

    // Glass-pass motion: ring matched pairs in gold, shake a missed pair.
    // Purely visual — the flip contract above is untouched.
    if (status.code == 2 || status.code == 4) {
      var nodes = cardNodes();
      matchedSet[status.args[0]] = true;
      matchedSet[status.args[1]] = true;
      nodes[status.args[0]].classList.add('matched');
      nodes[status.args[1]].classList.add('matched');
      nodes[status.args[0]].classList.add('just-matched');
      nodes[status.args[1]].classList.add('just-matched');
    }

    if (status.code == 3 ) {
      var missNodes = cardNodes();
      missNodes[status.args[0]].classList.add('miss');
      missNodes[status.args[1]].classList.add('miss');

      var stamp = turnId;
      var pair = [status.args[0], status.args[1]];
      boardLocked = true;
      setTimeout(function () {
        if (stamp !== turnId) {
          // A new board was dealt while this pair was up. Those nodes are
          // gone, and the ones standing in their place are not ours.
          return;
        }
        boardLocked = false;
        var childNodes = cardNodes();
        pair.forEach(function (i) {
          if (!childNodes[i]) {
            return;
          }
          childNodes[i].classList.remove('miss');
          paintCard(i, $.cards[i].isRevealed);
        });
      }, nonMatchingCardTime);
    }
    else if (status.code == 4) {
      stopTimer();
      // Speed bonus: +15 per whole second left. Awarded before the modal
      // shows so the shell's final score includes it.
      var bonus = $.addTimeBonus(Math.floor(remainingMs / 1000));
      showEndGame('You found them all! (+' + bonus + ' time bonus)');
    }

  };

  // Build grid of cards. `fresh` = a brand-new board (deal-in stagger plays);
  // a resize re-layout rebuilds the same board and must not re-deal it.
  var buildLayout = function (cards, rows, columns, fresh) {
    if (!cards.length) {
      return;
    }

    var memoryCards = document.getElementById("memory--cards");
    var index = 0;

    var cardMaxWidth = document.getElementById('memory--app-container').offsetWidth / columns;
    var cardHeightForMaxWidth = cardMaxWidth * (3 / 4);

    var cardMaxHeight = document.getElementById('memory--app-container').offsetHeight / rows;
    var cardWidthForMaxHeight = cardMaxHeight * (4 / 3);

    // Clean up. Remove all child nodes and card clicking event listeners.
    while (memoryCards.firstChild) {
      memoryCards.firstChild.removeEventListener('click', handleFlipCard);
      memoryCards.removeChild(memoryCards.firstChild);
    }

    for (var i = 0; i < rows; i++) {
      for (var j = 0; j < columns; j++) {
        // Use cloneNode(true) otherwise only one node is appended
        memoryCards.appendChild(buildCardNode(index, cards[index],
          (100 / columns) + "%", (100 / rows) + "%", fresh));
        index++;
      }
    }

    // Resize cards to fit in viewport
    if (cardMaxHeight > cardHeightForMaxWidth) {
      // Update height
      memoryCards.style.height = (cardHeightForMaxWidth * rows) + "px";
      memoryCards.style.width = document.getElementById('memory--app-container').offsetWidth + "px";
      memoryCards.style.top = ((cardMaxHeight * rows - (cardHeightForMaxWidth * rows)) / 2) + "px";
    }
    else {
      // Update Width
      memoryCards.style.width = (cardWidthForMaxHeight * columns) + "px";
      memoryCards.style.height = document.getElementById('memory--app-container').offsetHeight + "px";
      memoryCards.style.top = 0;
    }

  };

  // Update on resize (re-lay-out, not a fresh deal)
  window.addEventListener('resize', function() {
    buildLayout($.cards, $.settings.rows, $.settings.columns, false);
  }, true);

  // Build single card
  var buildCardNode = function (index, card, width, height, fresh) {
    var flipContainer = document.createElement("li");
    var flipper = document.createElement("div");
    var front = document.createElement("a");
    var back = document.createElement("a");

    flipContainer.index = index;
    flipContainer.style.width = width;
    flipContainer.style.height = height;
    flipContainer.classList.add("flip-container");
    if (card.isRevealed) {
      flipContainer.classList.add("clicked");
    }
    // Glass pass: cards matched this round stay ringed after a re-layout
    // (the DOM classes die with the old nodes), while the deal-in stagger
    // only plays when a brand-new board is laid out.
    if (matchedSet[index]) {
      flipContainer.classList.add("matched");
    }
    if (fresh) {
      flipContainer.classList.add("deal-in");
      flipContainer.style.animationDelay = Math.min(index * 28, 560) + "ms";
    }

    flipper.classList.add("flipper");
    front.classList.add("front");
    front.setAttribute("href", "#");
    back.classList.add("back");
    back.classList.add("card-" + card.value);
    if (card.isMatchingCard) {
      back.classList.add("matching");
    }
    back.setAttribute("href", "#");

    flipper.appendChild(front);
    flipper.appendChild(back);
    flipContainer.appendChild(flipper);

    flipContainer.addEventListener('click', handleFlipCard);

    return flipContainer;
  };

})(MemoryGame);
