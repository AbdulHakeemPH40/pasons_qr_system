"""
Generate image derivatives when a model image is saved.

``media_optim.ensure_derivative`` already generates a derivative on first use,
so nothing breaks without this signal. What the signal does is move that cost
off the guest's request and onto the staff member's save, which is the right
trade: panel saves are rare and performed by a colleague on a desktop, while
guest pages are hit constantly, often on a phone over mobile data.

Rules this follows:

  * **Never break a save.** Every failure is caught and logged. An image that
    cannot be encoded simply has no derivative, and the template falls back to
    the original ``<img>``.
  * **Models are discovered, not enumerated.** Any ``ImageField`` on any model
    is handled, so a new image field needs no change here.
  * **Cheap when there is nothing to do.** An up-to-date derivative costs one
    ``stat()`` per width.
"""

import logging

from django.db.models import ImageField
from django.db.models.signals import post_save

from apps.core.media_optim import WIDTHS, ensure_derivative

logger = logging.getLogger(__name__)


def _image_fields(instance):
    """Yield the non-empty ImageField values on a model instance."""
    for field in instance._meta.concrete_fields:
        if not isinstance(field, ImageField):
            continue
        value = getattr(instance, field.attname, None)
        # FieldFile is falsy when empty; also skip a plain "" or None.
        if not value:
            continue
        name = getattr(value, "name", None)
        if not name:
            continue
        yield name


def generate_derivatives(instance, widths=WIDTHS, **_kwargs):
    """post_save handler: warm the derivative cache for this instance's images."""
    try:
        names = list(_image_fields(instance))
    except Exception:  # pragma: no cover - introspection should not fail
        logger.debug("derivative signal: could not read fields on %r", instance, exc_info=True)
        return

    for name in names:
        for width in widths:
            try:
                ensure_derivative(name, width)
            except Exception:
                # Logged, never raised: a failed optimisation must not roll back
                # or block the save that triggered it.
                logger.warning("derivative failed for %s @%s", name, width, exc_info=True)


def register_image_models():
    """Connect the handler to every model that actually has an ImageField.

    Called once from ``CoreConfig.ready()``. Connecting per-model rather than
    to a global ``post_save`` means the handler is not invoked for every save
    in the project (analytics tap events, scans, sessions), only for the
    handful of models that can carry an image.

    Models are discovered at startup, so adding a new ImageField anywhere needs
    no change to this file.
    """
    from django.apps import apps

    connected = []
    for model in apps.get_models():
        # Skip models that are not ready or are abstract/unmanaged proxies.
        try:
            fields = model._meta.concrete_fields
        except Exception:
            continue
        if not any(isinstance(f, ImageField) for f in fields):
            continue
        post_save.connect(
            generate_derivatives,
            sender=model,
            weak=False,
            dispatch_uid=f"media_optim_derivatives.{model._meta.label}",
        )
        connected.append(model._meta.label)
    return connected
