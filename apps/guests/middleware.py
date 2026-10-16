"""
Attaches `request.guest` and queues the identity cookie on the response.

Cost profile, because this runs on EVERY request:

  * no cookie            -> zero queries (GuestHandle is never resolved)
  * cookie, page ignores -> zero queries (still never resolved)
  * cookie, page reads   -> one indexed lookup by guest_id, once per request
  * a view creates one   -> one INSERT, plus the Set-Cookie below

The write to the cookie happens here rather than in each view so a view can
create the profile and then return a redirect without duplicating the logic.
"""

from .identity import attach, set_guest_cookie


class GuestIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        attach(request)
        response = self.get_response(request)
        guest_id = getattr(request, "_guest_cookie_to_set", None)
        if guest_id:
            set_guest_cookie(response, guest_id)
        return response
