"""
Pre-generate optimised WebP derivatives for every image under media/.

Why a command and not only on-demand generation
-----------------------------------------------
``media_optim.ensure_derivative`` already generates a derivative the first
time a template asks for one, so nothing breaks if this command is never run.
But that means the first guest to load a page pays the encode cost, and on a
cold deploy every page pays it at once. Running this at deploy time moves that
work off the request path entirely.

It is also the only way to optimise the six hardcoded ``media/icons/*.png``
badges, which are referenced by literal path in the templates rather than
through an ImageField, so no signal ever fires for them.

Idempotent and safe:
  - originals are only ever READ. All output goes to ``media/deriv/``.
  - a derivative newer than its source is skipped, so re-running is cheap.
  - ``--dry-run`` reports what would happen and writes nothing.

  python manage.py optimize_media --dry-run
  python manage.py optimize_media
  python manage.py optimize_media --widths 162,288 --force
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.media_optim import (
    DERIV_DIRNAME,
    SUPPORTED_SUFFIXES,
    WIDTHS,
    ensure_derivative,
    iter_media_images,
)


def _pixel_width(path: Path) -> int:
    """Width in pixels, or 0 when it cannot be read.

    Reads only the header, so this is cheap enough to call per image. A 0 means
    "unknown" and the caller falls back to generating every requested width.
    """
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.size[0])
    except Exception:
        return 0


class Command(BaseCommand):
    help = "Generate right-sized WebP derivatives for every image under media/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--widths",
            default=",".join(str(w) for w in WIDTHS),
            help="Comma-separated pixel widths (default: the WIDTHS ladder).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-encode even when the derivative is already up to date.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be written, write nothing.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Also delete derivatives whose source image no longer exists.",
        )

    def handle(self, *args, **opts):
        try:
            widths = sorted({int(w) for w in str(opts["widths"]).split(",") if w.strip()})
        except ValueError:
            self.stderr.write(self.style.ERROR("--widths must be comma-separated integers"))
            return
        if not widths:
            self.stderr.write(self.style.ERROR("no widths to generate"))
            return

        force = opts["force"]
        dry = opts["dry_run"]
        root = Path(settings.MEDIA_ROOT)

        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing will be written"))
        self.stdout.write(f"media root : {root}")
        self.stdout.write(f"derivatives: {root / DERIV_DIRNAME}")
        self.stdout.write(f"widths     : {widths}")
        self.stdout.write("")

        created = skipped = failed = 0
        saved_bytes = 0

        for rel in iter_media_images():
            src = root / rel
            src_size = src.stat().st_size
            src_width = _pixel_width(src)
            for width in widths:
                # Skip widths at or above the source's own pixel width: the
                # derivative could only ever be a re-encode of the same size,
                # which is more bytes for no extra detail.
                if src_width and width >= src_width:
                    skipped += 1
                    continue
                if dry:
                    created += 1
                    continue
                out = ensure_derivative(rel, width, force=force)
                if not out:
                    failed += 1
                    continue
                out_path = root / out
                if out_path.stat().st_size < src_size:
                    saved_bytes += src_size - out_path.stat().st_size
                    created += 1
                else:
                    # The original was already smaller (e.g. a tiny logo); keep
                    # the derivative out of the way and serve the original.
                    skipped += 1

        if opts["prune"]:
            pruned = self._prune(root, dry)
        else:
            pruned = 0

        self.stdout.write("")
        self.stdout.write(
            f"{'would write' if dry else 'written'}: {created}   "
            f"skipped: {skipped}   failed: {failed}   pruned: {pruned}"
        )
        if not dry and saved_bytes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"total bytes avoided when a derivative is served: "
                    f"{saved_bytes / 1024 / 1024:.2f} MB"
                )
            )

    def _prune(self, root: Path, dry: bool) -> int:
        """Delete derivatives whose source image is gone."""
        deriv_root = root / DERIV_DIRNAME
        if not deriv_root.exists():
            return 0
        pruned = 0
        for path in sorted(deriv_root.rglob("*.webp")):
            # deriv/<subdir>/<name>.w<width>.webp -> <subdir>/<name>.<ext>
            rel = path.relative_to(deriv_root).as_posix()
            stem = rel
            for marker in (".w162.", ".w288.", ".w640.", ".w1080."):
                if marker in stem:
                    stem = stem.split(marker)[0]
                    break
            else:
                continue
            if any((root / f"{stem}{ext}").exists() for ext in SUPPORTED_SUFFIXES):
                continue
            pruned += 1
            if not dry:
                path.unlink(missing_ok=True)
        return pruned
