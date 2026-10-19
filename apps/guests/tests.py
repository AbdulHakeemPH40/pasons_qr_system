"""
Guest identity suite (plan 2026-10-16, task 1).

Locks the cookie/identity contract:

  * an anonymous page view writes NOTHING and sets no cookie
  * a view that needs identity creates one row and one signed cookie
  * the same cookie reuses the same row across requests
  * a tampered or unsigned cookie is treated as "no guest", never trusted
  * the middleware adds zero queries when the cookie is absent, and zero
    queries when a page simply never looks at identity
"""

import csv
import io
import json
import urllib.error
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage

from . import identity, otp, panel_views, reporting, whatsapp
from .google import profile_fields_from_claims, verify_id_token
from .middleware import GuestIdentityMiddleware
from .models import GuestProfile, PhoneOTP
from .phone import COUNTRIES, normalise_phone, normalise_with_country, picker_countries

COOKIE = identity.COOKIE_NAME


def _hours_open_all_day():
    return {
        d: {"open": "00:00", "close": "23:59", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class PhoneNormalisationTests(TestCase):
    """No OTP step exists, so these shape checks are the only validation."""

    def test_accepts_the_shapes_a_guest_actually_types(self):
        expected = "+971501234567"
        for raw in (
            "+971501234567",
            "+971 50 123 4567",
            "00971501234567",
            "971501234567",
            "0501234567",
            "050 123 4567",
            "501234567",
            "  +971-50-123-4567  ",
        ):
            self.assertEqual(normalise_phone(raw), expected, msg=repr(raw))

    def test_rejects_what_cannot_be_a_number(self):
        for raw in ("", None, "   ", "abc", "call me", "12345", "0", "+"):
            self.assertEqual(normalise_phone(raw), "", msg=repr(raw))

    def test_rejects_absurdly_long_input(self):
        self.assertEqual(normalise_phone("+1234567890123456789"), "")

    def test_a_foreign_number_is_not_forced_into_the_local_country(self):
        """Guests are mostly local, but a tourist's number must survive intact."""
        self.assertEqual(normalise_phone("+447911123456"), "+447911123456")
        self.assertEqual(normalise_phone("447911123456"), "+447911123456")


class GuestQrFixtures(TestCase):
    """A brand, one outlet, and the QR a guest scans."""

    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Guest", code="KINGCHEF-GUEST", status="active"
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-GUEST-INTL",
            slug="guest-international-city",
            official_name="King Chef - International City",
            brand=cls.brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.page = SmartPage.objects.create(
            brand=cls.brand,
            outlet=cls.outlet,
            slug="guest-intlcity",
            page_title="King Chef - International City",
            published=True,
            published_at=timezone.now(),
        )
        cls.qr = QrCode.objects.create(
            brand=cls.brand,
            outlet=cls.outlet,
            destination_page=cls.page,
            source_type="table",
            label="Table 1",
            qr_code_name="KINGCHEF-GUEST-TABLE-001",
            redirect_key="kcguest-table-001",
        )

    @property
    def landing_url(self):
        return reverse("qr_landing", args=[self.qr.redirect_key])

    # --- WhatsApp one time code -----------------------------------------
    # The suite runs with WHATSAPP_OTP_DEBUG forced on (config/settings.py),
    # so no message is ever sent and the send endpoint answers with the code.
    # These helpers drive the REAL endpoints rather than seeding a session,
    # so the tests cover the same path a guest takes.

    def send_code(self, phone="050 123 4567", country="971"):
        response = self.client.post(
            reverse("guest_otp_send", args=[self.qr.redirect_key]),
            data={"country": country, "phone": phone},
            content_type="application/json",
        )
        return response, response.json()

    def verify_phone(self, phone="050 123 4567", country="971"):
        """Send and check a code, leaving the session holding a proof.

        A guest who already proved this number on this device is skipped by
        the server (no second message), so that answer is a success too.
        """
        _response, sent = self.send_code(phone=phone, country=country)
        self.assertTrue(sent.get("ok"), sent)
        if sent.get("already_verified"):
            return sent
        code = sent.get("debug_code")
        self.assertTrue(code, "debug delivery must return the code in tests")
        response = self.client.post(
            reverse("guest_otp_check", args=[self.qr.redirect_key]),
            data={"country": country, "phone": phone, "code": code},
            content_type="application/json",
        )
        return response.json()


class AnonymousBrowseWritesNothingTests(GuestQrFixtures):
    """The most important cost guarantee: browsing must not create rows."""

    def test_landing_page_creates_no_profile_and_sets_no_cookie(self):
        response = self.client.get(reverse("qr_landing", args=[self.qr.redirect_key]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuestProfile.objects.count(), 0)
        self.assertNotIn(COOKIE, response.cookies)
        self.assertNotContains(response, "guest-profile-open")


class SavedGuestWalletTests(GuestQrFixtures):
    """A saved profile gets a button. A first visit does not."""

    def _saved(self, **overrides):
        data = {
            "guest_id": "wallet-guest",
            "first_name": "Layla",
            "last_name": "Noor",
            "phone": "+971509990001",
            "first_brand": self.brand,
            "first_outlet": self.outlet,
        }
        data.update(overrides)
        profile = GuestProfile.objects.create(**data)
        self.client.cookies[COOKIE] = identity.sign_guest_id(profile.guest_id)
        return profile

    def test_a_saved_profile_shows_the_profile_button_with_name_and_mobile(self):
        self._saved()
        response = self.client.get(self.landing_url)
        self.assertContains(response, "guest-profile-open")
        self.assertContains(response, "Layla Noor")
        self.assertContains(response, "+971509990001")
        # Django prints a multi-line {# #} note as page text. That note
        # sat in the contact row and crushed the circles.
        self.assertNotContains(response, "Saved-guest wallet")
        body = response.content.decode()
        row = body.split('class="contact-row"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("guest-profile__sheet", row)
        self.assertIn('id="guest-profile"', body)

    def test_the_wallet_shows_ready_used_and_expired_for_this_brand_only(self):
        from datetime import timedelta

        from apps.rewards.models import RewardCoupon, RewardTier, RewardType

        profile = self._saved()
        other = Brand.objects.create(name_en="Other Wallet", code="OTHER-WALLET", status="active")
        RewardCoupon.objects.create(
            code="WAL-READY1",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() + timedelta(days=7),
        )
        RewardCoupon.objects.create(
            code="WAL-USED01",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.HIGH,
            reward_type=RewardType.PERCENT,
            percent=10,
            status=RewardCoupon.Status.REDEEMED,
            redeemed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        RewardCoupon.objects.create(
            code="WAL-OLD001",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="memory-match",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() - timedelta(days=1),
        )
        RewardCoupon.objects.create(
            code="WAL-OTHER1",
            profile=profile,
            brand=other,
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() + timedelta(days=7),
        )

        response = self.client.get(self.landing_url)
        self.assertContains(response, "WAL-READY1")
        self.assertContains(response, "Ready")
        self.assertContains(response, "WAL-USED01")
        self.assertContains(response, "Used")
        self.assertContains(response, "WAL-OLD001")
        self.assertContains(response, "Expired")
        self.assertNotContains(response, "WAL-OTHER1")

    def test_profile_button_links_to_the_dedicated_profile_page(self):
        self._saved()
        profile_url = reverse("guest_profile_page", args=[self.qr.redirect_key])
        response = self.client.get(self.landing_url)
        self.assertContains(response, f'href="{profile_url}"')


class DedicatedGuestProfilePageTests(GuestQrFixtures):
    """Dedicated /q/<key>/profile/ page: name editable anytime, mobile once per month."""

    @property
    def profile_url(self):
        return reverse("guest_profile_page", args=[self.qr.redirect_key])

    def _saved(self, **overrides):
        data = {
            "guest_id": "dedicated-profile-guest",
            "first_name": "Abdul",
            "last_name": "Hakeem",
            "phone": "+971564669930",
            "first_brand": self.brand,
            "first_outlet": self.outlet,
        }
        data.update(overrides)
        profile = GuestProfile.objects.create(**data)
        self.client.cookies[COOKIE] = identity.sign_guest_id(profile.guest_id)
        return profile

    def test_anonymous_visitor_is_redirected_to_landing(self):
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.landing_url)

    def test_changing_the_number_later_drops_the_verified_tick(self):
        """A number edited on the profile page was never proved.

        Without this reset a guest could verify once, then swap in any number
        and still count as verified, which is the hole the OTP step closes.
        """
        profile = self._saved(phone_verified=True)
        response = self.client.post(
            self.profile_url,
            {
                "first_name": "Abdul",
                "last_name": "Hakeem",
                "phone": "050 111 2233",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "+971501112233")
        self.assertFalse(profile.phone_verified)

    def test_renders_dedicated_profile_page_with_guest_details_and_coupons(self):
        from datetime import timedelta

        from apps.rewards.models import RewardCoupon, RewardTier, RewardType

        profile = self._saved()
        RewardCoupon.objects.create(
            code="KIN-86HD7D",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Abdul Hakeem")
        self.assertContains(response, "+971564669930")
        self.assertContains(response, "KIN-86HD7D")
        self.assertContains(response, "1 change / month")
        self.assertContains(response, '<span class="profile-pass__eyebrow">Your Profile</span>')
        self.assertNotContains(response, "Saved Guest Pass")

    def test_the_wallet_coupon_is_the_approved_win_ticket(self):
        """A coupon must ship as the silver ticket, not a flat rounded card.

        The client approved one reward design (design draft 2): a ticket cut
        with the code above a tear line and the usage stub below it. This
        locks the anatomy so a restyle cannot quietly flatten it back.
        """
        from datetime import timedelta

        from apps.rewards.models import RewardCoupon, RewardTier, RewardType

        profile = self._saved()
        RewardCoupon.objects.create(
            code="KIN-TICKET1",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.HIGH,
            reward_type=RewardType.PERCENT,
            percent=10,
            expires_at=timezone.now() + timedelta(days=14),
        )
        html = self.client.get(self.profile_url).content.decode()

        # the ticket anatomy, in the order the eye reads it
        for marker in (
            "guest-coupon__shell",
            "guest-coupon__ticket",
            "guest-coupon__brushed",
            "guest-coupon__sheen",
            "guest-coupon__codewrap",
            "guest-coupon__perf",
            "guest-coupon__stub",
        ):
            self.assertIn(marker, html, marker)

        # the code sits ABOVE the tear line, the stub below it
        self.assertLess(html.index("guest-coupon__codewrap"), html.index("guest-coupon__perf"))
        self.assertLess(html.index("guest-coupon__perf"), html.index("guest-coupon__stub"))

        # a discount ticket makes the number the prize
        self.assertIn('<span class="pct">%</span>', html)
        self.assertIn("Your code", html)
        self.assertIn("How to use", html)
        self.assertIn("one use only", html)
        # the discount face, not the dessert words
        self.assertIn("guest-coupon--discount", html)

    def test_the_wallet_coupon_keeps_the_cut_and_the_sweep(self):
        """The mask cut and the light sweep live in the stylesheet."""
        from pathlib import Path

        css = Path(__file__).resolve().parents[2] / "static" / "css" / "theme-warm.css"
        sheet = css.read_text()

        # the ticket cut: corner bites plus the side notches at the tear line
        self.assertIn("mask-composite: intersect", sheet)
        self.assertIn("--gc-scoop", sheet)
        self.assertIn("--gc-bite", sheet)
        # the tear line must land on the stub, or the notches drift
        self.assertIn("bottom: calc(var(--gc-stub) - 1px)", sheet)
        self.assertIn("height: var(--gc-stub)", sheet)
        # the light sweep, and its reduced-motion off switch
        self.assertIn("@keyframes gcSheen", sheet)
        self.assertIn("@keyframes gcTicketIn", sheet)

    def test_name_can_be_changed_multiple_times_without_locking_phone(self):
        profile = self._saved()
        for new_first, new_last in (("Hakeem", "K"), ("Abdul", "Rahman"), ("Zayd", "Ali")):
            resp = self.client.post(
                self.profile_url,
                {
                    "first_name": new_first,
                    "last_name": new_last,
                    "phone": "+971564669930",
                },
            )
            self.assertEqual(resp.status_code, 302)
            profile.refresh_from_db()
            self.assertEqual(profile.first_name, new_first)
            self.assertEqual(profile.last_name, new_last)
            self.assertIsNone(profile.phone_changed_at)
            self.assertTrue(profile.can_change_phone())

    def test_mobile_number_can_be_updated_once_per_calendar_month_only(self):
        profile = self._saved()
        # First mobile change in the current month succeeds:
        resp1 = self.client.post(
            self.profile_url,
            {
                "first_name": "Abdul",
                "last_name": "Hakeem",
                "phone": "050 222 3344",
            },
        )
        self.assertEqual(resp1.status_code, 302)
        self.assertIn("phone_updated=1", resp1["Location"])
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "+971502223344")
        self.assertIsNotNone(profile.phone_changed_at)
        self.assertFalse(profile.can_change_phone())

        # Second mobile change in the same month is rejected:
        resp2 = self.client.post(
            self.profile_url,
            {
                "first_name": "Abdul",
                "last_name": "Hakeem",
                "phone": "050 999 8877",
            },
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(
            resp2, "You can only change your mobile number once per month."
        )
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "+971502223344")

        # Even while mobile is locked for the month, changing the name still works:
        resp3 = self.client.post(
            self.profile_url,
            {
                "first_name": "Abdul",
                "last_name": "Kareem",
                "phone": "+971502223344",
            },
        )
        self.assertEqual(resp3.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.last_name, "Kareem")
        self.assertEqual(profile.phone, "+971502223344")

    def test_mobile_number_can_be_changed_again_in_the_next_calendar_month(self):
        from datetime import datetime

        profile = self._saved(
            phone="+971502223344",
            phone_changed_at=timezone.make_aware(datetime(2026, 9, 15, 12, 0)),
        )
        self.assertTrue(profile.can_change_phone())
        resp = self.client.post(
            self.profile_url,
            {
                "first_name": "Abdul",
                "last_name": "Hakeem",
                "phone": "050 777 6655",
            },
        )
        self.assertEqual(resp.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "+971507776655")
        self.assertFalse(profile.can_change_phone())



class GuestCookieCycleTests(TestCase):
    """Drives the middleware directly so the cycle is tested, not assumed."""

    def setUp(self):
        self.factory = RequestFactory()

    def _identity_view(self, request):
        profile, _created = identity.ensure_profile(request)
        return HttpResponse(str(profile.pk))

    def _read_view(self, request):
        profile = request.guest.profile
        return HttpResponse("none" if profile is None else str(profile.pk))

    def _run(self, view, cookie=None):
        request = self.factory.get("/")
        if cookie is not None:
            request.COOKIES[COOKIE] = cookie
        return GuestIdentityMiddleware(view)(request)

    def test_first_touch_creates_one_row_and_a_signed_cookie(self):
        response = self._run(self._identity_view)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuestProfile.objects.count(), 1)
        raw = response.cookies[COOKIE].value
        self.assertNotEqual(raw, "")
        # the cookie never carries the bare id: it must be signed
        profile = GuestProfile.objects.get()
        self.assertNotEqual(raw, profile.guest_id)
        self.assertEqual(identity.unsign_guest_id(raw), profile.guest_id)

    def test_second_visit_reuses_the_same_row(self):
        first = self._run(self._identity_view)
        first_pk = first.content.decode()
        second = self._run(self._read_view, cookie=first.cookies[COOKIE].value)
        self.assertEqual(second.content.decode(), first_pk)
        self.assertEqual(GuestProfile.objects.count(), 1)

    def test_tampered_cookie_is_treated_as_no_guest(self):
        response = self._run(self._read_view, cookie="not-a-signed-value")
        self.assertEqual(response.content.decode(), "none")

    def test_unsigned_raw_id_cookie_is_rejected(self):
        """Someone pasting a guessed id must not become that guest."""
        profile = GuestProfile.objects.create(guest_id="guessed-guest-id")
        response = self._run(self._read_view, cookie=profile.guest_id)
        self.assertEqual(response.content.decode(), "none")

    def test_no_queries_without_a_cookie(self):
        """A first-time visitor costs the middleware nothing."""
        with self.assertNumQueries(0):
            self._run(self._read_view)

    def test_no_queries_when_the_page_ignores_identity(self):
        """A returning guest on a page that never asks costs nothing either."""
        profile = GuestProfile.objects.create(guest_id="existing-guest-id")
        cookie = identity.sign_guest_id(profile.guest_id)
        with self.assertNumQueries(0):
            response = self._run(
                lambda request: HttpResponse("plain"), cookie=cookie
            )
        self.assertEqual(response.content.decode(), "plain")

    def test_cookie_is_http_only_and_lax(self):
        response = self._run(self._identity_view)
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/")

    def test_the_cookie_is_not_secure_while_the_site_is_plain_http(self):
        """A Secure cookie is discarded silently over http.

        The live site runs over http://<ip> with DEBUG off. While the flag
        followed DEBUG the browser threw every cookie away, so each visit
        minted a new guest and a coupon could never survive a page load.
        """
        with self.settings(GUEST_COOKIE_SECURE=False):
            response = self._run(self._identity_view)
        self.assertFalse(response.cookies[COOKIE]["secure"])

    def test_the_cookie_is_secure_once_https_is_on(self):
        with self.settings(GUEST_COOKIE_SECURE=True):
            response = self._run(self._identity_view)
        self.assertTrue(response.cookies[COOKIE]["secure"])


class EnsureProfileReuseTests(TestCase):
    def test_ensure_profile_is_idempotent_within_one_request(self):
        request = RequestFactory().get("/")
        identity.attach(request)
        first, created_first = identity.ensure_profile(request)
        second, created_second = identity.ensure_profile(request)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(GuestProfile.objects.count(), 1)

    def test_origin_brand_and_outlet_stamp_once(self):
        brand = Brand.objects.create(name_en="Origin Brand", code="ORIGIN", status="active")
        outlet = Outlet.objects.create(
            code="ORIGIN-ONE", slug="origin-one", official_name="Origin One", brand=brand
        )
        request = RequestFactory().get("/")
        identity.attach(request)
        identity.ensure_profile(request, brand=brand, outlet=outlet)
        profile = GuestProfile.objects.get()
        self.assertEqual(profile.first_brand, brand)
        self.assertEqual(profile.first_outlet, outlet)

        # a later request with a different outlet must not overwrite the first
        request2 = RequestFactory().get("/")
        identity.attach(request2)
        request2.COOKIES[COOKIE] = identity.sign_guest_id(profile.guest_id)
        other = Outlet.objects.create(
            code="ORIGIN-TWO", slug="origin-two", official_name="Origin Two", brand=brand
        )
        identity.ensure_profile(request2, brand=brand, outlet=other)
        profile.refresh_from_db()
        self.assertEqual(profile.first_outlet, outlet)


class InstagramFallbackPageTests(GuestQrFixtures):
    """GET /q/<key>/instagram/thanks/ -- the stable bio link."""

    def _url(self):
        return reverse("guest_instagram_thanks", args=[self.qr.redirect_key])

    def test_renders_the_sheet_open_at_the_question(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Did you follow us?")
        body = response.content.decode()
        self.assertIn('data-base="ask"', body)
        self.assertIn('data-state="ask"', body)
        self.assertNotIn('id="ig-draw-popup" hidden', body)

    def test_form_posts_back_to_this_qr(self):
        action = reverse("guest_identity_submit", args=[self.qr.redirect_key])
        self.assertContains(self.client.get(self._url()), f'action="{action}"')

    def test_the_follower_gift_is_never_a_dessert_or_a_discount(self):
        """Client decision 2026-10-16.

        Following us on Instagram is its own gift. It is NOT the game
        dessert and NOT the game discount, and MANAGEMENT decides what the
        gift is, so the copy must never promise a specific item.

        Asserted on this page, not the landing page: the landing page also
        carries the Games card, which promises a gift in its own words
        ("Win a gift, our team picks it") and is asserted in
        apps/games/tests.py. Neither promise names a specific prize.
        """
        body = self.client.get(self._url()).content.decode()
        low = body.lower()
        for promise in ("dessert", "discount", "% off", "free"):
            self.assertNotIn(promise, low, f"the sheet still promises: {promise}")
        self.assertIn("Our team decides what the gift is", body)
        self.assertIn("Follow us and get a gift", body)

    def test_the_form_says_the_mobile_must_match_before_submit(self):
        """The mobile number is the handle staff match at the counter when a
        guest redeems, so the form says so BEFORE the guest submits."""
        body = self.client.get(self._url()).content.decode()
        self.assertIn("We send a 6 digit code on WhatsApp to check this number", body)
        self.assertIn("Use your own number: it must match when you claim", body)
        # The note sits under the mobile field, not somewhere else on the page.
        phone_at = body.index('name="phone"')
        note_at = body.index("Use your own number: it must match when you claim")
        self.assertLess(phone_at, note_at)

    def test_unknown_key_is_404(self):
        response = self.client.get(
            reverse("guest_instagram_thanks", args=["no-such-key"])
        )
        self.assertEqual(response.status_code, 404)


class LandingSheetTests(GuestQrFixtures):
    """The sheet on the landing page, and the states the server can open."""

    def test_sheet_is_present_but_closed_by_default(self):
        body = self.client.get(self.landing_url).content.decode()
        self.assertIn('id="ig-draw-popup" hidden', body)
        self.assertIn('data-state="entry"', body)
        self.assertIn("Follow us and get a gift", body)
        # all four panels ship with the page; the script switches between them
        for panel in ("entry", "ask", "form", "done"):
            self.assertIn(f'data-panel="{panel}"', body)

    def test_joined_opens_the_confirmation(self):
        body = self.client.get(self.landing_url + "?joined=1").content.decode()
        self.assertIn('data-state="done"', body)
        self.assertNotIn('id="ig-draw-popup" hidden', body)

    def test_submit_error_opens_the_form_with_the_message(self):
        body = self.client.get(
            self.landing_url + "?identity_error=bad_phone"
        ).content.decode()
        self.assertIn('data-state="form"', body)
        self.assertIn("does not look right", body)

    def test_sheet_carries_the_return_detection_and_the_form(self):
        body = self.client.get(self.landing_url).content.decode()
        # the CTA that opens Instagram is left un-prevented so the new tab
        # can carry the tap-tracked redirect
        self.assertIn("data-ig-go", body)
        self.assertIn("data-ig-answer", body)
        self.assertIn("visibilitychange", body)
        self.assertIn('name="phone"', body)
        self.assertIn('name="consent"', body)

    def test_the_sheet_carries_the_code_step_and_its_controls(self):
        body = self.client.get(self.landing_url).content.decode()
        self.assertIn('data-panel="code"', body)
        # country picker, UAE preselected. The value that posts is the dial
        # code, still carried by a field named `country`, so nothing about the
        # submitted form changed when the native select became a flag picker.
        self.assertIn('name="country"', body)
        self.assertIn('value="971"', body)
        # the code field lets the phone fill it from the WhatsApp message
        self.assertIn('autocomplete="one-time-code"', body)
        self.assertIn("Didn't get it?", body)
        self.assertIn("Wrong number? Edit the number", body)
        key = self.qr.redirect_key
        self.assertIn(f"/q/{key}/identity/otp/send/", body)
        self.assertIn(f"/q/{key}/identity/otp/check/", body)

    def test_the_country_picker_is_flags_and_dial_codes_not_a_select(self):
        """Client direction 2026-10-19: no country names in the sheet.

        The picker is a searchable list of flags and dial codes. This locks
        three things that would each be a silent regression:

        1. the native select is gone (it could not be searched, and on a
           desktop it spilled outside the card),
        2. every row carries a flag and a shorter search haystack than the
           visible text, so "uae" and "91" both find something,
        3. no country NAME is printed: the only visible text on a row is the
           dial code.
        """
        body = self.client.get(self.landing_url).content.decode()
        self.assertNotIn("<select", body)
        self.assertIn("ig-picker__row", body)
        self.assertIn('data-picker-search', body)
        # one row per country, each with its flag file. Counted on the class,
        # not on data-picker-row: the script in the same partial mentions that
        # attribute twice.
        self.assertEqual(body.count('class="ig-picker__row"'), len(COUNTRIES))
        self.assertIn("/static/img/flags/ae.png", body)
        self.assertIn("/static/img/flags/in.png", body)
        # every row is a flag, a dial code, and a tick. The English name lives
        # only in data-search and aria-label, never between the tags.
        for dial, _name, _iso in COUNTRIES:
            self.assertIn(f'<span class="ig-picker__dial">+{dial}</span>', body)

    def test_the_unverified_error_explains_the_code_step(self):
        body = self.client.get(
            self.landing_url + "?identity_error=phone_unverified"
        ).content.decode()
        self.assertIn('data-state="form"', body)
        self.assertIn("Please verify your mobile number with the code", body)

    def test_a_full_code_never_verifies_itself(self):
        """Client direction 2026-10-19: no auto approve.

        Six digits must not sign anyone in on their own. A code that arrives
        whole (WhatsApp autofill, a paste, a fast thumb) still waits for the
        guest to look at it and tap "Verify and continue". The readiness ring
        is the only thing a complete code changes.

        This locks the three ways the rule could quietly come back:

        1. no side effect on the sixth digit,
        2. the tap is wired to the check,
        3. Enter still submits, because a keyboard is an explicit act too.
        """
        body = self.client.get(self.landing_url).content.decode()
        self.assertNotIn("this.value.length === 6", body)
        self.assertIn(
            'verifyButton.addEventListener("click", verifyCode)', body
        )
        self.assertIn('verifyButton.setAttribute("data-ready"', body)
        self.assertIn('if (e.key === "Enter")', body)
        # a refused code clears the field and says how many tries are left,
        # so the guest never taps a code the server already rejected
        self.assertIn('verifyButton.setAttribute("aria-busy", "true")', body)

    def test_a_short_code_says_what_is_missing_instead_of_silently_staying(self):
        """A tap on an empty field must explain itself, not do nothing."""
        body = self.client.get(self.landing_url).content.decode()
        self.assertIn("Enter the 6 digits from the WhatsApp message.", body)


class SheetMaterialCssTests(TestCase):
    """The sheet and the pre-game prompt must not be see-through.

    Client report 2026-10-19: over a game, the page behind showed THROUGH the
    sign-in card and through the pre-game prompt, so two sets of words landed
    on top of each other and neither could be read. The fix is an opaque warm
    cream surface plus a deep scrim, and this test locks it so a later "make
    it look more glassy" pass cannot quietly bring the ghosting back.

    The material is also the reason there is no backdrop-filter left on either
    layer: an opaque surface has nothing to sample, and a blur over a live
    game canvas is re-sampled on every frame.
    """

    @staticmethod
    def _rule(css, selector):
        """The declaration block of the first rule that opens with `selector`.

        Brace balanced on purpose: a regex over the whole stylesheet drifts
        as soon as one comment or one nested at-rule block upsets the
        pairing, and then it silently matches the wrong rule.
        """
        at = css.find(selector + " {")
        if at == -1:
            return ""
        start = css.index("{", at)
        depth = 0
        for i in range(start, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    return css[start + 1 : i]
        return ""

    def setUp(self):
        from pathlib import Path

        from django.conf import settings

        self.css = (
            Path(settings.BASE_DIR) / "static" / "css" / "theme-warm.css"
        ).read_text(encoding="utf-8")

    def test_the_sheet_surface_is_opaque_cream(self):
        glass = self._rule(self.css, "body.theme-warm .ig-draw__glass")
        self.assertTrue(glass, "the sheet's surface rule is gone")
        self.assertIn(
            "background-color: #",
            glass,
            "the sheet must declare an opaque background-color: a translucent "
            "gradient alone is what let the game read through the form",
        )
        self.assertNotIn(
            "backdrop-filter",
            glass,
            "an opaque surface has nothing to blur; a filter here is a per "
            "frame cost with no visual gain",
        )

    def test_the_scrim_dims_without_blurring_a_live_game(self):
        scrim = self._rule(self.css, "body.theme-warm .ig-draw__backdrop")
        self.assertTrue(scrim, "the scrim rule is gone")
        self.assertNotIn(
            "backdrop-filter",
            scrim,
            "a blur on the scrim is re-sampled on every frame of the game "
            "canvas running underneath it",
        )
        self.assertIn("radial-gradient", scrim)

    def test_the_pregame_prompt_is_opaque_too(self):
        card = self._rule(self.css, "body.theme-warm .page--play .game-nudge__card")
        self.assertTrue(card, "the pre-game prompt card rule is gone")
        self.assertIn(
            "background-color: #",
            card,
            "the chess setup panel read straight through this card at 16% "
            "opacity and collided with its own copy",
        )

    def test_the_form_does_not_show_a_scroll_bar(self):
        scroll = self._rule(self.css, "body.theme-warm .ig-draw__scroll")
        self.assertIn(
            "scrollbar-width: none",
            scroll,
            "the operating system scroll track drew a pale line down the edge "
            "of the form and read as a broken border",
        )
        self.assertIn("::-webkit-scrollbar", self.css)

    def test_a_short_phone_keeps_continue_above_the_fold(self):
        """375x667 is the smallest screen the client tests on.

        The form is taller than the card there, so the primary action fell
        below the fold, and with the scroll bar hidden there was no cue that
        anything was below. Compact mode gives the card more height and drops
        the decorative icon.
        """
        self.assertIn("@media (max-height: 720px)", self.css)
        start = self.css.index("@media (max-height: 720px)")
        block = self.css[start : self.css.index("\n}\n", start)]
        self.assertIn("body.theme-warm .ig-draw__icon { display: none; }", block)
        self.assertIn("max-height: 98%", block)

    def test_the_readiness_ring_is_a_shadow_not_a_new_surface(self):
        """A complete code lights the button; it does not layer a new one.

        A fifth glass layer, or a size change, over the blurred scrim is
        exactly the repaint this sheet was rebuilt to avoid. The ring is a
        box-shadow, which composites without touching the layers behind it.
        """
        ready = self._rule(
            self.css, 'body.theme-warm .ig-draw__cta[data-ready="true"]'
        )
        self.assertTrue(ready, "the readiness cue is gone")
        self.assertIn("box-shadow", ready)
        self.assertNotIn("backdrop-filter", ready)
        self.assertNotIn("width", ready)
        self.assertNotIn("background", ready)


class IdentitySubmitTests(GuestQrFixtures):
    """POST /q/<key>/identity/ -- the single write in the guest flow."""

    def _post(self, **overrides):
        # `claimed_phone` proves one number and then posts a different one,
        # which is the flow a tester cannot reach by accident.
        claimed = overrides.pop("claimed_phone", None)
        payload = {
            "first_name": "Aisha",
            "last_name": "Rahman",
            "country": "971",
            "phone": "050 123 4567",
            "consent": "1",
            "next": self.landing_url,
        }
        payload.update(overrides)
        # The form refuses a number that was not proved, so prove it first,
        # exactly as the sheet does. A test about a wrong shape skips this
        # because no code can be sent to a number that is not a number.
        if normalise_with_country(payload["country"], payload["phone"]):
            self.verify_phone(phone=payload["phone"], country=payload["country"])
        if claimed is not None:
            payload["phone"] = claimed
        return self.client.post(
            reverse("guest_identity_submit", args=[self.qr.redirect_key]), payload
        )

    def test_valid_submit_saves_the_profile_and_confirms(self):
        response = self._post(ig_follow="1")
        self.assertEqual(response.status_code, 302)
        self.assertIn("joined=1", response["Location"])

        profile = GuestProfile.objects.get()
        self.assertEqual(profile.first_name, "Aisha")
        self.assertEqual(profile.last_name, "Rahman")
        self.assertEqual(profile.phone, "+971501234567")
        self.assertTrue(profile.phone_verified)
        self.assertTrue(profile.consent_marketing)
        self.assertIsNotNone(profile.consent_at)
        self.assertTrue(profile.ig_follow_claimed)
        self.assertIsNotNone(profile.ig_claimed_at)
        self.assertEqual(profile.first_brand, self.brand)
        self.assertEqual(profile.first_outlet, self.outlet)
        # the identity cookie rides out on the redirect
        self.assertIn(COOKIE, response.cookies)

    def test_phone_never_appears_in_the_redirect_url(self):
        """A mobile number in a query string would leak into history and
        Referer headers, so the bounce carries only a short code."""
        location = self._post()["Location"]
        self.assertNotIn("9715", location)
        self.assertNotIn("phone", location)

    def test_without_consent_nothing_is_saved(self):
        response = self._post(consent="")
        self.assertIn("identity_error=no_consent", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 0)

    def test_bad_phone_is_rejected(self):
        response = self._post(phone="not a number")
        self.assertIn("identity_error=bad_phone", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 0)

    def test_missing_name_is_rejected(self):
        response = self._post(first_name="   ")
        self.assertIn("identity_error=missing_name", response["Location"])

    def test_failed_submit_keeps_the_typed_values_out_of_the_url(self):
        response = self._post(phone="oops", ig_follow="1")
        self.assertNotIn("oops", response["Location"])
        body = self.client.get(response["Location"]).content.decode()
        self.assertIn('value="Aisha"', body)
        self.assertIn('data-state="form"', body)
        # the Instagram answer survives the round trip
        self.assertIn('value="1" data-ig-flag', body)

    def test_draft_is_consumed_once(self):
        response = self._post(phone="oops")
        self.client.get(response["Location"])  # the render that reads it
        self.assertNotIn("Aisha", self.client.get(self.landing_url).content.decode())

    def test_next_is_allow_listed_against_open_redirect(self):
        response = self._post(next="https://evil.example.com/steal")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(self.landing_url))
        self.assertNotIn("evil.example.com", response["Location"])

    def test_protocol_relative_next_is_rejected(self):
        response = self._post(next="//evil.example.com")
        self.assertNotIn("evil.example.com", response["Location"])

    def test_a_submit_from_the_play_page_returns_to_the_game(self):
        """The play page renders the sheet in place (bug fix 2026-10-17).

        Its `next` carries the page's own query string
        (/games/<slug>/?back=/q/<key>/), so the bounce has to APPEND the
        flag with '&'. A second '?' would swallow joined=1 into the back
        value: the guest would land on the game with no confirmation, and
        Exit would point at a nonsense key.
        """
        play_url = (
            reverse("games_play", args=["chess-master"]) + f"?back={self.landing_url}"
        )
        response = self._post(next=play_url)

        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith(play_url), location)

        query = parse_qs(urlparse(location).query)
        self.assertEqual(query.get("joined"), ["1"])
        # the game's own parameter survived intact, so Exit still works
        self.assertEqual(query.get("back"), [self.landing_url])

        self.assertEqual(GuestProfile.objects.count(), 1)
        self.assertTrue(GuestProfile.objects.get().is_identified)

        # the guest lands back on the game with the confirmation open
        body = self.client.get(location).content.decode()
        self.assertIn('data-state="done"', body)
        self.assertIn("Thanks, Aisha!", body)
        self.assertIn("You are signed in", body)

    def test_second_submit_reuses_the_same_profile(self):
        self._post()
        first_pk = GuestProfile.objects.get().pk
        self._post()
        self.assertEqual(GuestProfile.objects.count(), 1)
        self.assertEqual(GuestProfile.objects.get().pk, first_pk)

    def test_answering_not_yet_never_erases_an_earlier_claim(self):
        self._post(ig_follow="1")
        self._post(ig_follow="0")
        self.assertTrue(GuestProfile.objects.get().ig_follow_claimed)

    def test_get_is_not_allowed(self):
        response = self.client.get(
            reverse("guest_identity_submit", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 405)

    def test_unknown_key_is_404(self):
        response = self.client.post(
            reverse("guest_identity_submit", args=["no-such-key"]),
            {"first_name": "A", "phone": "0501234567", "consent": "1"},
        )
        self.assertEqual(response.status_code, 404)

    def test_a_number_that_was_never_proved_is_refused(self):
        """No code, no profile. This is the whole point of the OTP step."""
        response = self.client.post(
            reverse("guest_identity_submit", args=[self.qr.redirect_key]),
            {
                "first_name": "Aisha",
                "last_name": "Rahman",
                "country": "971",
                "phone": "050 123 4567",
                "consent": "1",
                "next": self.landing_url,
            },
        )
        self.assertIn("identity_error=phone_unverified", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 0)
        # the typed values are kept out of the URL, as on every other error
        self.assertNotIn("9715", response["Location"])

    def test_proving_one_number_does_not_let_another_one_through(self):
        response = self._post(claimed_phone="050 999 8887")
        self.assertIn("identity_error=phone_unverified", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 0)

    def test_the_country_picker_decides_the_country(self):
        response = self._post(country="44", phone="07911 123456")
        self.assertIn("joined=1", response["Location"])
        self.assertEqual(GuestProfile.objects.get().phone, "+447911123456")

    def test_a_proof_is_spent_by_the_submit_it_verified(self):
        """One code buys one profile, not two."""
        self._post()
        self.assertEqual(GuestProfile.objects.count(), 1)
        second = self.client.post(
            reverse("guest_identity_submit", args=[self.qr.redirect_key]),
            {
                "first_name": "Someone",
                "last_name": "Else",
                "country": "971",
                "phone": "050 123 4567",
                "consent": "1",
                "next": self.landing_url,
            },
        )
        self.assertIn("identity_error=phone_unverified", second["Location"])
        self.assertEqual(GuestProfile.objects.count(), 1)


# --------------------------------------------------------------------------
# WhatsApp one time code (2026-10-19)
# --------------------------------------------------------------------------

PHONE = "+971501234567"


class SignOutAndReturningGuestTests(GuestQrFixtures):
    """Sign out forgets the browser, not the account.

    Client decision 2026-10-19: the mobile number is the account. A guest who
    signs out and signs back in with the same number must land on the same
    row, with the same coupons and the same ladder. Clearing cookies used to
    mint a second account, and the coupons on the first one looked lost.
    """

    def _profile(self, **overrides):
        data = {
            "guest_id": "returning-guest",
            "first_name": "Reem",
            "last_name": "Khalid",
            "phone": PHONE,
            "phone_verified": True,
            "first_brand": self.brand,
            "first_outlet": self.outlet,
        }
        data.update(overrides)
        return GuestProfile.objects.create(**data)

    def _sign_in_as(self, profile):
        self.client.cookies[COOKIE] = identity.sign_guest_id(profile.guest_id)
        return profile

    def _sign_out(self, next_url=None):
        response = self.client.post(
            reverse("guest_signout", args=[self.qr.redirect_key]),
            {"next": next_url or self.landing_url},
        )
        # A genuinely signed-out browser: the test client would otherwise keep
        # the empty Morsel and every later request would look "signed out" for
        # the wrong reason.
        self.client.cookies.pop(COOKIE, None)
        return response

    def _submit(self, **overrides):
        payload = {
            "first_name": "Reem",
            "last_name": "",
            "country": "971",
            "phone": "050 123 4567",
            "consent": "1",
            "next": self.landing_url,
        }
        payload.update(overrides)
        return self.client.post(
            reverse("guest_identity_submit", args=[self.qr.redirect_key]), payload
        )

    # --- sign out -------------------------------------------------------

    def test_sign_out_clears_the_cookie_and_keeps_the_account(self):
        profile = self._sign_in_as(self._profile())
        response = self._sign_out()

        self.assertEqual(response.status_code, 302)
        # delete_cookie answers with an already-expired cookie
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
        self.assertTrue(GuestProfile.objects.filter(pk=profile.pk).exists())

    def test_sign_out_returns_to_the_page_it_came_from(self):
        self._sign_in_as(self._profile())
        back = self.landing_url
        response = self._sign_out(next_url=back)
        self.assertEqual(response["Location"], back)

    def test_sign_out_refuses_an_off_site_destination(self):
        self._sign_in_as(self._profile())
        response = self.client.post(
            reverse("guest_signout", args=[self.qr.redirect_key]),
            {"next": "https://evil.example.com/steal"},
        )
        self.assertTrue(response["Location"].startswith(self.landing_url))
        self.assertNotIn("evil.example.com", response["Location"])

    def test_sign_out_is_post_only(self):
        self._sign_in_as(self._profile())
        response = self.client.get(
            reverse("guest_signout", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 405)

    def test_sign_out_drops_a_pending_code_proof(self):
        """The proof vouches for a number, not for a browser session."""
        self.verify_phone()
        self.assertIn(otp.SESSION_KEY, self.client.session)
        self._sign_out()
        self.assertNotIn(otp.SESSION_KEY, self.client.session)

    def test_sign_out_on_an_unknown_qr_key_is_404(self):
        response = self.client.post(reverse("guest_signout", args=["no-such-key"]))
        self.assertEqual(response.status_code, 404)

    # --- coming back ----------------------------------------------------

    def test_signing_back_in_with_the_same_number_reopens_the_same_account(self):
        from datetime import timedelta

        from apps.rewards.models import RewardCoupon, RewardTier, RewardType

        profile = self._profile()
        RewardCoupon.objects.create(
            code="RET-READY1",
            profile=profile,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self._sign_in_as(profile)
        self._sign_out()

        verified = self.verify_phone()
        self.assertTrue(verified["ok"])
        self.assertTrue(verified.get("returning"), verified)

        response = self._submit()
        self.assertIn("joined=1", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 1)
        self.assertEqual(GuestProfile.objects.get().pk, profile.pk)

        # the coupon is back on the page the guest lands on
        landing = self.client.get(self.landing_url)
        self.assertContains(landing, "RET-READY1")
        self.assertContains(landing, "Reem Khalid")

    def test_a_blank_field_never_erases_the_stored_name(self):
        profile = self._profile()
        self._sign_in_as(profile)
        self._sign_out()

        self.verify_phone()
        self._submit(last_name="")

        profile.refresh_from_db()
        self.assertEqual(profile.last_name, "Khalid")

    def test_a_different_number_does_not_take_the_old_account(self):
        profile = self._profile()
        self._sign_in_as(profile)
        self._sign_out()

        # +971 50 999 8887 has never been verified before
        self.verify_phone(phone="050 999 8887")
        response = self._submit(phone="050 999 8887")

        self.assertIn("joined=1", response["Location"])
        self.assertEqual(GuestProfile.objects.count(), 2)
        self.assertTrue(GuestProfile.objects.filter(pk=profile.pk).exists())

    def test_anonymous_history_on_this_device_moves_into_the_account(self):
        account = self._profile()
        anon = GuestProfile.objects.create(
            guest_id="anon-device",
            ig_follow_claimed=True,
            ig_claimed_at=timezone.now(),
        )
        self._sign_in_as(anon)

        self.assertTrue(self.verify_phone().get("returning"))
        self._submit()

        self.assertEqual(GuestProfile.objects.count(), 1)
        survivor = GuestProfile.objects.get()
        self.assertEqual(survivor.pk, account.pk)
        self.assertTrue(survivor.ig_follow_claimed)

    def test_a_profile_verified_with_another_number_is_left_alone(self):
        """A shared tablet: the second guest signs in, the first keeps their row."""
        other_person = self._profile(guest_id="first-guest", phone="+971509990001")
        owner = self._profile(guest_id="phone-owner")
        self._sign_in_as(other_person)

        self.assertTrue(self.verify_phone().get("returning"))

        # this browser now belongs to the account that owns PHONE, and the
        # account that owns the other number is untouched
        self.assertEqual(GuestProfile.objects.count(), 2)
        self.assertTrue(GuestProfile.objects.filter(pk=other_person.pk).exists())

        cookie = self.client.cookies[COOKIE].value
        signing_in_as = GuestProfile.objects.get(
            guest_id=identity.unsign_guest_id(cookie)
        )
        self.assertEqual(signing_in_as.pk, owner.pk)

    def test_duplicate_accounts_for_one_number_are_folded_together(self):
        from datetime import timedelta

        from apps.rewards.models import RewardCoupon, RewardTier, RewardType

        older = self._profile(guest_id="older-account")
        newer = self._profile(guest_id="newer-account")
        RewardCoupon.objects.create(
            code="OLD-COUPON",
            profile=newer,
            brand=self.brand,
            outlet=self.outlet,
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            reward_type=RewardType.DESSERT,
            expires_at=timezone.now() + timedelta(days=7),
        )

        self.assertTrue(self.verify_phone().get("returning"))

        self.assertEqual(GuestProfile.objects.count(), 1)
        survivor = GuestProfile.objects.get()
        self.assertEqual(survivor.pk, older.pk)
        self.assertEqual(survivor.coupons.count(), 1)

    def test_the_higher_ladder_rung_survives_a_merge(self):
        from apps.rewards.models import RewardProgress

        older = self._profile(guest_id="older-account")
        newer = self._profile(guest_id="newer-account")
        RewardProgress.objects.create(profile=older, game_slug="chess-master", rung=1)
        RewardProgress.objects.create(profile=newer, game_slug="chess-master", rung=3)

        self.assertTrue(self.verify_phone().get("returning"))

        self.assertEqual(GuestProfile.objects.count(), 1)
        progress = RewardProgress.objects.get(profile_id=older.pk)
        self.assertEqual(progress.rung, 3)


class SignOutAffordanceTests(GuestQrFixtures):
    """The button has to be reachable, and it has to be a POST form."""

    def _signed_in(self):
        profile = GuestProfile.objects.create(
            guest_id="signed-in-guest",
            first_name="Reem",
            last_name="Khalid",
            phone=PHONE,
            phone_verified=True,
            first_brand=self.brand,
            first_outlet=self.outlet,
        )
        self.client.cookies[COOKIE] = identity.sign_guest_id(profile.guest_id)
        return profile

    def test_the_profile_page_offers_sign_out(self):
        self._signed_in()
        response = self.client.get(
            reverse("guest_profile_page", args=[self.qr.redirect_key])
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(reverse("guest_signout", args=[self.qr.redirect_key]), body)
        self.assertIn("Sign out", body)
        self.assertIn("Your coupons stay saved", body)
        self.assertIn('method="post"', body)

    def test_a_signed_out_guest_sees_no_sign_out_button(self):
        response = self.client.get(self.landing_url)
        self.assertNotIn(reverse("guest_signout", args=[self.qr.redirect_key]),
                         response.content.decode())


class CountryPickerTests(TestCase):
    """The picker supplies the dial code, so no country guessing is needed."""

    def test_the_uae_is_first_and_no_code_repeats(self):
        self.assertEqual(COUNTRIES[0][0], "971")
        dials = [dial for dial, _name, _iso in COUNTRIES]
        self.assertEqual(len(dials), len(set(dials)))

    def test_every_country_has_a_flag_file_on_disk(self):
        """A missing flag is a broken image in the sheet, not a test failure
        anywhere else, so it is checked here."""
        for dial, name, iso in COUNTRIES:
            path = f"img/flags/{iso}.png"
            self.assertIsNotNone(
                finders.find(path), msg=f"{name} ({dial}) has no flag at {path}"
            )

    def test_the_picker_rows_carry_what_search_needs(self):
        rows = picker_countries()
        self.assertEqual(len(rows), len(COUNTRIES))
        for row in rows:
            # the visible text is the dial code and nothing else
            self.assertTrue(row["dial"])
            self.assertTrue(row["iso"])
            # the haystack is what the search box matches against
            self.assertIn(row["dial"], row["search"])
            self.assertIn(row["iso"], row["search"])
            self.assertEqual(row["search"], row["search"].lower())
            # and the accessible name still says which country it is
            self.assertIn(f"+{row['dial']}", row["label"])

    def test_search_words_people_actually_type(self):
        """The English name alone is not enough: "uae" is not inside
        "United Arab Emirates", and nobody types "United States"."""
        by_dial = {row["dial"]: row["search"] for row in picker_countries()}
        self.assertIn("uae", by_dial["971"])
        self.assertIn("dubai", by_dial["971"])
        self.assertIn("india", by_dial["91"])
        self.assertIn("91", by_dial["91"])
        self.assertIn("uk", by_dial["44"])
        self.assertIn("usa", by_dial["1"])

    def test_country_plus_national_number_becomes_e164(self):
        self.assertEqual(normalise_with_country("971", "050 123 4567"), PHONE)
        self.assertEqual(normalise_with_country("971", "501234567"), PHONE)
        self.assertEqual(normalise_with_country("44", "07911 123456"), "+447911123456")
        self.assertEqual(normalise_with_country("91", "98765 43210"), "+919876543210")

    def test_a_pasted_full_number_wins_over_the_picker(self):
        self.assertEqual(
            normalise_with_country("971", "+44 7911 123456"), "+447911123456"
        )
        self.assertEqual(
            normalise_with_country("971", "00971501234567"), PHONE
        )

    def test_garbage_is_refused(self):
        for dial, phone in (("971", ""), ("971", "abc"), ("", "abc"), ("971", "0")):
            self.assertEqual(
                normalise_with_country(dial, phone), "", msg=repr((dial, phone))
            )


class OtpIssueTests(GuestQrFixtures):
    """Issuing and sending a code, and every limit that guards it."""

    def _age(self, row, minutes):
        PhoneOTP.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes)
        )

    def _old_row(self, phone=PHONE, minutes=5, **extra):
        # delivered=True is what the limits count. A row that never arrived
        # is kept for the panel, but it must not spend the guest's window.
        extra.setdefault("delivered", True)
        row = PhoneOTP.objects.create(
            phone=phone, code_hash="x", expires_at=timezone.now(), **extra
        )
        self._age(row, minutes)
        return row

    def test_the_digits_are_never_stored(self):
        outcome = otp.issue(PHONE)
        self.assertTrue(outcome.ok)
        self.assertRegex(outcome.debug_code, r"^\d{6}$")

        row = PhoneOTP.objects.get()
        self.assertNotIn(outcome.debug_code, row.code_hash)
        self.assertTrue(row.code_hash.startswith("pbkdf2_"))
        self.assertTrue(row.delivered)
        self.assertLessEqual(
            row.expires_at - timezone.now(), timedelta(minutes=5, seconds=2)
        )

    def test_a_second_send_inside_a_minute_is_refused_with_a_wait(self):
        otp.issue(PHONE)
        outcome = otp.issue(PHONE)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, otp.Reason.COOLDOWN)
        self.assertGreater(outcome.retry_after, 50)
        self.assertLessEqual(outcome.retry_after, 60)

    def test_three_codes_an_hour_then_a_fourth_is_refused(self):
        for minutes in (30, 20, 10):
            self._old_row(minutes=minutes)
        outcome = otp.issue(PHONE)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, otp.Reason.HOURLY_LIMIT)
        self.assertGreater(outcome.retry_after, 0)

    def test_ten_codes_a_day_then_a_wait(self):
        for hours in range(2, 12):
            self._old_row(minutes=hours * 60)
        outcome = otp.issue(PHONE)
        self.assertEqual(outcome.reason, otp.Reason.DAILY_LIMIT)

    def test_one_address_cannot_message_twelve_numbers(self):
        for n in range(12):
            self._old_row(phone=f"+9715000000{n:02d}", sent_ip="10.0.0.9")
        outcome = otp.issue("+971509999999", ip="10.0.0.9")
        self.assertEqual(outcome.reason, otp.Reason.IP_LIMIT)

    def test_a_failed_send_is_recorded_but_never_opens_a_code(self):
        """A refused send leaves a row for the panel and nothing to type.

        The row used to be deleted, which made "delivered" a column that was
        always true and hid how often WhatsApp refuses. It stays now, spent,
        so the six undelivered digits cannot be reused and the panel can show
        the failure.
        """
        with mock.patch.object(
            whatsapp, "send_otp", return_value=whatsapp.Delivery(False, "http_500")
        ):
            outcome = otp.issue(PHONE)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, otp.Reason.SEND_FAILED)

        row = PhoneOTP.objects.get()
        self.assertFalse(row.delivered)
        self.assertEqual(row.delivery_error, "http_500")
        self.assertIsNotNone(row.consumed_at)
        self.assertIsNone(row.verified_at)

    def test_a_failed_send_does_not_burn_the_guest_allowance(self):
        with mock.patch.object(
            whatsapp, "send_otp", return_value=whatsapp.Delivery(False, "network")
        ):
            otp.issue(PHONE)

        # No 60 second wait and no hourly slot spent: the guest may ask again
        # straight away, and three delivered codes still fit in the hour.
        retry = otp.issue(PHONE)
        self.assertTrue(retry.ok)
        self.assertEqual(retry.retry_after, 60)
        self.assertEqual(
            PhoneOTP.objects.filter(phone=PHONE, delivered=True).count(), 1
        )
        self.assertEqual(PhoneOTP.objects.filter(phone=PHONE).count(), 2)

    def test_verifying_stamps_verified_at(self):
        sent = otp.issue(PHONE)
        self.assertTrue(otp.verify(PHONE, sent.debug_code).ok)
        row = PhoneOTP.objects.get()
        self.assertIsNotNone(row.verified_at)
        self.assertIsNotNone(row.consumed_at)

    def test_a_replaced_code_is_consumed_but_not_verified(self):
        otp.issue(PHONE)
        first_row = PhoneOTP.objects.get(phone=PHONE)
        self._age(first_row, 2)
        otp.issue(PHONE)
        first_row.refresh_from_db()
        self.assertIsNotNone(first_row.consumed_at)
        self.assertIsNone(first_row.verified_at)

    def test_a_new_code_kills_the_old_one(self):
        first = otp.issue(PHONE)
        self._age(PhoneOTP.objects.get(), 2)
        second = otp.issue(PHONE)
        self.assertTrue(second.ok)
        self.assertNotEqual(first.debug_code, second.debug_code)
        # The replaced digits are no longer a working code. They are not
        # accepted silently and they do not open a second window: typing an
        # old code is just a wrong guess against the live one.
        stale = otp.verify(PHONE, first.debug_code)
        self.assertFalse(stale.ok)
        self.assertEqual(stale.reason, otp.Reason.WRONG)
        self.assertTrue(otp.verify(PHONE, second.debug_code).ok)


class OtpVerifyTests(GuestQrFixtures):
    """Checking a typed code: single use, five tries, five minutes."""

    def test_the_right_code_is_accepted_once(self):
        issued = otp.issue(PHONE)
        first = otp.verify(PHONE, issued.debug_code)
        self.assertTrue(first.ok)
        self.assertIsNotNone(PhoneOTP.objects.get().consumed_at)
        # replaying the same digits cannot open a second profile
        self.assertFalse(otp.verify(PHONE, issued.debug_code).ok)

    def test_wrong_digits_count_down_then_lock(self):
        issued = otp.issue(PHONE)
        wrong = "000000" if issued.debug_code != "000000" else "111111"
        for left in (4, 3, 2, 1):
            answer = otp.verify(PHONE, wrong)
            self.assertEqual(answer.reason, otp.Reason.WRONG)
            self.assertEqual(answer.attempts_left, left)
        locked = otp.verify(PHONE, wrong)
        self.assertEqual(locked.reason, otp.Reason.LOCKED)
        self.assertIsNotNone(PhoneOTP.objects.get().consumed_at)

    def test_a_code_dies_when_it_expires(self):
        issued = otp.issue(PHONE)
        PhoneOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(
            otp.verify(PHONE, issued.debug_code).reason, otp.Reason.EXPIRED
        )

    def test_a_number_that_never_asked_for_a_code_has_none(self):
        self.assertEqual(otp.verify(PHONE, "123456").reason, otp.Reason.NO_CODE)


class OtpHttpTests(GuestQrFixtures):
    """The two JSON endpoints the sheet calls."""

    def test_send_answers_the_code_in_debug_mode(self):
        response, data = self.send_code()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["phone"], PHONE)
        self.assertEqual(len(data["debug_code"]), 6)
        self.assertEqual(data["resend_after"], 60)

    def test_a_second_send_inside_the_minute_is_429(self):
        self.send_code()
        response, data = self.send_code()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(data["reason"], "cooldown")
        self.assertTrue(data["message"])
        self.assertGreater(data["retry_after"], 0)

    def test_a_bad_number_is_400_and_stores_nothing(self):
        response, data = self.send_code(phone="hello")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(data["ok"])
        self.assertEqual(PhoneOTP.objects.count(), 0)

    def test_check_accepts_the_code_and_leaves_a_session_proof(self):
        data = self.verify_phone()
        self.assertTrue(data["ok"])
        self.assertEqual(data["phone"], PHONE)
        self.assertEqual(self.client.session.get(otp.SESSION_KEY)["phone"], PHONE)

    def test_check_refuses_a_wrong_code_and_says_how_many_tries_are_left(self):
        _response, sent = self.send_code()
        wrong = "000000" if sent["debug_code"] != "000000" else "111111"
        response = self.client.post(
            reverse("guest_otp_check", args=[self.qr.redirect_key]),
            data={"country": "971", "phone": "050 123 4567", "code": wrong},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["reason"], "wrong")
        self.assertEqual(body["attempts_left"], 4)
        self.assertFalse(self.client.session.get(otp.SESSION_KEY))

    def test_unknown_qr_key_is_404(self):
        response = self.client.post(
            reverse("guest_otp_send", args=["no-such-key"]),
            data={"country": "971", "phone": "0501234567"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    @override_settings(
        WHATSAPP_OTP_DEBUG=False,
        WHATSAPP_ACCESS_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="",
    )
    def test_a_server_with_no_token_never_answers_the_code(self):
        """Fail closed, end to end.

        A missing token used to fall back to debug delivery, which would put
        the six digits straight into this JSON response. On a production
        server with an empty .env that made the whole check worthless: any
        visitor could "verify" any number. Nothing is sent now, so nothing
        can be verified, and the guest is asked to try again.
        """
        response, data = self.send_code()

        # 502, not 429: nothing was throttled, the provider refused. The
        # guest may try again at once, and the panel sees the failed attempt.
        self.assertEqual(response.status_code, 502)
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], "send_failed")
        self.assertNotIn("debug_code", data)
        # The number the guest typed may come back (the sheet shows it), but
        # the six digits never can.
        self.assertEqual(data["phone"], PHONE)
        self.assertTrue(data["message"])
        # A refused send must not burn the guest's allowance: the attempt is
        # logged for the panel, but nothing counts as delivered.
        self.assertEqual(PhoneOTP.objects.filter(phone=PHONE).count(), 1)
        self.assertFalse(PhoneOTP.objects.get(phone=PHONE).delivered)


class PhoneProofTests(GuestQrFixtures):
    """The session proof: one number, one submit, half an hour."""

    def _request(self):
        from django.test import RequestFactory

        request = RequestFactory().post("/")
        request.session = self.client.session
        return request

    def test_a_fresh_proof_matches_its_own_number_only(self):
        self.verify_phone()
        request = self._request()
        self.assertEqual(otp.proof_phone(request), PHONE)
        self.assertFalse(otp.consume(request, "+971509999999"))
        # a mismatch must not spend the proof for the real number
        self.assertTrue(otp.consume(request, PHONE))

    def test_a_proof_is_single_use(self):
        self.verify_phone()
        request = self._request()
        self.assertTrue(otp.consume(request, PHONE))
        self.assertFalse(otp.consume(request, PHONE))

    def test_a_stale_proof_is_dropped(self):
        self.verify_phone()
        request = self._request()
        session = request.session
        entry = dict(session[otp.SESSION_KEY])
        entry["at"] = (
            timezone.now() - timedelta(seconds=otp.PROOF_MAX_AGE_SECONDS + 60)
        ).isoformat()
        session[otp.SESSION_KEY] = entry
        session.save()
        self.assertEqual(otp.proof_phone(request), "")
        self.assertNotIn(otp.SESSION_KEY, session)


class WhatsAppDeliveryTests(TestCase):
    """The Cloud API call, without ever touching the network."""

    @override_settings(
        WHATSAPP_OTP_DEBUG=False,
        WHATSAPP_ACCESS_TOKEN="test-token",
        WHATSAPP_PHONE_NUMBER_ID="123456",
        WHATSAPP_API_VERSION="v25.0",
        WHATSAPP_OTP_TEMPLATE="pasons_otp",
        WHATSAPP_OTP_LANGUAGE="en",
    )
    def test_the_code_is_sent_in_the_body_and_the_copy_button(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"messages":[{"id":"wamid.X"}]}'

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.headers.get("Authorization")
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch(
            "apps.guests.whatsapp.urllib.request.urlopen", fake_urlopen
        ):
            result = whatsapp.send_otp(PHONE, "123456")

        self.assertTrue(result.ok)
        self.assertIn("/v25.0/123456/messages", captured["url"])
        self.assertEqual(captured["auth"], "Bearer test-token")
        self.assertEqual(captured["body"]["to"], "971501234567")
        template = captured["body"]["template"]
        self.assertEqual(template["name"], "pasons_otp")
        # body carries the digits, and so does the copy-code URL button
        self.assertEqual(
            template["components"][0]["parameters"][0]["text"], "123456"
        )
        self.assertEqual(template["components"][1]["sub_type"], "url")
        self.assertEqual(
            template["components"][1]["parameters"][0]["text"], "123456"
        )

    @override_settings(
        WHATSAPP_OTP_DEBUG=False,
        WHATSAPP_ACCESS_TOKEN="test-token",
        WHATSAPP_PHONE_NUMBER_ID="123456",
    )
    def test_a_refused_send_reports_a_code_not_the_api_message(self):
        def boom(request, timeout=None):
            raise urllib.error.HTTPError(
                "https://graph.facebook.com",
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"error":{"message":"internal detail"}}'),
            )

        with mock.patch("apps.guests.whatsapp.urllib.request.urlopen", boom):
            result = whatsapp.send_otp(PHONE, "123456")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "http_400")
        self.assertNotIn("internal detail", result.error)

    @override_settings(
        WHATSAPP_OTP_DEBUG=True,
        WHATSAPP_ACCESS_TOKEN="test-token",
        WHATSAPP_PHONE_NUMBER_ID="123456",
    )
    def test_debug_mode_never_touches_the_network(self):
        with mock.patch(
            "apps.guests.whatsapp.urllib.request.urlopen",
            side_effect=AssertionError("network used in debug mode"),
        ):
            result = whatsapp.send_otp(PHONE, "123456")
        self.assertTrue(result.ok)
        self.assertEqual(result.debug_code, "123456")

    @override_settings(
        WHATSAPP_OTP_DEBUG=False,
        WHATSAPP_ACCESS_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="",
    )
    def test_no_token_is_a_refusal_not_a_debug_delivery(self):
        """`not configured` must never behave like debug mode.

        The two were once the same branch, which is convenient on a fresh
        machine and dangerous everywhere else: debug delivery returns the
        code to the browser, so a server missing its token would hand out
        every code it generated.
        """
        with mock.patch(
            "apps.guests.whatsapp.urllib.request.urlopen",
            side_effect=AssertionError("network used without a token"),
        ):
            result = whatsapp.send_otp(PHONE, "123456")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "not_configured")
        self.assertEqual(result.debug_code, "")



# Claims as Google returns them for a normal personal account.
GOOD_CLAIMS = {
    "aud": "test-client-id.apps.googleusercontent.com",
    "iss": "https://accounts.google.com",
    "email": "aisha@example.com",
    "email_verified": "true",
    "sub": "109876543210",
    "given_name": "Aisha",
    "family_name": "Rahman",
}


class GoogleTokenVerificationTests(TestCase):
    """Verification rules, exercised without any network access."""

    def test_malformed_credential_never_leaves_the_box(self):
        # a JWT has exactly three segments; anything else is refused locally
        self.assertEqual(verify_id_token("nope", "client"), (None, "malformed"))
        self.assertEqual(verify_id_token("", "client"), (None, "malformed"))

    def test_no_client_id_means_not_configured(self):
        self.assertEqual(verify_id_token("a.b.c", ""), (None, "not_configured"))

    def test_claims_map_onto_profile_fields(self):
        fields = profile_fields_from_claims(GOOD_CLAIMS)
        self.assertEqual(fields["first_name"], "Aisha")
        self.assertEqual(fields["last_name"], "Rahman")
        self.assertEqual(fields["email"], "aisha@example.com")
        self.assertEqual(fields["google_sub"], "109876543210")

    def test_display_name_is_split_when_the_parts_are_missing(self):
        fields = profile_fields_from_claims(
            {"name": "Aisha Al Rahman", "email": "a@example.com", "sub": "1"}
        )
        self.assertEqual(fields["first_name"], "Aisha")
        self.assertEqual(fields["last_name"], "Al Rahman")


class GoogleSignInViewTests(GuestQrFixtures):
    """POST /q/<key>/identity/google/ -- fills the name from Google."""

    def _url(self):
        return reverse("guest_identity_google", args=[self.qr.redirect_key])

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)

    def test_unknown_key_is_404(self):
        response = self.client.post(
            reverse("guest_identity_google", args=["no-such-key"]),
            {"credential": "a.b.c"},
        )
        self.assertEqual(response.status_code, 404)

    def test_without_a_client_id_the_endpoint_refuses(self):
        response = self.client.post(self._url(), {"credential": "a.b.c"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_configured")

    @override_settings(GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    def test_a_junk_token_is_refused_and_writes_nothing(self):
        response = self.client.post(self._url(), {"credential": "a.b.c"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(GuestProfile.objects.count(), 0)

    @override_settings(GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    def test_wrong_audience_is_refused_even_when_the_token_is_valid(self):
        """A token minted for another site must never be accepted."""
        with mock.patch(
            "apps.guests.views.verify_id_token",
            return_value=(None, "wrong_audience"),
        ):
            response = self.client.post(self._url(), {"credential": "a.b.c"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "wrong_audience")
        self.assertEqual(GuestProfile.objects.count(), 0)

    @override_settings(GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    def test_a_valid_token_fills_the_name_and_email(self):
        with mock.patch(
            "apps.guests.views.verify_id_token", return_value=(GOOD_CLAIMS, "")
        ):
            response = self.client.post(self._url(), {"credential": "a.b.c"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["first_name"], "Aisha")

        profile = GuestProfile.objects.get()
        self.assertEqual(profile.first_name, "Aisha")
        self.assertEqual(profile.last_name, "Rahman")
        self.assertEqual(profile.email, "aisha@example.com")
        self.assertTrue(profile.email_verified)
        self.assertEqual(profile.google_sub, "109876543210")
        self.assertEqual(profile.first_brand, self.brand)
        self.assertIn(COOKIE, response.cookies)
        # Google never returns a mobile, so the flow still has to ask for one
        self.assertEqual(profile.phone, "")


class GoogleButtonRenderingTests(GuestQrFixtures):
    """No client id means no external script and no dead button."""

    def _landing(self):
        return self.client.get(self.landing_url).content.decode()

    def test_hidden_without_a_client_id(self):
        body = self._landing()
        self.assertNotIn("accounts.google.com/gsi/client", body)
        self.assertNotIn("g_id_signin", body)

    @override_settings(GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    def test_rendered_with_a_client_id(self):
        body = self._landing()
        self.assertIn("accounts.google.com/gsi/client", body)
        self.assertIn("g_id_signin", body)
        self.assertIn("test-client-id.apps.googleusercontent.com", body)
        self.assertIn("pqGoogleCredential", body)

    def test_endpoint_url_is_wired_into_the_sheet(self):
        url = reverse("guest_identity_google", args=[self.qr.redirect_key])
        self.assertIn(f'data-google-url="{url}"', self._landing())

    def test_the_ask_panel_still_offers_the_manual_route(self):
        """Google is a shortcut, never the only way in."""
        self.assertIn('name="first_name"', self._landing())


def _hours_open_all_day():
    return {
        day: {"open": "00:00", "close": "23:59", "closed": False}
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class PanelGuestContactTests(TestCase):
    """The panel contact list and the campaign CSV hand-off.

    The CSV is the file the client imports into their separate campaign
    platform, so these tests lock what makes a row usable: a mobile number,
    one row per number, and an honest consent column.
    """

    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Contacts", code="KINGCHEF-GC", status="active"
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-GC-INTL",
            slug="contacts-international-city",
            official_name="King Chef - International City",
            brand=cls.brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.head_office = User.objects.create_user(
            "ho-guests", password="pw-ho-12345"
        )
        cls.head_office.is_staff = True
        cls.head_office.save(update_fields=["is_staff"])

    def _profile(self, guest_id, **overrides):
        data = {
            "guest_id": guest_id,
            "first_brand": self.brand,
            "first_outlet": self.outlet,
        }
        data.update(overrides)
        return GuestProfile.objects.create(**data)

    def _export(self, user=None, **params):
        """Fetch the CSV. Logs in only when asked, so a scoped caller's own
        session is what the export is tested against."""
        if user is not None:
            self.client.force_login(user)
        response = self.client.get(reverse("panel_guests_export"), params)
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def test_the_contact_pages_need_a_staff_login(self):
        for name in ("panel_guests", "panel_guests_export"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/panel/login/", response["Location"])

    def test_head_office_sees_the_guests_we_can_act_on(self):
        self._profile("known-one", first_name="Aisha", phone="+971501110001")
        self._profile("anonymous-one")  # no name, no email, no number

        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_guests"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aisha")
        self.assertNotContains(response, "anonymous device")

    def test_every_contact_value_is_labelled_at_its_true_strength(self):
        """Unverified and self-declared are called out, because they are."""
        self._profile(
            "labelled-one",
            first_name="Omar",
            phone="+971501110002",
            email="omar@example.com",
            ig_follow_claimed=True,
        )
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_guests"))
        self.assertContains(response, "Unverified")
        self.assertContains(response, "Self-declared")
        self.assertNotContains(response, "Google verified")

    def test_a_google_confirmed_email_is_marked_verified(self):
        self._profile(
            "google-one",
            first_name="Noor",
            email="noor@example.com",
            email_verified=True,
        )
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_guests"))
        self.assertContains(response, "Google verified")

    def test_the_export_keeps_only_rows_the_campaign_can_message(self):
        self._profile("has-number", first_name="Aisha", phone="+971501110003")
        self._profile("no-number", first_name="Bilal", email="bilal@example.com")

        rows = self._export(self.head_office)
        self.assertEqual([row["Mobile"] for row in rows], ["+971501110003"])
        self.assertEqual(rows[0]["First name"], "Aisha")

    def test_the_export_counts_one_row_per_mobile_number(self):
        self._profile(
            "same-person-old",
            first_name="Old",
            phone="+971501110004",
        )
        self._profile(
            "same-person-new",
            first_name="Newest",
            phone="+971501110004",
        )

        rows = self._export(self.head_office)
        self.assertEqual(len(rows), 1)
        # the newest profile wins, because it holds the latest state
        self.assertEqual(rows[0]["First name"], "Newest")

    def test_the_export_carries_consent_and_can_narrow_to_consented(self):
        self._profile(
            "consented-one", first_name="Consented", phone="+971501110005",
            consent_marketing=True,
        )
        self._profile(
            "silent-one", first_name="Silent", phone="+971501110006",
        )

        rows = self._export(self.head_office)
        consent = {row["First name"]: row["Marketing consent"] for row in rows}
        self.assertEqual(consent, {"Consented": "yes", "Silent": "no"})

        narrowed = self._export(self.head_office, consented=1)
        self.assertEqual([row["First name"] for row in narrowed], ["Consented"])

    def test_the_export_names_its_columns_once(self):
        self._profile("column-one", first_name="Aisha", phone="+971501110007")
        rows = self._export(self.head_office)
        expected = [label for _key, label in panel_views.EXPORT_COLUMNS]
        self.assertEqual(list(rows[0].keys()), expected)

    def test_a_brand_manager_only_sees_their_own_brand(self):
        from apps.core.panel_permissions import apply_role_to_user

        other_brand = Brand.objects.create(
            name_en="Other Contacts", code="OTHER-GC", status="active"
        )
        other_outlet = Outlet.objects.create(
            code="OTHER-GC-1",
            slug="other-contacts-branch",
            official_name="Other Branch",
            brand=other_brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        self._profile("mine", first_name="Mine", phone="+971501110008")
        self._profile(
            "theirs", first_name="Theirs", phone="+971501110009",
            first_brand=other_brand, first_outlet=other_outlet,
        )

        manager = User.objects.create_user("brand-guests", password="pw-br-12345")
        apply_role_to_user(manager, "brand_manager", self.brand, [])
        self.client.force_login(manager)

        response = self.client.get(reverse("panel_guests"))
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

        # the export must honour the same brand scope, not leak the group list
        rows = self._export()
        self.assertEqual([row["First name"] for row in rows], ["Mine"])

    def test_a_branch_manager_has_no_export_of_personal_data(self):
        """A shop-floor role must not walk away with the contact list.

        Guest contacts are marketing data. The brand owns them; an individual
        branch manager is refused, and this test is the guard so a later
        capability change has to be a conscious decision.
        """
        from apps.core.panel_permissions import apply_role_to_user

        self._profile("branch-person", first_name="Branch", phone="+971501110010")
        manager = User.objects.create_user("branch-guests", password="pw-br-12345")
        apply_role_to_user(manager, "outlet_manager", None, [self.outlet])
        self.client.force_login(manager)

        self.assertEqual(self.client.get(reverse("panel_guests")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("panel_guests_export")).status_code, 403
        )


# --------------------------------------------------------------------------
# WhatsApp code report (/panel/verification/)
# --------------------------------------------------------------------------
def _report_now():
    """A fixed local midday, so a window test never depends on the clock."""
    return timezone.make_aware(
        datetime(2026, 10, 19, 12, 0), timezone.get_current_timezone()
    )


class OtpReportFixtures(GuestQrFixtures):
    """A second brand and branch, the three staff roles, dated codes."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_brand = Brand.objects.create(
            name_en="Milan Report", code="MILAN-REPORT", status="active"
        )
        cls.other_outlet = Outlet.objects.create(
            code="MILAN-REPORT-1",
            slug="milan-report-branch",
            official_name="Milan Report - Karama",
            brand=cls.other_brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )

    def make_code(
        self,
        phone="+971501234567",
        when=None,
        delivered=True,
        verified=False,
        outlet="default",
        brand="default",
    ):
        """One PhoneOTP row, dated to `when` so the windows are testable."""
        when = when or timezone.now()
        row = PhoneOTP.objects.create(
            phone=phone,
            code_hash="x",
            expires_at=when + timedelta(minutes=5),
            delivered=delivered,
            verified_at=when if verified else None,
            brand=self.brand if brand == "default" else brand,
            outlet=self.outlet if outlet == "default" else outlet,
        )
        PhoneOTP.objects.filter(pk=row.pk).update(created_at=when, updated_at=when)
        row.refresh_from_db()
        return row

    def head_office(self, name="ho-report"):
        user = User.objects.create_user(name, password="pw-ho-123456")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        return user

    def brand_manager(self, brand=None, name="bm-report"):
        from apps.core.panel_permissions import apply_role_to_user

        user = User.objects.create_user(name, password="pw-bm-123456")
        apply_role_to_user(user, "brand_manager", brand or self.brand, [])
        return user

    def branch_manager(self, outlets=None, name="br-report"):
        from apps.core.panel_permissions import apply_role_to_user

        user = User.objects.create_user(name, password="pw-br-123456")
        apply_role_to_user(user, "outlet_manager", None, outlets or [self.outlet])
        return user


class OtpWindowTests(OtpReportFixtures):
    """The six windows the client named, and what belongs in each."""

    def setUp(self):
        self.now = _report_now()
        self.w = {row["key"]: row for row in reporting.periods(now=self.now)}
        self.make_code(when=self.w["today"]["start"] + timedelta(hours=1))
        self.make_code(
            phone="+971500000002",
            when=self.w["yesterday"]["start"] + timedelta(hours=1),
        )
        self.make_code(
            phone="+971500000003",
            when=self.w["week"]["start"] + timedelta(hours=1),
        )
        self.make_code(
            phone="+971500000004",
            when=self.w["last_month"]["start"] + timedelta(hours=1),
        )

    def _rows(self):
        return {
            row["key"]: row
            for row in reporting.period_rows(PhoneOTP.objects.all(), now=self.now)
        }

    def test_the_six_windows_the_client_named(self):
        labels = [row["label"] for row in reporting.periods(now=self.now)]
        self.assertEqual(
            labels,
            [
                "Today",
                "Yesterday",
                "Last 7 days",
                "Last 30 days",
                "This month",
                "Last month",
            ],
        )

    def test_today_starts_where_yesterday_ends(self):
        rows = reporting.periods(now=self.now)
        self.assertEqual(rows[0]["start"], rows[1]["end"])
        # The 7 day window is today plus the six days before it, so it opens
        # five days before yesterday opens.
        self.assertEqual(rows[1]["start"], rows[2]["start"] + timedelta(days=5))

    def test_each_window_counts_only_its_own_days(self):
        rows = self._rows()
        self.assertEqual(rows["today"]["sent"], 1)
        self.assertEqual(rows["yesterday"]["sent"], 1)
        # Today, yesterday and the code placed on the first day of the window.
        self.assertEqual(rows["week"]["sent"], 3)
        self.assertEqual(rows["month30"]["sent"], 3)
        self.assertEqual(rows["this_month"]["sent"], 3)
        self.assertEqual(rows["last_month"]["sent"], 1)

    def test_a_window_carries_the_dates_it_covers(self):
        today = self._rows()["today"]
        self.assertEqual(today["range"], "19 Oct 2026")

    def test_sent_delivered_and_verified_are_three_different_numbers(self):
        PhoneOTP.objects.all().delete()
        when = self.w["month30"]["start"] + timedelta(hours=2)
        self.make_code(phone="+971500000011", when=when, delivered=True, verified=True)
        self.make_code(phone="+971500000012", when=when, delivered=True)
        self.make_code(phone="+971500000013", when=when, delivered=False)

        row = self._rows()["month30"]
        self.assertEqual(row["sent"], 3)
        self.assertEqual(row["delivered"], 2)
        self.assertEqual(row["verified"], 1)
        self.assertEqual(row["guests"], 3)
        self.assertEqual(row["delivery_pct"], 67)
        self.assertEqual(row["verified_pct"], 50)

    def test_the_month_trend_is_zero_filled_and_ends_on_this_month(self):
        trend = reporting.monthly_trend(PhoneOTP.objects.all(), now=self.now)
        self.assertEqual(len(trend), 6)
        self.assertEqual(trend[-1]["label"], "Oct")
        self.assertEqual([m["sent"] for m in trend[:4]], [0, 0, 0, 0])
        self.assertEqual(trend[-1]["sent"], 3)
        self.assertEqual(trend[-1]["failed"], 0)

    def test_the_trend_keeps_the_refused_slice(self):
        PhoneOTP.objects.all().delete()
        when = self.w["today"]["start"] + timedelta(hours=1)
        self.make_code(phone="+971500000021", when=when, delivered=True)
        self.make_code(phone="+971500000022", when=when, delivered=False)
        month = reporting.monthly_trend(PhoneOTP.objects.all(), now=self.now)[-1]
        self.assertEqual((month["sent"], month["delivered"], month["failed"]), (2, 1, 1))
        self.assertEqual(month["pct"], 100)


class OtpReportScopeTests(OtpReportFixtures):
    """Who may see which branch's codes."""

    def test_a_branch_manager_sees_only_their_branch(self):
        self.make_code(phone="+971500000031")
        self.make_code(
            phone="+971500000032",
            outlet=self.other_outlet,
            brand=self.other_brand,
        )
        self.client.force_login(self.branch_manager())

        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "King Chef - International City")
        self.assertNotContains(response, "Milan Report - Karama")

    def test_a_brand_manager_sees_their_brand_page_codes(self):
        self.make_code(phone="+971500000033", outlet=None)
        self.make_code(
            phone="+971500000034",
            outlet=self.other_outlet,
            brand=self.other_brand,
        )
        self.client.force_login(self.brand_manager())

        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "Brand page")
        self.assertNotContains(response, "Milan Report")

    def test_head_office_sees_rows_written_before_branch_recording(self):
        self.make_code(phone="+971500000035", brand=None, outlet=None)
        self.client.force_login(self.head_office())

        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "Before recording")
        self.assertContains(response, "+971500000035")

    def test_a_manager_never_sees_unrecorded_rows(self):
        self.make_code(phone="+971500000036", brand=None, outlet=None)
        self.client.force_login(self.branch_manager())

        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "No codes yet")

    def test_the_branch_filter_cannot_reach_another_branch(self):
        self.make_code(phone="+971500000037")
        self.client.force_login(self.branch_manager())

        response = self.client.get(
            reverse("panel_otp"), {"branch": self.other_outlet.pk}
        )
        self.assertEqual(response.status_code, 200)
        # The out-of-scope id is ignored, so the manager still sees their own
        # branch rather than an empty page or the other brand's numbers.
        self.assertContains(response, "+971500000037")

    def test_head_office_can_narrow_to_one_branch(self):
        self.make_code(phone="+971500000038")
        self.make_code(
            phone="+971500000039",
            outlet=self.other_outlet,
            brand=self.other_brand,
        )
        self.client.force_login(self.head_office())

        response = self.client.get(
            reverse("panel_otp"), {"branch": self.other_outlet.pk}
        )
        self.assertContains(response, "+971500000039")
        self.assertNotContains(response, "+971500000038")


class OtpAttributionTests(OtpReportFixtures):
    """A send carries the branch of the QR page it was asked on."""

    def test_a_send_is_attributed_to_the_qr_page_branch(self):
        _response, data = self.send_code()
        self.assertTrue(data["ok"])
        row = PhoneOTP.objects.get()
        self.assertEqual(row.brand, self.brand)
        self.assertEqual(row.outlet, self.outlet)

    def test_a_verified_code_is_stamped_verified_at(self):
        self.verify_phone()
        row = PhoneOTP.objects.get()
        self.assertIsNotNone(row.verified_at)
        self.assertEqual(row.verified_at, row.consumed_at)

    def test_a_failed_send_is_attributed_too(self):
        with mock.patch.object(
            whatsapp, "send_otp", return_value=whatsapp.Delivery(False, "http_500")
        ):
            self.send_code()
        row = PhoneOTP.objects.get()
        self.assertFalse(row.delivered)
        self.assertEqual(row.outlet, self.outlet)


class OtpReportPageTests(OtpReportFixtures):
    """The page itself: gate, layout contract, search, and no money."""

    def test_the_page_requires_sign_in(self):
        response = self.client.get(reverse("panel_otp"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/panel/login/", response["Location"])

    def test_a_user_with_no_role_is_refused(self):
        user = User.objects.create_user("no-role-report", password="pw-no-123456")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("panel_otp")).status_code, 403)

    def test_the_page_renders_the_windows_and_the_guest_list(self):
        self.verify_phone()
        self.client.force_login(self.brand_manager())

        response = self.client.get(reverse("panel_otp"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The six windows")
        self.assertContains(response, "By branch")
        self.assertContains(response, "Guests who asked for a code")
        self.assertContains(response, "+971501234567")
        self.assertContains(response, "Verified")

    def test_the_page_prints_no_money_figure(self):
        """The client chose counts only. A guessed rate is worse than none."""
        self.verify_phone()
        self.client.force_login(self.head_office())
        body = self.client.get(reverse("panel_otp")).content.decode()

        for token in ("$", "USD", "AED", "AED ", "per message", "cost", "price", "invoice"):
            self.assertNotIn(token, body, msg=f"{token!r} must not appear on the page")

    def test_the_guest_name_is_joined_by_mobile_number(self):
        profile = GuestProfile.objects.create(
            guest_id="report-guest",
            first_name="Layla",
            last_name="Noor",
            phone="+971501234567",
            phone_verified=True,
            first_brand=self.brand,
            first_outlet=self.outlet,
        )
        self.make_code(phone=profile.phone, verified=True)
        self.client.force_login(self.brand_manager())

        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "Layla")
        self.assertContains(response, "Noor")

    def test_search_finds_a_guest_by_name_and_by_number(self):
        GuestProfile.objects.create(
            guest_id="search-guest",
            first_name="Mariam",
            last_name="Haddad",
            phone="+971507778888",
            first_brand=self.brand,
            first_outlet=self.outlet,
        )
        self.make_code(phone="+971507778888")
        self.client.force_login(self.head_office())

        by_name = self.client.get(reverse("panel_otp"), {"q": "mariam"})
        self.assertContains(by_name, "+971507778888")

        by_number = self.client.get(reverse("panel_otp"), {"q": "0507778888"})
        self.assertContains(by_number, "+971507778888")

    def test_a_search_with_no_match_shows_the_empty_state(self):
        self.make_code(phone="+971500000041")
        self.client.force_login(self.head_office())
        response = self.client.get(reverse("panel_otp"), {"q": "zzzz"})
        self.assertContains(response, "No codes yet")

    def test_the_destination_uses_a_flag_and_a_dial_code(self):
        self.make_code(phone="+919876543210")
        self.client.force_login(self.head_office())
        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "+91")
        self.assertContains(response, "flags/in.png")

    def test_the_nav_link_is_visible_to_managers(self):
        self.client.force_login(self.branch_manager())
        response = self.client.get(reverse("panel_dashboard"))
        self.assertContains(response, reverse("panel_otp"))
        self.assertContains(response, "Verification")

    def test_an_empty_report_still_renders(self):
        self.client.force_login(self.head_office())
        response = self.client.get(reverse("panel_otp"))
        self.assertContains(response, "No codes yet")
        self.assertEqual(response.status_code, 200)
