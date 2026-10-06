"""Template tags for the social modules of the Smart Page.

Brand dot colors and monograms are taken verbatim from the prototype
frame 02 (module_social_links): WA #25D366 · FB #1877F2 · YT #FF0000 ·
TT #111111 · X #000000 · IN #0A66C2. Instagram is rendered separately
as its gradient tile (module_instagram).
"""

from django import template

register = template.Library()

SOCIAL_META = {
    "whatsapp": ("WA", "#25D366", "WhatsApp"),
    "facebook": ("FB", "#1877F2", "Facebook"),
    "youtube": ("YT", "#FF0000", "YouTube"),
    "tiktok": ("TT", "#111111", "TikTok"),
    "x": ("X", "#000000", "X"),
    "twitter": ("X", "#000000", "X"),
    "instagram": ("IN", "#0A66C2", "Instagram"),
    "linkedin": ("LI", "#0A66C2", "LinkedIn"),
    "telegram": ("TG", "#229ED9", "Telegram"),
    "snapchat": ("SC", "#F5C400", "Snapchat"),
}

# Frame 02 circle order (module_social_links): WA · FB · YT · TT · X · IN
CIRCLE_ORDER = [
    "whatsapp", "facebook", "youtube", "tiktok", "x", "twitter",
    "instagram", "linkedin", "telegram", "snapchat",
]


@register.simple_tag
def social_meta(name):
    """Return {mono, color, label} for a social network key."""
    key = (name or "").strip().lower()
    mono, color, label = SOCIAL_META.get(
        key, (key[:2].upper() or "··", "#7FA06B", (name or "").title())
    )
    return {"mono": mono, "color": color, "label": label}


@register.filter
def ig_handle(url):
    """'https://instagram.com/kingchefuae' -> 'kingchefuae' (display handle)."""
    if not url:
        return ""
    handle = str(url).rstrip("/").split("/")[-1]
    if handle.lower() in ("instagram.com", "www.instagram.com", "instagram"):
        return ""
    return handle


@register.filter
def circle_links(social, whatsapp_url=""):
    """Ordered social dots for module_social_links (frame 02: WA FB YT TT X IN).

    WhatsApp comes from the click-to-chat number, Instagram is included as its
    IN dot, and non-URL values (e.g. instagram_followers) never render.
    """
    merged = dict(social or {})
    if whatsapp_url:
        merged.setdefault("whatsapp", whatsapp_url)

    out, seen = [], set()
    for key in CIRCLE_ORDER + [k for k in merged if k not in CIRCLE_ORDER]:
        url = merged.get(key)
        if not url or not str(url).startswith("http"):
            continue
        mono, color, label = SOCIAL_META.get(
            key, (key[:2].upper() or "··", "#7FA06B", key.replace("_", " ").title())
        )
        if mono in seen:  # e.g. 'x' and 'twitter' both map to X
            continue
        seen.add(mono)
        out.append({"mono": mono, "color": color, "label": label, "url": url})
    return out
