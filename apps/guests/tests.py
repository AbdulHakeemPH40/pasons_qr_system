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
from unittest import mock

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage

from . import identity, panel_views
from .google import profile_fields_from_claims, verify_id_token
from .middleware import GuestIdentityMiddleware
from .models import GuestProfile
from .phone import normalise_phone

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


class AnonymousBrowseWritesNothingTests(GuestQrFixtures):
    """The most important cost guarantee: browsing must not create rows."""

    def test_landing_page_creates_no_profile_and_sets_no_cookie(self):
        response = self.client.get(reverse("qr_landing", args=[self.qr.redirect_key]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GuestProfile.objects.count(), 0)
        self.assertNotIn(COOKIE, response.cookies)


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
        self.assertIn("It must match when you redeem your coupon", body)
        self.assertIn("make sure it is correct before you submit", body)
        # The note sits under the mobile field, not somewhere else on the page.
        phone_at = body.index('name="phone"')
        note_at = body.index("It must match when you redeem your coupon")
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


class IdentitySubmitTests(GuestQrFixtures):
    """POST /q/<key>/identity/ -- the single write in the guest flow."""

    def _post(self, **overrides):
        payload = {
            "first_name": "Aisha",
            "last_name": "Rahman",
            "phone": "050 123 4567",
            "consent": "1",
            "next": self.landing_url,
        }
        payload.update(overrides)
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
        self.assertFalse(profile.phone_verified)
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
