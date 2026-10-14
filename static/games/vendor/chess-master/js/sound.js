/**
 * Sound Manager - Generates chess sounds using Web Audio API
 */
export class SoundManager {
  constructor() {
    this.audioCtx = null;
    this.enabled = true;
  }

  /** Get or create audio context */
  getContext() {
    if (!this.audioCtx) {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return this.audioCtx;
  }

  /** Play a tone with envelope */
  playTone(frequency, duration, type = 'sine', volume = 0.3) {
    if (!this.enabled) return;

    try {
      const ctx = this.getContext();
      const oscillator = ctx.createOscillator();
      const gainNode = ctx.createGain();

      oscillator.connect(gainNode);
      gainNode.connect(ctx.destination);

      oscillator.type = type;
      oscillator.frequency.setValueAtTime(frequency, ctx.currentTime);

      gainNode.gain.setValueAtTime(volume, ctx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);

      oscillator.start(ctx.currentTime);
      oscillator.stop(ctx.currentTime + duration);
    } catch (e) {
      // Audio not available
    }
  }

  /** Play noise burst (for captures) */
  playNoise(duration, volume = 0.2) {
    if (!this.enabled) return;

    try {
      const ctx = this.getContext();
      const bufferSize = ctx.sampleRate * duration;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);

      for (let i = 0; i < bufferSize; i++) {
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / bufferSize, 3);
      }

      const source = ctx.createBufferSource();
      const gainNode = ctx.createGain();
      const filter = ctx.createBiquadFilter();

      source.buffer = buffer;
      filter.type = 'lowpass';
      filter.frequency.value = 800;

      source.connect(filter);
      filter.connect(gainNode);
      gainNode.connect(ctx.destination);

      gainNode.gain.setValueAtTime(volume, ctx.currentTime);

      source.start(ctx.currentTime);
    } catch (e) {
      // Audio not available
    }
  }

  /** Sound: piece move */
  playMove() {
    this.playTone(600, 0.08, 'sine', 0.2);
    setTimeout(() => this.playTone(800, 0.06, 'sine', 0.15), 30);
  }

  /** Sound: capture */
  playCapture() {
    this.playNoise(0.12, 0.3);
    this.playTone(300, 0.1, 'square', 0.1);
  }

  /** Sound: check */
  playCheck() {
    this.playTone(880, 0.15, 'sine', 0.25);
    setTimeout(() => this.playTone(1100, 0.15, 'sine', 0.2), 100);
  }

  /** Sound: castle */
  playCastle() {
    this.playTone(500, 0.08, 'sine', 0.2);
    setTimeout(() => this.playTone(600, 0.08, 'sine', 0.2), 80);
    setTimeout(() => this.playTone(700, 0.08, 'sine', 0.2), 160);
  }

  /** Sound: game start */
  playGameStart() {
    this.playTone(440, 0.1, 'sine', 0.2);
    setTimeout(() => this.playTone(550, 0.1, 'sine', 0.2), 100);
    setTimeout(() => this.playTone(660, 0.15, 'sine', 0.25), 200);
  }

  /** Sound: game end (win) */
  playGameEnd() {
    this.playTone(523, 0.15, 'sine', 0.2);
    setTimeout(() => this.playTone(659, 0.15, 'sine', 0.2), 150);
    setTimeout(() => this.playTone(784, 0.2, 'sine', 0.25), 300);
    setTimeout(() => this.playTone(1047, 0.3, 'sine', 0.3), 450);
  }

  /** Sound: illegal move */
  playIllegal() {
    this.playTone(200, 0.15, 'square', 0.15);
  }

  /** Sound: clock tick (low time) */
  playLowTime() {
    this.playTone(1000, 0.05, 'sine', 0.1);
  }

  /** Toggle sound on/off */
  toggle() {
    this.enabled = !this.enabled;
    return this.enabled;
  }
}
