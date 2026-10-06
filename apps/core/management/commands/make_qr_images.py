"""
Generate printable QR images for every active QrCode (spec sections 14, 47).

Output: media/qr/<qr_code_name>.png and .svg
Each image encodes the permanent /q/<redirect_key>/ URL, so printed codes
stay valid while destinations change (spec section 23).
"""

from pathlib import Path

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse

from apps.core.models import QrCode


class Command(BaseCommand):
    help = "Render PNG + SVG QR images for all active QR codes."

    def handle(self, *args, **options):
        out_dir = Path(settings.MEDIA_ROOT) / "qr"
        out_dir.mkdir(parents=True, exist_ok=True)

        for qr in QrCode.objects.filter(active=True):
            from apps.core.qr_utils import get_qr_url, generate_qr_png_bytes, generate_qr_svg_bytes
            url = get_qr_url(qr.redirect_key)

            png_data = generate_qr_png_bytes(url)
            with open(out_dir / f"{qr.qr_code_name}.png", "wb") as f:
                f.write(png_data)

            svg_data = generate_qr_svg_bytes(url)
            with open(out_dir / f"{qr.qr_code_name}.svg", "wb") as f:
                f.write(svg_data)

            self.stdout.write(f"  {qr.qr_code_name} -> {url}")

        self.stdout.write(self.style.SUCCESS(f"QR images written to {out_dir}"))
