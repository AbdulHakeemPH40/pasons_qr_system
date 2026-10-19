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
  * The mobile number is checked by a WhatsApp one time code before it is
    stored as verified (2026-10-19). The digits themselves never sit in the
    database: PhoneOTP keeps a salted hash, a 5 minute expiry and an attempt
    counter, matching the lifetime the guest is told on their phone.
  * One mobile number may appear on more than one profile (same person, new
    phone or cleared cookies), so the number is indexed, not unique, and
    exports dedupe by number.
"""

from datetime import date, timedelta

from django.db import models
from django.utils import timezone

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
        help_text="True only after the guest entered the code sent to this number",
    )
    phone_changed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the guest last updated their mobile number on the profile page",
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

        Since 2026-10-19 the number IS checked: every write goes through a
        WhatsApp code (apps.guests.otp), so "verified" here means the guest
        proved the number, not merely typed it. `phone_verified` records that
        proof for the number column on its own.
        """
        if self.google_sub or self.email_verified:
            return True
        return bool(self.first_name and self.last_name and self.phone)

    def can_change_phone(self, now=None):
        """A guest may change their mobile number at most once per calendar month.

        The lock starts at the FIRST number captured, not at the first
        replacement. Every write of a number stamps `phone_changed_at` (see
        apps.guests.views), so one account cannot hold two different numbers
        in the same month by capturing one and then changing it, and the
        sign-in sheet cannot be used to get around the profile page. Keeping
        the same number never spends the allowance.
        """
        if not self.phone or not self.phone_changed_at:
            return True
        now = now or timezone.now()
        local_now = timezone.localtime(now)
        local_changed = timezone.localtime(self.phone_changed_at)
        return (local_now.year, local_now.month) != (
            local_changed.year,
            local_changed.month,
        )

    def next_phone_change_date(self, now=None):
        """First day of next calendar month when the phone lock is active."""
        if self.can_change_phone(now=now):
            return None
        now = now or timezone.now()
        local_now = timezone.localtime(now)
        if local_now.month == 12:
            return date(local_now.year + 1, 1, 1)
        return date(local_now.year, local_now.month + 1, 1)


class PhoneOTP(TimeStampedModel):
    """One WhatsApp one time code sent to one mobile number.

    Why a table and not just a column on the profile: the code has to survive
    a page reload, it has a lifetime, it can be guessed five times before it
    dies, and every send is rate limited. Those are four pieces of state, and
    the profile is the wrong place for any of them.

    The digits are NEVER stored. `code_hash` is a salted Django password hash
    (PBKDF2), compared in constant time. A copy of this table is worth
    nothing: six digits behind a slow hash, plus a five minute window.

    `consumed_at` is the single-use marker. A resend marks the older rows
    consumed, so only the newest code can ever be accepted. That is what stops
    a guest from keeping an old working code after asking for a new one.

    `verified_at` answers a different question: was this code actually typed
    correctly? A resend also sets `consumed_at`, so that column alone cannot
    tell a win from a replacement, and the panel would over-report.
    """

    class Purpose(models.TextChoices):
        VERIFY = "verify", "Verify a mobile number"

    phone = models.CharField(
        max_length=24,
        db_index=True,
        help_text="E.164, the number the code was sent to",
    )
    purpose = models.CharField(
        max_length=16,
        choices=Purpose.choices,
        default=Purpose.VERIFY,
    )
    code_hash = models.CharField(
        max_length=128,
        help_text="Salted hash of the 6 digits; the code itself is never stored",
    )
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text="Wrong guesses so far; the code dies at the limit",
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the code was used, replaced by a resend, or refused",
    )
    delivered = models.BooleanField(
        default=False,
        help_text=(
            "True when WhatsApp accepted the message. A failed attempt is "
            "kept with False so the panel can show it, but it is excluded "
            "from the rate limits: a message the guest never received must "
            "not spend their allowance."
        ),
    )
    delivery_error = models.CharField(
        max_length=120,
        blank=True,
        help_text="Short reason from the delivery attempt, never the token",
    )
    sent_ip = models.GenericIPAddressField(null=True, blank=True)

    # --- where the guest was standing when they asked for the code ---
    #
    # The sheet is only ever opened from a shop QR page, so the brand and the
    # branch are known at send time. Storing them is what lets the panel say
    # "King Chef, Al Quoz sent 41 codes this week" instead of one flat total
    # nobody can act on. SET_NULL, not CASCADE: deleting a branch must not
    # erase the record of messages the client was billed for.
    #
    # Rows written before this column existed have no branch. They are shown
    # as "Not recorded" rather than guessed from the guest's later profile,
    # because a guess would move a real count to the wrong branch.
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="otp_codes",
        help_text="Brand of the QR page the guest asked on",
    )
    outlet = models.ForeignKey(
        Outlet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="otp_codes",
        help_text="Branch of that QR page; empty for a brand-level page",
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Set only when the guest typed the code correctly. `consumed_at` "
            "alone cannot say this, because a resend also consumes a code."
        ),
    )

    class Meta:
        verbose_name = "Phone verification code"
        verbose_name_plural = "Phone verification codes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone", "-created_at"]),
            models.Index(fields=["phone", "consumed_at"]),
            # The panel reads every report by date, scoped by branch.
            models.Index(fields=["-created_at"]),
            models.Index(fields=["outlet", "-created_at"]),
            models.Index(fields=["brand", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.phone} issued {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def is_spent(self):
        return self.consumed_at is not None

    def is_expired(self, now=None):
        return self.expires_at <= (now or timezone.now())

    def attempts_left(self, limit):
        return max(0, limit - self.attempts)

    def spend(self, now=None):
        """Mark the code unusable, without a full save."""
        self.consumed_at = now or timezone.now()
        self.save(update_fields=["consumed_at", "updated_at"])

    @classmethod
    def ttl(cls):
        """The lifetime the guest is told on their phone. Keep the two equal."""
        return timedelta(minutes=5)


