"""Games Hub — the game registry and the restaurant demo background packs.

This is the single source of truth for what games exist and what the demo
backgrounds look like. Templates read it; the browser receives it as JSON via
``json_script`` so gameplay tuning never has to be duplicated in two places.

Gameplay tuning (speeds, timings, scoring weights) lives in
``static/gameshub/js/config.js`` instead — that file is the one place that owns
external URLs and tunables.
"""

#: The three games on the hub. Order is the card order on /games/.
GAMES = [
    {
        "slug": "catch-the-burger",
        "title": "Catch the Burger",
        "short": "Hop, grab, survive.",
        "rule": "Tap to hop. Grab the burgers and dodge everything else.",
        "kind": "runner",
        "est": "1–2 min",
    },
    {
        "slug": "memory-match",
        "title": "Memory Match",
        "short": "Find every pair.",
        "rule": "Tap two tiles to turn them over. Match all six pairs before the clock runs out.",
        "kind": "pairs",
        "est": "1–2 min",
    },
    {
        "slug": "stack-the-burger",
        "title": "Stack the Burger",
        "short": "Build it tall.",
        "rule": "Tap to drop the moving layer. Line it up to keep the stack from shrinking.",
        "kind": "stack",
        "est": "1–3 min",
    },
]

#: Restaurant demo background packs. Same demo names as the rest of the
#: prototype — these are the four Pasons restaurant brands. Each pack is a set
#: of flat colours for the playfield: sky, far scenery, near scenery, ground
#: and one accent. All values sit inside the tokens.css palette family so a
#: game never looks foreign next to the Smart Page.
THEMES = [
    {
        "slug": "king-chef",
        "name": "King Chef Restaurant",
        "sky": "#EDF3E7",
        "far": "#A8B59B",
        "near": "#7FA06B",
        "ground": "#31452D",
        "accent": "#D5C98A",
    },
    {
        "slug": "paramount",
        "name": "Paramount Restaurant",
        "sky": "#F2F1E8",
        "far": "#B9BFA6",
        "near": "#9DB18C",
        "ground": "#3C4A38",
        "accent": "#D5C98A",
    },
    {
        "slug": "milan-veg",
        "name": "Milan Veg",
        "sky": "#EAF4E4",
        "far": "#B7CDA2",
        "near": "#79B36B",
        "ground": "#2F4A2C",
        "accent": "#E3D9A0",
    },
    {
        "slug": "donar-istanbul",
        "name": "Donar Istanbul",
        "sky": "#F6EFE2",
        "far": "#D8C79B",
        "near": "#C2A96B",
        "ground": "#4A3B2A",
        "accent": "#D5C98A",
    },
]

DEFAULT_THEME = "king-chef"

GAME_BY_SLUG = {g["slug"]: g for g in GAMES}
THEME_BY_SLUG = {t["slug"]: t for t in THEMES}


def get_game(slug):
    return GAME_BY_SLUG.get(slug)


def get_theme(slug):
    return THEME_BY_SLUG.get(slug) or THEME_BY_SLUG[DEFAULT_THEME]
