"""
Template helpers for optimised image delivery.

Usage inside a ``<picture>``, leaving the existing ``<img>`` untouched::

    {% load media_tags %}
    <picture>
      <source srcset="{{ brand.logo|deriv_url:288 }}" type="image/webp">
      <img src="{{ brand.logo.url }}" alt="..." width="104" height="104"
           decoding="async">
    </picture>

The ``<img>`` is deliberately left exactly as it was. Two reasons:

  * it is the fallback for any browser without WebP support, so nothing can
    regress on an old device;
  * the accessibility tests assert on ``width``, ``height``, ``alt``,
    ``decoding`` and ``loading`` in the served HTML. Rewriting the ``<img>``
    from Python would put those contracts at risk for no gain.

The filter returns an empty string when no derivative could be produced, so
the ``<source>`` is simply ignored and the original image is used. A failed
optimisation must never break a guest page.
"""

from django import template

from apps.core.media_optim import derivative_url

register = template.Library()


@register.filter
def deriv_url(source, width):
    """URL of the WebP derivative for ``source`` at ``width``, or "".

    ``source`` may be an ImageField, a media-relative path such as
    ``"icons/Green Circle Phone Icon.png"``, or a served ``/media/...`` URL.
    """
    if not source:
        return ""
    try:
        width = int(width)
    except (TypeError, ValueError):
        return ""
    return derivative_url(source, width) or ""
