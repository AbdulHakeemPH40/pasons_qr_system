# Changes to vendored 2048 (MIT)

Upstream: github.com/gabrielecirulli/2048 (vendored 2026-10-10, licence in
`LICENSE.txt`).

1. `index.html`: removed `target-densitydpi=160dpi` from the viewport meta
   tag. The property is deprecated and makes Chrome log a console warning on
   every load; guest pages of the Pasons platform keep a clean console.
   Layout is unaffected (the game already ships its own mobile media query).

No JavaScript was modified.
