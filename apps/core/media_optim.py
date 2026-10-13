"""
On-demand image derivatives for the guest-facing pages.

Why this exists
---------------
The QR landing page shipped 2.12 MB, and 1.98 MB of that (93%) was five
1254x1254 icon PNGs rendered at 54x54 CSS pixels -- a 23x oversize, all above
the fold, all downloaded before the page looked finished. On a phone over 4G
that is the difference between instant and several seconds.

This module generates right-sized WebP derivatives and leaves every original
untouched. Templates opt in with ``{% deriv_url %}`` inside a ``<picture>``,
so the existing ``<img>`` stays as the fallback and nothing about the approved
art direction changes -- the same artwork, just served at the size it is
actually displayed.

Design rules
------------
* **Never mutate or delete a source file.** All output goes to a separate
  ``media/deriv/`` tree.
* **Never upscale.** If the source is narrower than the requested width the
  source width is used, so a small logo is not blown up into a larger, softer
  file.
* **Fail open.** If Pillow cannot read a file, or the source is an SVG or a
  PDF, the caller gets ``None`` and the template falls back to the original
  URL. A broken derivative must never break a guest page.
* **Idempotent and cheap to re-run.** A derivative is regenerated only when it
  is missing or older than its source, so this is safe on every deploy and
  fast enough to call from a ``post_save`` signal.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Derivatives live in their own tree under MEDIA_ROOT. They must be under
# MEDIA_ROOT rather than STATIC_ROOT because uploads generate derivatives at
# runtime, and the static tree is collected/read-only in deployment.
DERIV_DIRNAME = "deriv"

# Widths actually used by the guest templates, at 3x the CSS size so a
# derivative stays crisp on any phone retina screen:
#   162  = 54px icons and contact circles
#   288  = 96px avatars / brand logos
#   640  = menu and promo card art
#   1080 = full-bleed heroes
WIDTHS = (162, 288, 640, 1080)

# Raster formats worth re-encoding. SVG is already vector and tiny; PDF is not
# an image; GIF may be animated, which a single-frame WebP would break.
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

# Icons are flat-colour art with hard edges: lossless WebP is both smaller and
# crisper than lossy at these sizes. Photos want lossy.
ICON_WIDTH_THRESHOLD = 288
LOSSY_QUALITY = 82


def _media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def deriv_root() -> Path:
    return _media_root() / DERIV_DIRNAME


def source_relpath(source) -> str | None:
    """Normalise a FieldFile, absolute path, or media-relative path to a
    slash-separated path relative to MEDIA_ROOT.

    Returns None when the value cannot be resolved inside MEDIA_ROOT, which is
    how a missing or external file fails open.
    """
    if source is None:
        return None

    # FieldFile / ImageFieldFile: .name is already media-relative.
    name = getattr(source, "name", None)
    if name:
        return name.replace(os.sep, "/")

    text = str(source).strip()
    if not text:
        return None

    # A served URL: strip the media prefix.
    media_url = settings.MEDIA_URL
    if text.startswith(media_url):
        from urllib.parse import unquote

        return unquote(text[len(media_url):]).replace(os.sep, "/")

    path = Path(text)
    if path.is_absolute():
        try:
            return path.relative_to(_media_root()).as_posix()
        except ValueError:
            return None

    return path.as_posix()


def derivative_relpath(rel: str, width: int) -> str:
    """media-relative path of the derivative for ``rel`` at ``width``.

    Mirrors the source's directory layout and keeps the source's own filename,
    so ``icons/Green Circle Phone Icon.png`` becomes
    ``deriv/icons/Green Circle Phone Icon.w162.webp``. Two icons in the same
    folder must never collapse onto one derivative.
    """
    clean = rel.replace(os.sep, "/").lstrip("/")
    # rpartition gives (before, separator, after): `after` is the FILENAME.
    parent, _, filename = clean.rpartition("/")
    name, _ext = os.path.splitext(filename)
    if not name:
        return ""
    prefix = f"{parent}/" if parent else ""
    return f"{DERIV_DIRNAME}/{prefix}{name}.w{width}.webp"


def _has_alpha(im) -> bool:
    """True when the image carries a channel that must survive the encode.

    Mode "P" only counts when it actually declares transparency: the six
    landing icons are palette PNGs with a baked-in white background, and
    converting those to RGBA would add an alpha channel they do not need and
    make the file larger for no visual gain.
    """
    if "A" in im.mode:  # RGBA, LA, PA
        return True
    if im.mode == "P":
        return "transparency" in im.info
    return False


def _is_stale(target: Path, source: Path) -> bool:
    return not target.exists() or target.stat().st_mtime < source.stat().st_mtime


def ensure_derivative(source, width: int, force: bool = False) -> str | None:
    """Generate (if needed) the WebP derivative and return its media-relative
    path, or None when no derivative could be produced.

    Safe to call on every request: an up-to-date derivative costs one stat().
    """
    rel = source_relpath(source)
    if not rel:
        return None
    if Path(rel).suffix.lower() not in SUPPORTED_SUFFIXES:
        return None

    src = _media_root() / rel
    if not src.exists():
        return None

    target_rel = derivative_relpath(rel, width)
    if not target_rel:
        return None
    target = _media_root() / target_rel
    if not force and not _is_stale(target, src):
        return target_rel

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a project dependency
        logger.warning("Pillow unavailable; serving original for %s", rel)
        return None

    try:
        with Image.open(src) as im:
            # Normalise the mode before encoding, preserving alpha exactly when
            # the source has it. Flattening an RGBA logo onto RGB would turn
            # its transparent background into a solid white box.
            if _has_alpha(im):
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
            elif im.mode not in ("RGB", "L"):
                im = im.convert("RGB")

            src_width, src_height = im.size
            # Never upscale: a 200px logo asked for at 640 stays 200px.
            target_width = min(width, src_width)
            if target_width <= 0:
                return None
            if target_width < src_width:
                ratio = target_width / src_width
                im = im.resize(
                    (target_width, max(1, round(src_height * ratio))),
                    Image.LANCZOS,
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp name then rename, so a concurrent request never
            # reads a half-written file.
            tmp = target.with_suffix(".part")
            if target_width <= ICON_WIDTH_THRESHOLD:
                im.save(tmp, "WEBP", lossless=True, quality=100, method=6)
            else:
                im.save(tmp, "WEBP", quality=LOSSY_QUALITY, method=6)
            os.replace(tmp, target)
    except Exception as exc:  # never break a guest page over an optimisation
        logger.warning("derivative failed for %s @%s: %s", rel, width, exc)
        try:
            target.with_suffix(".part").unlink(missing_ok=True)
        except OSError:
            pass
        return None

    return target_rel


def derivative_url(source, width: int) -> str | None:
    """Public URL for the derivative, or None if it could not be produced.

    The path MUST be percent-encoded. Several source images have spaces in
    their filenames ("Green Circle Phone Icon.png"), and in a ``srcset``
    attribute a space is the separator between the URL and its descriptor --
    an unencoded space makes the browser parse the URL as
    ``/media/deriv/icons/Green``, fail, and silently fall back to the
    heavyweight original. ``quote`` leaves ``/`` intact.
    """
    rel = ensure_derivative(source, width)
    if not rel:
        return None
    from urllib.parse import quote

    return f"{settings.MEDIA_URL}{quote(rel)}"


def original_url(source) -> str | None:
    """The plain served URL for a source, for the <img> fallback."""
    url = getattr(source, "url", None)
    if url:
        return url
    rel = source_relpath(source)
    if not rel:
        return None
    from urllib.parse import quote

    return f"{settings.MEDIA_URL}{quote(rel)}"


def iter_media_images():
    """Yield media-relative paths of every raster image under MEDIA_ROOT,
    skipping the derivative tree itself."""
    root = _media_root()
    if not root.exists():
        return
    prefix = f"{DERIV_DIRNAME}/"
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(prefix):
            continue
        yield rel
