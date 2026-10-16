"""
Guest identity -- one row per anonymous device, upgraded in place when the
guest chooses to give a name, an email (Google) or a mobile number.

Why this exists (plan 2026-10-16): the platform must collect guest identity
and interaction data so the client's separate campaign platform can message
those guests later. Nothing here sends anything; this app only recognises a
returning guest and stores what they told us.

The identity ladder:

    guest_id cookie (anonymous)  ->  name / last name / mobile  ->  known guest
    Google sign-in (email)       ->  pre-fills the name, proves the email

Rules that matter:

  * No password, no login wall, no auth.User row. A guest is NOT a staff
    account; keeping guest identity out of django.contrib.auth means guest
    traffic can never collide with a panel session.
  * The cookie is SIGNED (apps.guests.identity). A guessable id would let
    one guest read another guest's coupons, so the raw value never leaves
    the server trusted.
  * The mobile number is stored UNVERIFIED (client decision 2026-10-16: no
    OTP). The panel labels it that way. phone_verified exists so a later
    WhatsApp OTP can flip it without a schema change.
  * One mobile number may appear on more than one profile (same person, new
    phone or cleared cookies), so the number is indexed, not unique, and
    exports dedupe by number.
"""

from django.db import models

from apps.core.models import Brand, Outlet, TimeStampedModel


class GuestProfile(TimeStampedModel):
    """Anonymous device identity, upgraded with what the guest tells us."""

    guest_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Opaque token stored in the signed pq_guest cookie",
    )

    # --- identity, filled by the form or by Google ---
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    email_verified = models.BooleanField(
        default=False,
        help_text="True only when Google confirmed the address",
    )
    google_sub = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Google account subject id (stable per Google account)",
    )
    phone = models.CharField(
        max_length=24,
        blank=True,
        db_index=True,
        help_text="E.164, e.g. +971501234567. Indexed, not unique: exports dedupe",
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="False today (no OTP step); ready for a later WhatsApp code",
    )

    # --- Instagram follow claim (self-declared: Meta exposes no follow check) ---
    ig_follow_claimed = models.BooleanField(default=False)
    ig_claimed_at = models.DateTimeField(null=True, blank=True)

    # --- consent (UAE PDPL: name and phone are personal data) ---
    consent_marketing = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)

    # --- where the guest first arrived, for campaign segmentation ---
    first_brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guest_profiles",
    )
    first_outlet = models.ForeignKey(
        Outlet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guest_profiles",
    )

    class Meta:
        verbose_name = "Guest Profile"
        verbose_name_plural = "Guest Profiles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["phone", "-created_at"]),
        ]

    def __str__(self):
        return self.full_name or (self.phone or self.guest_id[:8])

    @property
    def full_name(self):
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()

    @property
    def is_identified(self):
        """True once we can act on this guest (a name, an email or a phone)."""
        return bool(self.phone or self.email or self.full_name)

    @property
    def is_verified(self):
        """True when this guest can be PAID a reward.

        Two routes, exactly as the client asked (2026-10-16):

          * first name AND last name AND a mobile number, or
          * Google sign-in.

        `is_identified` is the weaker question ("can we act on this guest?")
        and stays as it is. This one is the gate on rewards only. Playing
        never needs it: a guest who is not verified plays every game at every
        level with no restriction, they simply do not earn anything.

        The mobile number is not OTP-checked (client decision, no OTP), so
        "verified" here means "told us a name and a number we can message",
        not "proved the number is theirs". The panel labels it that way.
        """
        if self.google_sub or self.email_verified:
            return True
        return bool(self.first_name and self.last_name and self.phone)
