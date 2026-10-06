/**
 * Hub screen entry point. Only job: the background pack picker.
 *
 * The chips work as links without this file (the server marks the active one).
 * This adds the live swap and remembers the choice for the game screens.
 */

import { applyTheme, resolveTheme, readDefaultThemeSlug } from "./theme.js";
import { setThemeSlug, getThemeSlug } from "./storage.js";

const group = document.querySelector(".gh-theme-row");
if (group) {
  const chips = Array.from(group.querySelectorAll("[data-theme]"));

  const mark = (slug) => {
    chips.forEach((chip) => {
      const on = chip.dataset.theme === slug;
      chip.classList.toggle("is-on", on);
      chip.setAttribute("aria-checked", on ? "true" : "false");
    });
  };

  // Restore the stored choice so the page matches what the games will use.
  const stored = getThemeSlug(readDefaultThemeSlug());
  const theme = resolveTheme(stored);
  if (theme) {
    applyTheme(theme);
    mark(theme.slug);
  }

  // One delegated listener for the whole row — the count never grows.
  group.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-theme]");
    if (!chip || !group.contains(chip)) return;

    const slug = chip.dataset.theme;
    setThemeSlug(slug);
    mark(slug);

    const next = resolveTheme(slug);
    if (next) applyTheme(next);
  });
}
