/**
 * Author: Maximo Mena
 * GitHub: mmenavas
 * Twitter: @menamaximo
 * Project: Memory Workout
 * Description: This is a memory game written in pure JavaScript.
 * The goal is to match pairs of cards in the least
 * number of matching attempts.
 */

/**
 * @TODO
 * - Implement support for multiple players.
 */

/**
 * @namespace The main application object
 */
var MemoryGame = {

  settings: {
    rows: 2,
    columns: 3,
    images: 3, // Number of images
  },

  // Properties that indicate state
  cards: [], // Array of MemoryGame.Card objects
  attempts: 0, // How many pairs of cards were flipped before completing game
  mistakes: 0, // How many pairs of cards were flipped before completing game
  isGameOver: false,

  // Scoring state (Pasons extension, see CHANGES.md).
  // Points: +100 per matched pair, plus a streak bonus of +25 for every
  // consecutive match after the first (capped at +100). A mismatch costs
  // -25 points (never below 0) and breaks the streak. A round finished
  // before the clock runs out adds +15 per whole second left.
  points: 0,
  streak: 0,
  bestStreak: 0,

  POINTS_MATCH: 100,
  POINTS_STREAK_STEP: 25,
  POINTS_STREAK_CAP: 100,
  POINTS_MISMATCH: 25,
  POINTS_PER_SECOND_LEFT: 15,

  // Round-local flip state (Pasons extension). Lives on the model instead of
  // a play() closure so initialize() can reset it; see resetPlayState().
  _selection: [], // indices flipped but not yet resolved this turn
  _matched: 0, // cards matched so far (2 per pair)
  _seenValues: [], // values already seen in a resolved mismatch
  _timedOut: false, // round ended because the countdown hit zero
  _bonusAwarded: false, // win time bonus already paid this round

  /**
   * Modify default settings to start a new game.
   * Both parameters need integers greater than one, and
   * at least one them  needs to be an even number.
   *
   * @param {number} columns
   * @param {number} rows
   * @param {number} number of card images
   * @return {array} shuffled cards
   */
  initialize : function(rows, columns, images) {
    var validOptions = true;

    // Validate arguments
    if (!(typeof columns === 'number' && (columns % 1) === 0 && columns > 1) ||
        !(typeof rows === 'number' && (rows % 1) === 0) && rows > 1) {
      validOptions = false;
      throw {
        name: "invalidInteger",
        message: "Both rows and columns need to be integers greater than 1."
      };
    }

    if ((columns * rows) % 2 !== 0) {
      validOptions = false;
      throw {
        name: "oddNumber",
        message: "Either rows or columns needs to be an even number."
      };
    }

    if (validOptions) {
      this.settings.rows = rows;
      this.settings.columns = columns;
      this.settings.images = images;
      this.attempts = 0;
      this.mistakes = 0;
      this.isGameOver = false;
      this.points = 0;
      this.streak = 0;
      this.bestStreak = 0;
      this.resetRoundState();
      this.createCards().shuffleCards();
    }

    return this.cards;
  },

  /**
   * Clear the flip state that tracks a single turn's pair selection and the
   * values already seen. Must run on every initialize(): kept in a play()
   * closure upstream, it survived "Start New Game" and could end a fresh
   * round early (matched count from the old board) or count phantom
   * mistakes. Pasons fix, see CHANGES.md.
   *
   * @return Reference to self object
   */
  resetRoundState: function() {
    this._selection = [];
    this._matched = 0;
    this._seenValues = [];
    this._timedOut = false;
    this._bonusAwarded = false;
    return this;
  },

  /**
   * Award the time bonus when the board is cleared before the clock runs
   * out: +15 points per whole second left (Pasons extension). Only the win
   * path earns it: a timed-out round gets nothing, and it is paid once.
   *
   * @param {number} seconds Whole seconds remaining
   * @return {number} Points awarded
   */
  addTimeBonus: function(seconds) {
    var bonus = 0;
    if (!this._timedOut && !this._bonusAwarded) {
      this._bonusAwarded = true;
      bonus = this.POINTS_PER_SECOND_LEFT * Math.max(0, Math.floor(seconds));
      this.points += bonus;
    }
    return bonus;
  },

  /**
   * End the round because the countdown reached zero. Points earned so far
   * are kept (Pasons extension).
   *
   * @return {number} Final points
   */
  timeUp: function() {
    this.isGameOver = true;
    this._timedOut = true;
    this._selection = [];
    return this.points;
  },

  /**
   * Create an array of sorted cards
   *
   * @return Reference to self object
   */
  createCards: function() {
    var cards = [];
    var values = [];
    var count = 0;
    var maxValue = (this.settings.columns * this.settings.rows) / 2;
    while (count < maxValue) {
      // Next random card value
      var value = this.getRandomCardValue(values);
      // Card A
      cards[2 * count] = new this.Card(value);
      // Card B (matching card)
      cards[2 * count + 1] = new this.Card(value, true);
      count++;
    }

    this.cards = cards;

    return this;
  },

  /**
   * Get a random value between 1 and this.settings.images that is not
   * already in 'values'.
   *
   * @param {array} values List of random values already in use.
   * @return {number}
   */
  getRandomCardValue: function(values) {
    var valid = false;
    var randomValue = 0;

    while (!valid) {
      randomValue = Math.floor(Math.random() * this.settings.images) + 1;
      var found = false;
      for (var index = 0; index < values.length; index++) {
        if (randomValue === values[index]) {
          found = true;
          break;
        }
      }
      if (!found) {
        valid = true;
        values.push(randomValue); // Purposely modify the array parameter.
      }
    }

    return randomValue;
  },

  /**
   * Rearrange elements in cards array
   *
   * @return Reference to self object
   */
  shuffleCards: function() {
    var cards = this.cards;
    var shuffledCards = [];
    var randomIndex = 0;

    // Shuffle cards
    while (shuffledCards.length < cards.length) {

      // Random value between 0 and cards.length
      randomIndex  = Math.floor(Math.random() * cards.length);

      // If element isn't false, add element to shuffled deck
      if(cards[randomIndex]) {

        // Add new element to shuffle deck
        shuffledCards.push(cards[randomIndex]);

        // Set element to false to avoid being reused
        cards[randomIndex] = false;
      }

    }

    this.cards = shuffledCards;

    return this;
  },

  /**
   * A player gets to flip two cards. This function returns information
   * about what happens when a card is selected. Scoring (Pasons
   * extension): +POINTS_MATCH per pair, plus a streak bonus of
   * +POINTS_STREAK_STEP for each consecutive match after the first, capped
   * at +POINTS_STREAK_CAP; a mismatch costs -POINTS_MISMATCH (never below
   * 0) and resets the streak.
   *
   * @param {number} Index of card selected by player
   * @return {object} {code: number, message: string, args: array or number}
   */
  play: function(index) {
    var status = {};
    var cardSelection = this._selection;

    if (!this.cards[index].isRevealed) {
      this.cards[index].reveal();
      cardSelection.push(index);
      if (cardSelection.length == 2) {
        this.attempts++;
        if (this.cards[cardSelection[0]].value !=
            this.cards[cardSelection[1]].value) {
          // No match
          this.cards[cardSelection[0]].conceal();
          this.cards[cardSelection[1]].conceal();
          /**
           * Algorithm to determine a mistake.
           * Check if the pair of at least
           * one card has been revealed before
           *
           * indexOf return -1 if value is not found
           */
          var isMistake = false;

          if (this._seenValues.indexOf(this.cards[cardSelection[0]].value) === -1) {
            this._seenValues.push(this.cards[cardSelection[0]].value);
          }
          else {
            isMistake = true;
          }

          if (this._seenValues.indexOf(this.cards[cardSelection[1]].value) === -1) {
            this._seenValues.push(this.cards[cardSelection[1]].value);
          }

          if (isMistake) {
            this.mistakes++;
          }

          this._seenValues.push(this.cards[cardSelection[0]].value);

          // Scoring: penalty and streak reset on a miss
          this.points = Math.max(0, this.points - this.POINTS_MISMATCH);
          this.streak = 0;

          status.code = 3,
          status.message = 'No Match. Conceal cards.';
          status.args = cardSelection;
        }
        else {
          this._matched += 2;
          // Pasons glass pass: report which pair matched so the interface
          // can ring it in gold (same args contract as the no-match path).
          status.args = cardSelection;
          // Scoring: base points plus a growing streak bonus
          this.streak++;
          if (this.streak > this.bestStreak) {
            this.bestStreak = this.streak;
          }
          this.points += this.POINTS_MATCH +
              Math.min(this.POINTS_STREAK_STEP * (this.streak - 1),
                  this.POINTS_STREAK_CAP);
          if (this._matched == this.cards.length) {
            // Game over
            this.isGameOver = true;
            status.code = 4,
            status.message = 'GAME OVER! Attempts: ' + this.attempts +
                ', Mistakes: ' + this.mistakes;
          }
          else {
            status.code = 2,
            status.message = 'Match.';
          }
        }
        this._selection = [];
      }
      else {
        status.code = 1,
        status.message = 'Flip first card.';
      }
    }
    else {
      status.code = 0,
      status.message = 'Card is already facing up.';
    }

    return status;

  }

};
