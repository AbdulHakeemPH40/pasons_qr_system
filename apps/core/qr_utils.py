"""
QR Image Generation utility.
Shared between management command and web downloads (Spec Part D).
"""

import io
from pathlib import Path
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.urls import reverse


def get_qr_url(redirect_key, request=None):
    path = reverse("qr_landing", args=[redirect_key])
    if request:
        return request.build_absolute_uri(path)
    host = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS[0] != "*" else "localhost:8000"
    return f"http://{host}{path}"


def generate_qr_png_bytes(url, box_size=10, border=4):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#243024", back_color="#FAFCF8")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_qr_svg_bytes(url, box_size=10, border=4):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
        image_factory=qrcode.image.svg.SvgPathImage
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue()
