"""
Mobile performance and touch-response guard tests.

These lock the work described in MOBILE_TOUCH_OPTIMIZATION_PLAN.md. Every
assertion encodes a MEASURED regression risk, not a style preference:

  * The QR landing page shipped 2.12 MB. 1.98 MB of that (93%) was five
    1254x1254 icon PNGs rendered at 54x54 CSS px -- a 23x oversize, all
    above the fold, all downloaded immediately.

  * ``-webkit-tap-highlight-color: transparent`` was declared in exactly one
    place, inside ``.btn`` (app.css:245). ``.btn`` is a panel-only class that
    no guest page uses, so every tap target a customer actually touches
    (``.btn-action``, ``.contact-circle``, ``.promo-card``, ``.variant-row``,
    ``.game-card``, ``.menu-pdf``, ``.sheet-back``, ``.row-arrow``) still
    flashed the grey system watermark. This is the "button water mark" the
    client reported.

  * ``touch-action: manipulation`` was scoped to ``.btn`` for the same reason,
    leaving the 300ms double-tap-to-zoom delay on every guest page.

Image bytes are resolved on the FILESYSTEM, not over HTTP. media/ is only
routed when DEBUG is True (config/urls.py:97), so a test-client GET of
/media/... returns 404; a naive HTTP-based budget check would then measure
zero bytes and pass vacuously while the real page stayed 2 MB.
"""

import re
import urllib.parse
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from apps.core.media_optim import derivative_relpath, derivative_url
from apps.core.test_acceptance import AcceptanceFixtures

# Guest pages in scope for the mobile pass. Panel pages are desktop by design.
GUEST_PAGES = ("qr_landing", "qr_specials", "qr_menu", "qr_review_write")

# Budgets. The landing page measured 2040 KB of images before the optimisation
# pass and should land near 90 KB after it (six small icons + one brand logo).
# 250 KB leaves room for richer art while still failing loudly on a regression
# to full-size sources.
MAX_TOTAL_IMAGE_KB = 250
MAX_SINGLE_IMAGE_KB = 80

_IMG_SRC = re.compile(
    r"""(?:src|href)="(/(?:media|static)/[^"]+\.(?:png|jpe?g|webp|avif|gif))\"""",
    re.IGNORECASE,
)


def _resolve(url):
    """Map a served /media/ or /static/ URL to a path on disk (or None)."""
    clean = urllib.parse.unquote(url.split("?")[0])
    if clean.startswith(settings.MEDIA_URL):
        return Path(settings.MEDIA_ROOT) / clean[len(settings.MEDIA_URL):]
    if clean.startswith(settings.STATIC_URL):
        rel = clean[len(settings.STATIC_URL):]
        for directory in settings.STATICFILES_DIRS:
            candidate = Path(directory) / rel
            if candidate.exists():
                return candidate
        return Path(settings.STATIC_ROOT) / rel
    return None


_PICTURE = re.compile(r"<picture\b.*?</picture>", re.IGNORECASE | re.DOTALL)
_SOURCE_SRCSET = re.compile(r"""<source\b[^>]*\bsrcset="([^"]+)\"""", re.IGNORECASE)
_IMG_ONLY = re.compile(r"""<img\b[^>]*\bsrc="([^"]+)\"""", re.IGNORECASE)


def _chosen_image_urls(html):
    """The image URLs a WebP-capable browser would ACTUALLY download.

    A ``<picture>`` carries both a WebP ``<source srcset>`` and an ``<img src>``
    fallback, and the browser picks one. Counting both overstates the payload
    by every original; counting only ``<img src>`` ignores the optimisation
    completely and would report the pre-optimisation 2 MB forever.
    """
    chosen = []
    rest = html
    for block in _PICTURE.finditer(html):
        inner = block.group(0)
        sources = _SOURCE_SRCSET.findall(inner)
        if sources:
            # srcset is "url descriptor, url descriptor" - take the first URL.
            chosen.append(sources[0].split(",")[0].strip().split(" ")[0])
        else:
            imgs = _IMG_ONLY.findall(inner)
            if imgs:
                chosen.append(imgs[0])
        rest = rest.replace(inner, "", 1)
    chosen += _IMG_ONLY.findall(rest)
    return list(dict.fromkeys(chosen))


def _referenced_images(html):
    """Unique on-disk paths for every raster image the page would download."""
    found = []
    for url in _chosen_image_urls(html):
        path = _resolve(url)
        if path is not None:
            found.append((url, path))
    return found


def _css(*names):
    """Concatenate the shipped stylesheets, read from static/."""
    out = []
    for name in names:
        for directory in settings.STATICFILES_DIRS:
            path = Path(directory) / "css" / name
            if path.exists():
                out.append(path.read_text(encoding="utf-8"))
                break
    return "\n".join(out)


class GuestPageWeightTests(AcceptanceFixtures):
    """No guest page may ship unoptimised raster art."""

    def _page(self, url_name):
        """Return the rendered HTML, or None if the page redirects away.

        qr_menu 302-redirects to a genuine external menu URL when the brand
        sets one (apps/menu/views.py:128). A page that redirects ships no
        payload of its own, so there is nothing to weigh -- and following the
        redirect would make the test client fetch a foreign host and fail with
        a 400. Callers skip a None result.
        """
        response = self.client.get(reverse(url_name, args=["kcic-table-001"]))
        if response.status_code in (301, 302, 303, 307, 308):
            return None
        self.assertEqual(response.status_code, 200, f"{url_name} did not render")
        return response.content.decode("utf-8")

    def _pages(self):
        """(url_name, html) for every guest page that renders in-platform."""
        for url_name in GUEST_PAGES:
            html = self._page(url_name)
            if html is not None:
                yield url_name, html

    def test_landing_image_payload_under_budget(self):
        """The regression this whole pass exists for: 2040 KB -> under 250 KB."""
        images = _referenced_images(self._page("qr_landing"))
        self.assertTrue(images, "landing page referenced no images at all")
        total_kb = sum(p.stat().st_size for _, p in images if p.exists()) / 1024
        self.assertLess(
            total_kb,
            MAX_TOTAL_IMAGE_KB,
            f"landing page ships {total_kb:.0f} KB of images "
            f"(budget {MAX_TOTAL_IMAGE_KB} KB). Optimise the sources.",
        )

    def test_no_single_oversized_image(self):
        """One 441 KB icon is enough to ruin a page on its own."""
        checked = 0
        for url_name, html in self._pages():
            for url, path in _referenced_images(html):
                if not path.exists():
                    continue
                checked += 1
                size_kb = path.stat().st_size / 1024
                self.assertLess(
                    size_kb,
                    MAX_SINGLE_IMAGE_KB,
                    f"{url_name} ships {url} at {size_kb:.0f} KB "
                    f"(max {MAX_SINGLE_IMAGE_KB} KB).",
                )
        self.assertGreater(checked, 0, "no images were checked at all")

    def test_every_referenced_image_exists(self):
        """A missing derivative must 404 loudly here, not silently in prod."""
        for url_name, html in self._pages():
            for url, path in _referenced_images(html):
                self.assertTrue(path.exists(), f"{url_name} references missing {url}")

    def test_every_img_tag_carries_dimensions(self):
        """width/height (or a sized box) is what prevents layout shift on load."""
        html = self._page("qr_landing")
        tags = re.findall(r"<img\b[^>]*>", html, re.IGNORECASE)
        self.assertTrue(tags, "landing page rendered no <img> tags")
        for tag in tags:
            has_size = re.search(r"\bwidth=", tag) and re.search(r"\bheight=", tag)
            self.assertTrue(
                has_size,
                f"<img> without width/height causes CLS on mobile: {tag[:110]}",
            )


def _covers(selectors_text, element):
    """True if a selector list targets <element> as a whole element.

    Substring matching is not enough here: the letter "a" appears inside
    "btn-action", "transparent" and "manipulation", so a naive ``in`` check
    passes even when no global rule exists. Match the element as a whole
    selector token, or the universal selector.
    """
    if re.search(r"(^|[\s,>+~(])\*(?=$|[\s,.:#\[>+~)])", selectors_text):
        return True
    return re.search(
        rf"(^|[\s,>+~(]){re.escape(element)}(?=$|[\s,.:#\[>+~)])",
        selectors_text,
    ) is not None


def _rules_setting(css, declaration_pattern):
    """Yield the selector text of every rule whose body matches the pattern."""
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(declaration_pattern, block.group(2)):
            yield block.group(1)


class TouchResponseCssTests(AcceptanceFixtures):
    """The grey tap watermark and the 300ms tap delay are global concerns."""

    def test_tap_highlight_removed_globally(self):
        """Must cover every interactive element, not just the panel .btn."""
        css = _css("app.css", "theme-warm.css")
        selectors = " ".join(
            _rules_setting(css, r"-webkit-tap-highlight-color:\s*transparent")
        )
        self.assertTrue(
            selectors.strip(), "no -webkit-tap-highlight-color: transparent rule at all"
        )
        for required in ("a", "button"):
            self.assertTrue(
                _covers(selectors, required),
                f"no global -webkit-tap-highlight-color: transparent rule covers "
                f"<{required}>. Guest tap targets (.btn-action, .contact-circle, "
                ".promo-card, .variant-row, .game-card) will flash the grey "
                f"watermark. Selectors found: {selectors.strip()[:160]!r}",
            )

    def test_touch_action_manipulation_is_global(self):
        """Kills the 300ms double-tap-to-zoom delay on guest pages."""
        css = _css("app.css", "theme-warm.css")
        selectors = " ".join(_rules_setting(css, r"touch-action:\s*manipulation"))
        for required in ("a", "button"):
            self.assertTrue(
                _covers(selectors, required),
                f"touch-action: manipulation does not apply globally to "
                f"<{required}>; the 300ms tap delay survives on guest pages. "
                f"Selectors found: {selectors.strip()[:160]!r}",
            )

    def test_back_button_meets_minimum_hit_area(self):
        """Apple's minimum tap target is 44px.

        What matters is the TAPPABLE box, not the painted one. The approved
        artwork is a 40px frosted circle, so the fix extends the hit area with
        a transparent ``::before`` outset ring rather than enlarging the circle
        the client signed off on. This therefore measures
        ``declared size + 2 x outset`` and requires the total to reach 44px.

        Sizes are declared in more than one file (app.css sets
        ``.device-screen .sheet-back``, theme-warm.css re-skins the glass
        variant), so every rule naming .sheet-back is considered.
        """
        css = _css("app.css", "theme-warm.css")

        sizes = []
        for block in re.finditer(r"([^{}]*\.sheet-back[^{}]*)\{([^{}]*)\}", css):
            if "::before" in block.group(1):
                continue  # the hit-area ring, not the visual box
            sizes += [
                int(v)
                for v in re.findall(
                    r"(?:^|[\s;])(?:width|height|min-width|min-height):\s*(\d+)px",
                    block.group(2),
                )
            ]
        self.assertTrue(sizes, "no explicit size found on any .sheet-back rule")
        visual = max(sizes)

        # A negative inset on the ::before grows the tappable box by 2 x |inset|.
        outset = 0
        for block in re.finditer(r"([^{}]*\.sheet-back::before[^{}]*)\{([^{}]*)\}", css):
            for value in re.findall(r"(?:^|[\s;])inset:\s*(-?\d+)px", block.group(2)):
                outset = max(outset, -int(value))

        effective = visual + 2 * outset
        self.assertGreaterEqual(
            effective,
            44,
            f".sheet-back paints at {visual}px and its hit area extends only to "
            f"{effective}px, under the 44px minimum tap target. Extend the "
            "::before outset (do not enlarge the approved circle).",
        )


class HoverHygieneTests(AcceptanceFixtures):
    """:hover must not stick after a tap on a touch device."""

    def test_no_unguarded_hover_on_guest_components(self):
        """Every decorative :hover rule sits inside @media (hover: hover)."""
        css = _css("app.css", "theme-warm.css")
        unguarded = _strip_conditional_blocks(css)
        offenders = [
            sel.strip()
            for sel in re.findall(r"([^{};]+):hover[^{}]*\{", unguarded)
        ]
        self.assertEqual(
            offenders,
            [],
            "these :hover rules are not wrapped in @media (hover: hover) and "
            f"will stick after a tap on touch: {offenders}",
        )


def _strip_conditional_blocks(css):
    """Drop @media blocks that legitimately contain :hover.

    Two kinds are legitimate and must not be reported:
      * ``@media (hover: hover)`` -- the correct guard, hover only applies
        where a real pointing device hovers;
      * ``@media (prefers-reduced-motion)`` / ``(prefers-reduced-transparency)``
        -- these NEUTRALISE hover (``transform: none``), which is the desired
        accessible behaviour, not a decoration that can stick.
    """
    keep = re.compile(
        r"@media[^{]*(?:hover:\s*hover|prefers-reduced-motion|prefers-reduced-transparency)[^{]*\{",
        re.IGNORECASE,
    )
    out = []
    i = 0
    while i < len(css):
        match = keep.search(css, i)
        if not match:
            out.append(css[i:])
            break
        out.append(css[i:match.start()])
        depth = 1
        j = match.end()
        while j < len(css) and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        i = j
    return "".join(out)


class MediaOptimTests(SimpleTestCase):
    """Unit guards on the derivative pipeline itself.

    These two defects were both invisible in the rendered page and would have
    shipped silently:

      * derivatives for different icons in the same folder collapsed onto ONE
        filename (``deriv/icons/icons.w162.webp``), so every icon would have
        displayed the same artwork;
      * derivative URLs were not percent-encoded. In a ``srcset`` attribute a
        space separates the URL from its descriptor, so
        ``/media/deriv/icons/Green Circle Phone Icon.w162.webp`` parses as the
        URL ``/media/deriv/icons/Green`` -- the browser fails the source and
        quietly falls back to the 430 KB original, defeating the optimisation
        for all six icons (every one has a space in its name).
    """

    def test_derivatives_in_one_folder_do_not_collide(self):
        paths = {
            derivative_relpath(name, 162)
            for name in (
                "icons/Green Circle Phone Icon.png",
                "icons/Pale Mint WhatsApp Icon.png",
                "icons/Instagram Gradient Badge.png",
                "icons/Google Review Star Badge.png",
                "icons/Minimal Sage Circle Open Book Icon.png",
                "icons/Golden Gamepad Emblem.png",
            )
        }
        self.assertEqual(len(paths), 6, f"derivative names collided: {sorted(paths)}")

    def test_derivative_keeps_source_directory_and_name(self):
        self.assertEqual(
            derivative_relpath("icons/Green Circle Phone Icon.png", 162),
            "deriv/icons/Green Circle Phone Icon.w162.webp",
        )
        self.assertEqual(
            derivative_relpath("logo/kingchef.png", 288),
            "deriv/logo/kingchef.w288.webp",
        )

    def test_derivative_url_is_percent_encoded(self):
        """No raw spaces may reach a srcset attribute.

        ``ensure_derivative`` is patched so the test asserts the URL contract
        without encoding an image or writing into the real media/ tree.
        """
        with mock.patch(
            "apps.core.media_optim.ensure_derivative",
            return_value="deriv/icons/Green Circle Phone Icon.w162.webp",
        ):
            url = derivative_url("icons/Green Circle Phone Icon.png", 162)
        self.assertIsNotNone(url)
        self.assertNotIn(" ", url, f"unencoded space in derivative URL: {url!r}")
        self.assertIn("%20", url)
        self.assertTrue(url.endswith(".webp"), url)

    def test_unsupported_and_missing_sources_fail_open(self):
        """A derivative failure must never break a guest page."""
        self.assertIsNone(derivative_url("icons/does-not-exist.png", 162))
        self.assertIsNone(derivative_url("menu/booklet/page.pdf", 640))
        self.assertIsNone(derivative_url(None, 162))
        self.assertIsNone(derivative_url("", 162))
