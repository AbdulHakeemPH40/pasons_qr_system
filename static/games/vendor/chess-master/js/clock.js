/**
 * Chess Clock - Handles time controls with increment
 */
export class ChessClock {
  constructor() {
    this.whiteTime = 600; // seconds
    this.blackTime = 600;
    this.increment = 0;
    this.activeColor = null;
    this.running = false;
    this.lastTick = null;
    this.intervalId = null;
    this.onFlag = null; // callback when time runs out
    this.onTick = null; // callback every tick
  }

  /** Set time control */
  setTimeControl(seconds, increment = 0) {
    this.whiteTime = seconds;
    this.blackTime = seconds;
    this.increment = increment;
  }

  /** Start the clock for a specific color */
  start(color) {
    this.activeColor = color;
    this.running = true;
    this.lastTick = Date.now();

    if (this.intervalId) clearInterval(this.intervalId);
    this.intervalId = setInterval(() => this.tick(), 100);
  }

  /** Stop the clock */
  stop() {
    this.running = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  /** Switch clock to the other player (called after a move) */
  switchClock() {
    if (!this.running) return;

    // Add increment to the player who just moved
    if (this.activeColor === 'w') {
      this.whiteTime += this.increment;
      this.activeColor = 'b';
    } else {
      this.blackTime += this.increment;
      this.activeColor = 'w';
    }

    this.lastTick = Date.now();
  }

  /** Internal tick - update time */
  tick() {
    if (!this.running || !this.activeColor) return;

    const now = Date.now();
    const elapsed = (now - this.lastTick) / 1000;
    this.lastTick = now;

    if (this.activeColor === 'w') {
      this.whiteTime -= elapsed;
      if (this.whiteTime <= 0) {
        this.whiteTime = 0;
        this.stop();
        if (this.onFlag) this.onFlag('w');
      }
    } else {
      this.blackTime -= elapsed;
      if (this.blackTime <= 0) {
        this.blackTime = 0;
        this.stop();
        if (this.onFlag) this.onFlag('b');
      }
    }

    if (this.onTick) this.onTick();
  }

  /** Get formatted time string */
  formatTime(seconds) {
    if (seconds <= 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const tenths = Math.floor((seconds % 1) * 10);

    if (seconds < 10) {
      return `${mins}:${secs.toString().padStart(2, '0')}.${tenths}`;
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  /** Get display time for a color */
  getDisplayTime(color) {
    const time = color === 'w' ? this.whiteTime : this.blackTime;
    return this.formatTime(time);
  }

  /** Check if time is low (< 30 seconds) */
  isLowTime(color) {
    const time = color === 'w' ? this.whiteTime : this.blackTime;
    return time < 30;
  }

  /** Reset clocks */
  reset() {
    this.stop();
    this.activeColor = null;
  }
}
