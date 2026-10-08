"""Inline SVG icon set for the customer-facing pages.

Replaces the old unicode glyphs (✆ ☎ ◉ ✉ ★ — which render as "emoji"
symbols on phones) with real, crisp SVG marks:

  - brand logos: Google G, Instagram, Facebook, TikTok, WhatsApp,
    YouTube, X — colored exactly like the reference design badges
  - UI glyphs: phone, pin, book, sparkle, gamepad, star, clock, mail,
    arrow, chevron, search — single-color (currentColor), stroke-based

Usage:
    {% load icon_tags %}
    {% icon "google" %}          -> self-contained colored badge SVG
    {% icon "phone" class="ico" %} -> glyph that inherits currentColor

Every SVG is 24x24 viewBox. Brand icons carry their own circle
background (they ARE the badge, like the reference cards); UI glyphs
are transparent and take the color of their container.
"""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# ---------------------------------------------------------------- UI glyphs
# stroke-based, inherit currentColor — sized/cropped by CSS.
_STROKE = (
    'fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"'
)

GLYPHS = {
    "phone": (
        f'<path {_STROKE} d="M6.6 3h2.3c.5 0 .94.34 1.05.83l.7 3.2c.1.45-.04.92-.37 1.24'
        f'L8.6 9.95a12.4 12.4 0 0 0 5.45 5.45l1.68-1.68c.32-.33.79-.47 1.24-.37l3.2.7'
        f'c.5.1.83.55.83 1.05v2.3c0 .6-.48 1.08-1.07 1.07C10.53 18.47 5.53 13.47 5.53 4.07'
        f' 5.53 3.48 6 3 6.6 3z"/>'
    ),
    "pin": (
        f'<path {_STROKE} d="M12 21.5s7-6.9 7-12.5a7 7 0 1 0-14 0c0 5.6 7 12.5 7 12.5z"/>'
        f'<circle {_STROKE} cx="12" cy="9" r="2.4"/>'
    ),
    "book": (
        f'<path {_STROKE} d="M5 4.5A1.5 1.5 0 0 1 6.5 3H18v15H6.5A1.5 1.5 0 0 0 5 19.5v-15z"/>'
        f'<path {_STROKE} d="M5 19.5A1.5 1.5 0 0 0 6.5 21H18"/>'
        f'<path {_STROKE} d="M8.5 7.5h6M8.5 10.5h6"/>'
    ),
    "sparkle": (
        '<path fill="currentColor" d="M11 2.6l1.75 4.75L17.5 9.1l-4.75 1.75L11 15.6 '
        '9.25 10.85 4.5 9.1l4.75-1.75L11 2.6zM17.7 14.6l.95 2.55 2.55.95-2.55.95-.95 2.55'
        '-.95-2.55-2.55-.95 2.55-.95.95-2.55zM18.2 2.4l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9'
        '-1.9-.7 1.9-.7.7-1.9z"/>'
    ),
    "gamepad": (
        f'<rect {_STROKE} x="2.5" y="7.5" width="19" height="10" rx="4.5"/>'
        f'<path {_STROKE} d="M8 10.5v4M6 12.5h4M15.2 11.2h.01M17.8 13.8h.01"/>'
    ),
    "star": (
        '<path fill="currentColor" d="M12 2.5l2.6 5.55 6.1.72-4.5 4.12 1.22 6.01L12 16.9 '
        '6.58 18.9 7.8 12.9 3.3 8.78l6.1-.72L12 2.5z"/>'
    ),
    "star-line": (
        f'<path {_STROKE} d="M12 3.2l2.45 5.2 5.7.67-4.22 3.86 1.15 5.62L12 15.85 '
        f'6.92 18.55 8.07 12.93 3.85 9.07l5.7-.67L12 3.2z"/>'
    ),
    "clock": (
        f'<circle {_STROKE} cx="12" cy="12" r="8.5"/><path {_STROKE} d="M12 7.5V12l3 2"/>'
    ),
    "mail": (
        f'<rect {_STROKE} x="3" y="5.5" width="18" height="13" rx="2.5"/>'
        f'<path {_STROKE} d="M4 7l8 5.5L20 7"/>'
    ),
    "arrow": (
        f'<path {_STROKE} d="M5 12h13M12.5 6.5L19 12l-6.5 5.5"/>'
    ),
    "chevron": (
        f'<path {_STROKE} d="M9.5 5.5l6.5 6.5-6.5 6.5"/>'
    ),
    "back": (
        f'<path {_STROKE} d="M14.5 5.5L8 12l6.5 6.5"/>'
    ),
    "search": (
        f'<circle {_STROKE} cx="11" cy="11" r="6.5"/><path {_STROKE} d="M15.8 15.8L21 21"/>'
    ),
    "directions": (
        f'<path {_STROKE} d="M12 2.8l9 3.6v5.2c0 5-3.8 8.8-9 10.6-5.2-1.8-9-5.6-9-10.6V6.4'
        f'l9-3.6z"/><path {_STROKE} d="M9 12.2l2 2 4-4"/>'
    ),
    "gift": (
        f'<rect {_STROKE} x="3.5" y="8" width="17" height="4.5" rx="1"/>'
        f'<path {_STROKE} d="M5 12.5V20h14v-7.5M12 8V20M12 8s-4.5.2-4.5-2.2C7.5 3.8 10 4 12 8z'
        f'M12 8s4.5.2 4.5-2.2C16.5 3.8 14 4 12 8z"/>'
    ),
    "plate": (
        f'<circle {_STROKE} cx="12" cy="12" r="8.5"/><circle {_STROKE} cx="12" cy="12" r="4.5"/>'
    ),
    "chat": (
        f'<path {_STROKE} d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v8a2.5 2.5 0 0 1'
        f'-1.5 2.3v2.7l-3.2-2.2H6.5A2.5 2.5 0 0 1 4 14.5v-8z"/>'
        f'<path {_STROKE} d="M8 10.5h8M8 13h5"/>'
    ),
    "link": (
        f'<path {_STROKE} d="M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1.2 1.2"/>'
        f'<path {_STROKE} d="M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1.2-1.2"/>'
    ),
}

# ------------------------------------------------------------- brand badges
# Self-contained colored badges (circle bg + white/colored glyph),
# matching the reference card badges 1:1. `%%` escapes for .format-less use.

BRANDS = {
    "google": (
        '<circle cx="12" cy="12" r="12" fill="#FFFFFF" stroke="#E8E2D6" stroke-width="1"/>'
        '<path fill="#4285F4" d="M20.66 12.23c0-.68-.06-1.34-.18-1.96H12v3.71h4.85a4.14 4.14 0 '
        '0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.69-3.88 2.69-6.73z"/>'
        '<path fill="#34A853" d="M12 21c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86'
        '-2.34 0-4.32-1.58-5.03-3.7H3.96v2.33A9 9 0 0 0 12 21z"/>'
        '<path fill="#FBBC05" d="M6.97 13.72a5.4 5.4 0 0 1 0-3.44V7.95H3.96a9 9 0 0 0 0 8.1l3.01-2.33z"/>'
        '<path fill="#EA4335" d="M12 6.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C16.46 3.88 14.43 3 12 3'
        'a9 9 0 0 0-8.04 4.95l3.01 2.33C7.68 8.16 9.66 6.58 12 6.58z"/>'
    ),
    "instagram": (
        '<defs><linearGradient id="ig-grad" x1="0" y1="1" x2="1" y2="0">'
        '<stop offset="0" stop-color="#FEDA75"/><stop offset=".3" stop-color="#FA7E1E"/>'
        '<stop offset=".58" stop-color="#D62976"/><stop offset=".8" stop-color="#962FBF"/>'
        '<stop offset="1" stop-color="#4F5BD5"/></linearGradient></defs>'
        '<circle cx="12" cy="12" r="12" fill="url(#ig-grad)"/>'
        '<rect x="5.6" y="5.6" width="12.8" height="12.8" rx="3.9" fill="none" stroke="#fff" stroke-width="1.7"/>'
        '<circle cx="12" cy="12" r="3.1" fill="none" stroke="#fff" stroke-width="1.7"/>'
        '<circle cx="16.9" cy="7.1" r="1.05" fill="#fff"/>'
    ),
    "facebook": (
        '<circle cx="12" cy="12" r="12" fill="#1877F2"/>'
        '<path fill="#fff" d="M15.5 12.55l.42-2.75h-2.64V8.03c0-.75.37-1.48 1.54-1.48h1.19V4.19'
        's-1.08-.18-2.11-.18c-2.15 0-3.55 1.3-3.55 3.67v2.12H7.5v2.75h2.75V21h2.86v-8.45h2.39z"/>'
    ),
    "tiktok": (
        '<circle cx="12" cy="12" r="12" fill="#111111"/>'
        '<path fill="#fff" d="M16.9 8.5a4.85 4.85 0 0 1-3.02-1.05v5.62a3.98 3.98 0 1 1-3.98-3.98'
        'c.17 0 .33.01.49.03v2.2a1.85 1.85 0 1 0 1.3 1.76V4.3h2.1a4.84 4.84 0 0 0 3.11 4.2z"/>'
    ),
    "whatsapp": (
        '<circle cx="12" cy="12" r="12" fill="#25D366"/>'
        '<path fill="#fff" d="M12 6.1A5.87 5.87 0 0 0 6.9 15.05L6 18.4l3.46-.9a5.87 5.87 0 1 0 2.54-11.4z'
        'm0 10.53a4.65 4.65 0 0 1-2.38-.65l-.17-.1-1.75.51.53-1.7-.12-.18a4.65 4.65 0 1 1 3.89 2.12z'
        'm2.55-3.47c-.14-.07-.83-.41-.96-.45-.13-.05-.22-.07-.32.07-.1.14-.36.45-.44.55'
        '-.08.09-.16.11-.3.04a3.77 3.77 0 0 1-1.11-.69 4.16 4.16 0 0 1-.77-.96c-.08-.14-.01-.21.06-.28'
        '.07-.07.14-.16.21-.25.07-.08.09-.14.14-.23.05-.1.02-.18-.01-.25-.03-.07-.32-.76-.44-1.04'
        '-.11-.27-.23-.23-.31-.23h-.28c-.09 0-.25.04-.38.18-.13.15-.51.5-.51 1.21s.53 1.4.6 1.5'
        'c.07.1 1.02 1.55 2.47 2.17.35.15.62.24.83.3.34.11.66.09.9.06.28-.04.84-.34.95-.67.12-.33.12-.61.09-.67'
        '-.04-.07-.14-.11-.28-.18z"/>'
    ),
    "youtube": (
        '<circle cx="12" cy="12" r="12" fill="#FF0000"/>'
        '<path fill="#fff" d="M17.2 9.3a1.5 1.5 0 0 0-1.05-1.06C15.23 8 12 8 12 8s-3.23 0-4.15.24'
        'A1.5 1.5 0 0 0 6.8 9.3 15.5 15.5 0 0 0 6.56 12c0 .92.08 1.83.24 2.7a1.5 1.5 0 0 0 1.05 1.06'
        'C8.77 16 12 16 12 16s3.23 0 4.15-.24a1.5 1.5 0 0 0 1.05-1.06c.16-.87.24-1.78.24-2.7'
        's-.08-1.83-.24-2.7z"/>'
        '<path fill="#FF0000" d="M10.6 14.2V9.8L14.4 12l-3.8 2.2z"/>'
    ),
    "x": (
        '<circle cx="12" cy="12" r="12" fill="#111111"/>'
        '<path fill="#fff" d="M17.6 7.2h-1.32l-2.87 3.28-2.3-3.28H8.3l3.78 5.4-3.98 4.9h1.32l3.07-3.51 '
        '2.46 3.51h2.82l-3.99-5.67L17.6 7.2zm-.98 8.44h-.73L8.7 7.78h.78l7.14 7.86z"/>'
    ),
    "linkedin": (
        '<circle cx="12" cy="12" r="12" fill="#0A66C2"/>'
        '<path fill="#fff" d="M8.8 9.6H6.5V18h2.3V9.6zM7.65 6a1.35 1.35 0 1 0 0 2.7 1.35 1.35 0 0 0 0-2.7z'
        'M18 13.1c0-2.4-1.28-3.52-2.99-3.52-1.38 0-2 .76-2.35 1.29V9.6h-2.3c.03.65 0 8.4 0 8.4h2.3'
        'v-4.7c0-.2.02-.41.08-.55.16-.41.53-.83 1.15-.83.81 0 1.14.62 1.14 1.52V18H18v-4.9z"/>'
    ),
    "telegram": (
        '<circle cx="12" cy="12" r="12" fill="#229ED9"/>'
        '<path fill="#fff" d="M6.4 11.8l9.5-3.67c.44-.16.83.11.69.77l-1.62 7.63c-.11.54-.44.67-.9.42'
        'l-2.48-1.83-1.2 1.15c-.13.13-.24.24-.5.24l.18-2.54 4.62-4.18c.2-.18-.05-.28-.31-.1'
        'l-5.71 3.6-2.46-.77c-.54-.17-.55-.54.11-.8z"/>'
    ),
    "snapchat": (
        '<circle cx="12" cy="12" r="12" fill="#FFFC00"/>'
        '<path fill="#111" d="M12 5.2c2.4 0 4 1.72 4 4.3 0 .8-.07 1.55-.03 2.1.3.14.7-.2 1.07-.06.27.1.3.42.15.6-.35.42-1.24.66-1.5.87-.1.72.9 2.06 2.4 2.5.28.08.32.3.12.46-.4.33-1.15.44-1.53.57-.12.24.03.45-.2.5-.4.08-1.1-.12-1.7.08-.5.16-.86.72-1.5.72s-1-.56-1.5-.72c-.6-.2-1.3 0-1.7-.08-.23-.05-.08-.26-.2-.5-.38-.13-1.13-.24-1.53-.57-.2-.16-.16-.38.12-.46 1.5-.44 2.5-1.78 2.4-2.5-.26-.21-1.15-.45-1.5-.87-.15-.18-.12-.5.15-.6.37-.14.77.2 1.07.06.04-.55-.03-1.3-.03-2.1 0-2.58 1.6-4.3 4-4.3z"/>'
    ),
}


@register.simple_tag
def icon(name, class_=""):
    """Render an inline SVG icon by name.

    Brand names return self-contained colored badges; other names return
    currentColor UI glyphs. Unknown names render nothing (never a broken
    emoji square in the customer's face).
    """
    key = (name or "").strip().lower()
    inner = BRANDS.get(key) or GLYPHS.get(key)
    if not inner:
        return mark_safe("")
    css = ("icon " + class_).strip()
    return mark_safe(f'<svg class="{css}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{inner}</svg>')


@register.simple_tag
def icon_badge(name, class_=""):
    """Badge variant: same SVG, wrapped sizing hint class for card badges."""
    return icon(name, ("badge-ico " + class_).strip())
