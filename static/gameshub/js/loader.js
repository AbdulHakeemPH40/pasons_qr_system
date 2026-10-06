/**
 * Engine loading.
 *
 * Tries the pinned CDN first and falls back to the same-version local mirror, so
 * the games still run on a flaky connection or an offline demo. Both URLs come
 * from config.js — nothing else in the hub knows where the engine lives.
 */

import { ENGINE } from "./config.js";

let inflight = null;

function tryScript(src, timeoutMs = 9000) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    let settled = false;

    const done = (ok) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (!ok) script.remove();
      ok ? resolve() : reject(new Error("failed to load " + src));
    };

    const timer = setTimeout(() => done(false), timeoutMs);
    script.src = src;
    script.async = true;
    script.onload = () => done(true);
    script.onerror = () => done(false);
    document.head.appendChild(script);
  });
}

/**
 * Load the engine once per page.
 * @returns {Promise<object>} the global Phaser namespace
 */
export function loadPhaser({ cdn = ENGINE.cdn, local = ENGINE.local } = {}) {
  if (window.Phaser) return Promise.resolve(window.Phaser);
  if (inflight) return inflight;

  inflight = tryScript(cdn)
    .catch(() => tryScript(local))
    .then(() => {
      if (!window.Phaser) throw new Error("engine loaded but Phaser is missing");
      return window.Phaser;
    })
    .finally(() => {
      inflight = null;
    });

  return inflight;
}
