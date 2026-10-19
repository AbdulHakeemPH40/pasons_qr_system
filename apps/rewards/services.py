"""
The reward engine.

One entry point, `evaluate_round`, answers a single question: did this
finished round EARN something? Everything that limits abuse is decided here,
so there is exactly one place to audit.

The client's rule (2026-10-16) is "pay for a climb, not for a score". Merely
playing never pays, in any game. Four earning modes live in the games
registry (apps/games/registry.py, Game.earn):

  "none"       pure play. 2048 is entertainment and pays nothing at all, no
               coupon and no dessert.
  "ladder"     Chess Master. Four levels that must be won in order. Level 1
               and Level 2 pay NOTHING: they are the cost of entry. A Level 3
               win pays the free dessert, a Level 4 win pays the 10% discount.
  "streak"     Memory Match. A free dessert and never a coupon, and only after
               five qualifying rounds inside seven days.
  "threshold"  Flappy Burger. A free dessert and never a coupon, when one
               real round clears 25 pipes. One dessert per mobile per month
               is what keeps this from being easy.

Every claim then passes these gates, in order, first refusal wins:

  1. there is a profile at all
  2. the brand has not been switched off
  3. the round was really played (the per-game effort floor)
  4. that game's earning rule is satisfied
  5. the guest is VERIFIED (first name, last name and mobile, or Google).
     Playing stays open to everyone at every level; being verified is the
     gate on being PAID, never on playing.
  6. the guest has not already taken THIS kind of prize this calendar month
     (one dessert and one discount, counted apart, keyed on the mobile)
  7. the brand has not hit its monthly cap

Scores, durations and action counts all arrive from the browser and a
determined guest can fake any of them. Nothing here is proof of a real win,
and it should never be described to the client as one. What it buys is
EFFORT: a bot has to play a round of real length, climb the chess ladder rung
by rung, repeat genuine rounds over days, and hand over a name and a mobile
number to be paid. The real defence is the cooldown keyed on the MOBILE
NUMBER (clearing cookies does not start a fresh allowance) plus the monthly
cap; the signed round token only raises the effort further.
"""

import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.games.registry import get_game

from .models import (
    BrandRewardSettings,
    RewardCoupon,
    RewardProgress,
    RewardRound,
    RewardRule,
    RewardTier,
    RewardType,
    RoundResult,
    allowance_period,
    coupon_label,
)

# Staff read these codes off a phone screen, so the alphabet drops the
# characters that get misread: 0/O and 1/I/L.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6

DEFAULT_COOLDOWN_DAYS = 7
DEFAULT_VALID_DAYS = 14

# What each tier pays when only the registry defaults are in play. HIGH pays
# the discount; GOOD pays the dessert.
DEFAULT_REWARD_TYPE = {
    RewardTier.GOOD.value: RewardType.DESSERT,
    RewardTier.HIGH.value: RewardType.PERCENT,
}
DEFAULT_PERCENT = {RewardTier.HIGH.value: 10}

# --- round tokens ----------------------------------------------------------
_TOKEN_SALT = "pasons.reward.round"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 3
# A round cannot be finished faster than this. It is a floor, not proof: a
# genuine fast win is far slower, while an instant scripted beacon is not.
MIN_ROUND_SECONDS = 5


# --- why a claim paid, or did not -----------------------------------------
# Codes are stable strings: the shell maps them to wording, the tests assert
# on them, and the panel can group by them.
class Reason:
    ISSUED = "issued"
    PURE_PLAY = "pure_play"
    NO_PROFILE = "no_profile"
    TOKEN = "token"
    BRAND_OFF = "brand_off"
    EFFORT = "effort"
    LOCKED = "locked"
    NOT_A_WIN = "not_a_win"
    RUNG_FREE = "rung_free"
    LOW_SCORE = "low_score"
    NOT_YET = "not_yet"
    NOT_VERIFIED = "not_verified"
    COOLDOWN = "cooldown"
    CAP = "cap"


# Guest-facing wording, kept in one place so the panel, the tests and the
# game-over card cannot drift apart. Plain English, no emoji.
REASON_TEXT = {
    Reason.ISSUED: "Reward issued.",
    Reason.PURE_PLAY: "This game is just for fun. It does not give rewards.",
    Reason.NO_PROFILE: "No guest profile on this device.",
    Reason.TOKEN: "That round could not be confirmed. Play again.",
    Reason.BRAND_OFF: "Rewards are switched off at this restaurant.",
    Reason.EFFORT: "That round was too short to count for a reward. Play a longer one.",
    Reason.LOCKED: "Win the level you are on to unlock the next one.",
    Reason.NOT_A_WIN: "Only a win climbs the levels. Try again.",
    Reason.RUNG_FREE: "Level {level} does not pay a reward. Keep climbing.",
    Reason.LOW_SCORE: "Not a scoring round this time. Try again.",
    Reason.NOT_YET: "Keep playing. A run of good rounds is what counts.",
    Reason.NOT_VERIFIED: "Add your name and mobile, or use Google, to claim.",
    Reason.COOLDOWN: "You already have this reward this month.",
    Reason.CAP: "This month's rewards are all taken at this restaurant.",
}


@dataclass(frozen=True)
class Rule:
    """Either a RewardRule row or a registry default, in one shape."""

    tier: str
    min_score: int
    reward_type: str
    percent: int
    cooldown_days: int
    valid_days: int

    @property
    def label(self):
        return coupon_label(self.reward_type, self.percent)


@dataclass
class ClaimOutcome:
    """What the engine decided, in a shape the view can turn into JSON."""

    coupon: object = None
    reason: str = ""
    message: str = ""
    progress: dict = field(default_factory=dict)

    @property
    def issued(self):
        return self.coupon is not None


def _rule_from_row(row):
    return Rule(
        tier=row.tier,
        min_score=row.min_score,
        reward_type=row.reward_type,
        percent=row.percent,
        cooldown_days=row.cooldown_days,
        valid_days=row.valid_days,
    )


def effective_rules(game_slug):
    """Rules for a game, HIGH first.

    Merged PER TIER, not all-or-nothing: a RewardRule row overrides the
    registry default for the SAME tier (and a row with active=False switches
    that tier off entirely), while a tier with no row keeps its registry
    default. So staff can retune the discount line without losing the
    dessert line, and the engine still works on a fresh database.
    """
    by_tier = {}

    game = get_game(game_slug)
    for tier in (RewardTier.HIGH, RewardTier.GOOD):
        line = (getattr(game, "reward", None) or {}).get(tier.value)
        if not line:
            continue
        by_tier[tier.value] = Rule(
            tier=tier.value,
            min_score=int(line),
            reward_type=DEFAULT_REWARD_TYPE[tier.value],
            percent=DEFAULT_PERCENT.get(tier.value, 0),
            cooldown_days=DEFAULT_COOLDOWN_DAYS,
            valid_days=DEFAULT_VALID_DAYS,
        )

    for row in RewardRule.objects.filter(game_slug=game_slug):
        if not row.active:
            by_tier.pop(row.tier, None)
            continue
        by_tier[row.tier] = _rule_from_row(row)

    return sorted(by_tier.values(), key=lambda r: (-r.min_score, r.tier))


def rule_for_tier(game_slug, tier):
    """The one rule for (game, tier), or None when that tier pays nothing."""
    for rule in effective_rules(game_slug):
        if rule.tier == tier:
            return rule
    return None


def prize_label(game_slug, tier):
    """What that tier pays, as words. Empty when the tier pays nothing."""
    rule = rule_for_tier(game_slug, tier)
    return rule.label if rule else ""


def earn_config(game_slug):
    """How this game pays, straight from the registry. `{}` when unknown."""
    game = get_game(game_slug)
    return dict(getattr(game, "earn", None) or {})


def effort_floor(game_slug):
    """What a real round of this game looks like. (0, 0) when unspecified."""
    game = get_game(game_slug)
    effort = getattr(game, "effort", None) or {}
    return int(effort.get("min_seconds") or 0), int(effort.get("min_actions") or 0)


def brand_is_active(brand):
    """Rewards are on unless a brand has been switched off in the panel."""
    if brand is None:
        return True
    settings_row = BrandRewardSettings.objects.filter(brand=brand).first()
    return settings_row is None or settings_row.is_active


def _month_start(now):
    local = timezone.localtime(now)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _profiles_sharing_a_phone(profile):
    """Every profile that is really this person, keyed by the mobile number.

    Clearing cookies mints a fresh profile. The moment that profile types the
    same mobile number it is the same guest again, so the cooldown has to see
    across them. Without this the whole defence is one cookie.
    """
    ids = [profile.pk]
    if profile.phone:
        ids = list(
            type(profile)
            .objects.filter(phone=profile.phone)
            .values_list("pk", flat=True)
        )
    return ids


def _took_this_kind_this_month(profile, reward_type, now):
    """One coupon of this kind per mobile number, per calendar month.

    A dessert and a discount are separate allowances: taking the dessert
    does not spend the discount, and the other way round. The window is the
    calendar month, not a rolling week, because a week let the same mobile
    collect the same prize four times. Keyed on the mobile number as well as
    the profile, so clearing cookies buys nothing.
    """
    return (
        RewardCoupon.objects.filter(
            profile_id__in=_profiles_sharing_a_phone(profile),
            reward_type=reward_type,
            issued_at__gte=_month_start(now),
        )
        .exclude(status=RewardCoupon.Status.VOID)
        .exists()
    )


def _over_brand_cap(brand, now):
    if brand is None:
        return False
    settings_row = BrandRewardSettings.objects.filter(brand=brand).first()
    if settings_row is None or not settings_row.monthly_coupon_cap:
        return False
    issued = RewardCoupon.objects.filter(
        brand=brand, issued_at__gte=_month_start(now)
    ).count()
    return issued >= settings_row.monthly_coupon_cap


def _new_code(brand):
    """A short code staff can read aloud. Retries on the (rare) collision."""
    prefix = "".join(c for c in (brand.code if brand else "PR").upper() if c.isalnum())
    prefix = (prefix[:3] or "PR")
    for _ in range(10):
        body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        code = f"{prefix}-{body}"
        if not RewardCoupon.objects.filter(code=code).exists():
            return code
    return None


def _issue(profile, game_slug, rule, score, brand, outlet, now):
    code = _new_code(brand)
    if code is None:
        # Could not mint a unique code: refuse rather than hand out a
        # duplicate that two guests could both try to redeem.
        return None
    return RewardCoupon.objects.create(
        code=code,
        profile=profile,
        brand=brand,
        outlet=outlet,
        game_slug=game_slug,
        tier=rule.tier,
        score=score,
        reward_type=rule.reward_type,
        percent=rule.percent,
        expires_at=now + timedelta(days=rule.valid_days),
        # The allowance key. The unique index on these three columns is what
        # actually stops a second dessert in the same month; see _pay.
        phone_key=(profile.phone or None),
        allowance_period=allowance_period(now),
    )


# --------------------------------------------------------------------------
# progress: where one guest stands on one game
# --------------------------------------------------------------------------

def current_rung(profile, game_slug):
    """Highest ladder rung unlocked. Always starts at 1."""
    if profile is None:
        return 1
    row = RewardProgress.objects.filter(profile=profile, game_slug=game_slug).first()
    return row.rung if row else 1


def _set_rung(profile, game_slug, rung):
    row, _created = RewardProgress.objects.get_or_create(
        profile=profile, game_slug=game_slug, defaults={"rung": rung}
    )
    if row.rung != rung:
        row.rung = rung
        row.save(update_fields=["rung", "updated_at"])
    return row


def qualifying_rounds(profile, game_slug, window_days, min_score, now=None):
    """How many genuine, scoring rounds this guest has in the window."""
    if profile is None:
        return 0
    now = now or timezone.now()
    since = now - timedelta(days=window_days)
    return RewardRound.objects.filter(
        profile=profile,
        game_slug=game_slug,
        qualified=True,
        created_at__gte=since,
        score__gte=min_score,
    ).count()


def record_round(
    profile,
    game_slug,
    score,
    duration=0,
    actions=0,
    level=0,
    result=RoundResult.NONE,
    qualified=False,
    brand=None,
    outlet=None,
):
    """One finished round on the guest's audit trail."""
    return RewardRound.objects.create(
        profile=profile,
        game_slug=game_slug,
        score=score,
        duration_seconds=duration,
        actions=actions,
        level=level,
        result=result,
        qualified=qualified,
        brand=brand,
        outlet=outlet,
    )


def progress_payload(profile, game_slug, now=None):
    """Where this guest stands, in a shape the shell can render.

    Used twice: to draw the ladder / the round counter on the play page, and
    to explain a refusal on the game-over card. Guests can see the climb,
    which is the point of asking them to climb it.
    """
    now = now or timezone.now()
    mode = (earn_config(game_slug) or {}).get("mode", "none")
    # The mode name is internal. A guest reading the page source must not be
    # able to tell a paying game from the word the engine uses for it.
    shown = "ladder" if mode == "ladder" else ""
    payload = {
        "mode": shown,
        "verified": bool(profile is not None and profile.is_verified),
        "identified": bool(profile is not None and profile.phone),
    }

    if mode == "ladder":
        earn = earn_config(game_slug)
        levels = int(earn.get("levels") or 1)
        rung = current_rung(profile, game_slug)
        payload.update({"levels": levels, "rung": rung})
    elif mode == "streak":
        earn = earn_config(game_slug)
        need = int(earn.get("rounds") or 0)
        window = int(earn.get("window_days") or 7)
        tier = earn.get("prize_tier") or RewardTier.GOOD.value
        rule = rule_for_tier(game_slug, tier)
        floor = int(rule.min_score) if rule else 0
        done = qualifying_rounds(profile, game_slug, window, floor, now=now)
        payload.update(
            {
                "rounds_done": min(done, need),
                "window_days": window,
            }
        )
    elif mode == "threshold":
        earn = earn_config(game_slug)
        tier = earn.get("prize_tier") or RewardTier.GOOD.value
        rule = rule_for_tier(game_slug, tier)
        payload.update({"has_line": bool(rule)})
    return payload


# --------------------------------------------------------------------------
# the claim itself
# --------------------------------------------------------------------------

def _refusal(reason, profile, game_slug, now, **fmt):
    text = REASON_TEXT.get(reason, "")
    if fmt:
        text = text.format(**fmt)
    return ClaimOutcome(
        coupon=None,
        reason=reason,
        message=text,
        progress=progress_payload(profile, game_slug, now=now),
    )


def evaluate_round(
    profile,
    game_slug,
    score,
    brand=None,
    outlet=None,
    now=None,
    level=None,
    result=None,
    duration=None,
    actions=None,
):
    """Decide what a finished round earned. Always returns a ClaimOutcome."""
    now = now or timezone.now()

    def refuse(reason, **fmt):
        return _refusal(reason, profile, game_slug, now, **fmt)

    if profile is None:
        return refuse(Reason.NO_PROFILE)
    if not brand_is_active(brand):
        return refuse(Reason.BRAND_OFF)

    try:
        score = max(0, int(score or 0))
    except (TypeError, ValueError):
        score = 0
    try:
        duration = max(0, int(duration or 0))
    except (TypeError, ValueError):
        duration = 0
    try:
        actions = max(0, int(actions or 0))
    except (TypeError, ValueError):
        actions = 0

    earn = earn_config(game_slug)
    mode = earn.get("mode", "none")
    if mode == "none":
        return refuse(Reason.PURE_PLAY)

    # --- Requirement 3: the round was really played ------------------------
    min_seconds, min_actions = effort_floor(game_slug)
    if duration < min_seconds or actions < min_actions:
        return refuse(Reason.EFFORT)

    if mode == "ladder":
        outcome = _claim_ladder(
            profile, game_slug, score, earn, level, result, brand, outlet, now, refuse
        )
    elif mode == "reaches":
        outcome = _claim_reaches(
            profile, game_slug, score, earn, result, duration, actions,
            brand, outlet, now, refuse,
        )
    elif mode == "threshold":
        outcome = _claim_threshold(
            profile, game_slug, score, earn, duration, actions, brand, outlet, now, refuse
        )
    else:
        outcome = _claim_streak(
            profile, game_slug, score, earn, duration, actions, brand, outlet, now, refuse
        )
    if outcome is not None:
        return outcome
    return refuse(Reason.LOW_SCORE)


def _claim_ladder(
    profile, game_slug, score, earn, level, result, brand, outlet, now, refuse
):
    """Chess Master: win rung N to unlock rung N+1. Only the top rungs pay."""
    levels = int(earn.get("levels") or 1)
    paying = earn.get("paying_rungs") or {}

    try:
        level = int(level or 0)
    except (TypeError, ValueError):
        level = 0
    if level < 1 or level > levels:
        return refuse(Reason.EFFORT)

    result = (result or "").strip().lower()
    if result not in (RoundResult.WIN, RoundResult.DRAW, RoundResult.LOSS):
        result = RoundResult.LOSS

    rung = current_rung(profile, game_slug)
    # The round belongs on the trail whatever it earned, so the climb is
    # auditable and a guest can see where they are.
    record_round(
        profile,
        game_slug,
        score,
        duration=0,
        actions=0,
        level=level,
        result=result,
        qualified=(result == RoundResult.WIN),
        brand=brand,
        outlet=outlet,
    )

    # A win only counts if it was played ON the rung the guest is standing
    # on. Otherwise a guest could jump straight to Level 4 (which an
    # unverified guest is free to play) and cash in without climbing.
    if level > rung:
        return refuse(Reason.LOCKED)
    if result != RoundResult.WIN:
        return refuse(Reason.NOT_A_WIN)

    if level == rung and rung < levels:
        _set_rung(profile, game_slug, level + 1)

    tier = paying.get(level) or paying.get(str(level))
    if not tier:
        # Level 1 and Level 2 pay nothing. That is the cost of entry.
        return refuse(Reason.RUNG_FREE, level=level)

    rule = rule_for_tier(game_slug, tier)
    if rule is None:
        return refuse(Reason.RUNG_FREE, level=level)
    if score < rule.min_score:
        return refuse(Reason.LOW_SCORE)
    return _pay(profile, game_slug, rule, score, brand, outlet, now, refuse)


def _claim_reaches(
    profile, game_slug, score, earn, result, duration, actions,
    brand, outlet, now, refuse,
):
    """2048: the first time the tile is reached pays a dessert.

    A later reach pays 10% off, and only once this guest has `need` real
    reaches stored. Reaches in between pay nothing. A round that never made
    the tile pays nothing, however high the score.
    """
    need = int(earn.get("need") or 5)
    first = earn.get("first_tier") or RewardTier.GOOD.value
    later = earn.get("later_tier") or RewardTier.HIGH.value
    reached = (result or "").strip().lower() == RoundResult.WIN

    record_round(
        profile, game_slug, score,
        duration=duration, actions=actions,
        qualified=reached, result=RoundResult.WIN if reached else RoundResult.NONE,
        brand=brand, outlet=outlet,
    )
    if not reached:
        return refuse(Reason.LOW_SCORE)

    prior = RewardRound.objects.filter(
        profile__in=_profiles_sharing_a_phone(profile),
        game_slug=game_slug,
        qualified=True,
    ).count() - 1
    tier = first if prior < 1 else (later if prior + 1 >= need else None)
    if tier is None:
        return refuse(Reason.NOT_YET)
    rule = rule_for_tier(game_slug, tier)
    if rule is None:
        return refuse(Reason.PURE_PLAY)
    return _pay(profile, game_slug, rule, score, brand, outlet, now, refuse)


def _claim_threshold(
    profile, game_slug, score, earn, duration, actions, brand, outlet, now, refuse
):
    """One scoring round that clears the line. Flappy Burger at 25 pipes.

    A single round, not a run: the client asked for "25 or above pays the
    dessert" (2026-10-16, third pass). What keeps it from being easy is not
    this function but the gates in `_pay`: a verified identity, one reward per
    guest per calendar month keyed on the mobile number, and the brand's
    monthly cap.
    Never a coupon: only `prize_tier` is ever in play here.
    """
    tier = earn.get("prize_tier") or RewardTier.GOOD.value
    rule = rule_for_tier(game_slug, tier)
    if rule is None:
        # The tier was switched off in the panel, so there is nothing to win.
        return refuse(Reason.PURE_PLAY)

    qualifies = score >= rule.min_score
    record_round(
        profile,
        game_slug,
        score,
        duration=duration,
        actions=actions,
        qualified=qualifies,
        brand=brand,
        outlet=outlet,
    )
    if not qualifies:
        return refuse(Reason.LOW_SCORE)
    return _pay(profile, game_slug, rule, score, brand, outlet, now, refuse)


def _claim_streak(
    profile, game_slug, score, earn, duration, actions, brand, outlet, now, refuse
):
    """Memory Match: a dessert, and only after a run of real rounds."""
    need = int(earn.get("rounds") or 0)
    window = int(earn.get("window_days") or 7)
    tier = earn.get("prize_tier") or RewardTier.GOOD.value
    rule = rule_for_tier(game_slug, tier)
    if rule is None or need <= 0:
        return refuse(Reason.PURE_PLAY)

    qualifies = score >= rule.min_score
    record_round(
        profile,
        game_slug,
        score,
        duration=duration,
        actions=actions,
        qualified=qualifies,
        brand=brand,
        outlet=outlet,
    )

    done = qualifying_rounds(profile, game_slug, window, rule.min_score, now=now)
    if not qualifies:
        return refuse(Reason.LOW_SCORE)
    if done < need:
        return refuse(
            Reason.NOT_YET, done=done, need=need, left=max(0, need - done)
        )
    return _pay(profile, game_slug, rule, score, brand, outlet, now, refuse)


def _pay(profile, game_slug, rule, score, brand, outlet, now, refuse):
    """The gates that apply to every prize, whatever the earning rule was."""
    if not profile.is_verified:
        return refuse(Reason.NOT_VERIFIED)
    if _took_this_kind_this_month(profile, rule.reward_type, now):
        return refuse(Reason.COOLDOWN)
    if _over_brand_cap(brand, now):
        return refuse(Reason.CAP)

    try:
        # Nested atomic block: an IntegrityError marks the surrounding
        # transaction unusable, so it has to be caught outside a savepoint
        # this function owns.
        with transaction.atomic():
            coupon = _issue(profile, game_slug, rule, score, brand, outlet, now)
    except IntegrityError:
        # Two indexes can raise here: the allowance key (another claim for
        # this number and month won the race between the read and the write)
        # or the code's own unique column (a collision `_new_code` did not
        # see). Ask the KEY which one was rejected. This is deliberately not
        # `_took_this_kind_this_month`: that asks "has this PERSON taken one
        # this month" and ranges over every profile sharing the number, while
        # the index only knows the (phone, kind, month) key on one row.
        key_taken = bool(profile.phone) and (
            RewardCoupon.objects.filter(
                phone_key=profile.phone,
                reward_type=rule.reward_type,
                allowance_period=allowance_period(now),
            )
            .exclude(status=RewardCoupon.Status.VOID)
            .exists()
        )
        return refuse(Reason.COOLDOWN if key_taken else Reason.CAP)
    if coupon is None:
        return refuse(Reason.CAP)
    return ClaimOutcome(
        coupon=coupon,
        reason=Reason.ISSUED,
        message=REASON_TEXT[Reason.ISSUED],
        progress=progress_payload(profile, game_slug, now=now),
    )


# --------------------------------------------------------------------------
# round tokens: bind a claim to a play page this guest actually loaded
# --------------------------------------------------------------------------

def sign_round_token(game_slug, now=None):
    """Token embedded in the play page, claimed once when the round ends.

    Deliberately NOT bound to a guest profile: only the guest's own browser
    holds the token, so cross-guest sharing is not a real risk, and keeping
    the profile out means loading a play page does not have to create one.
    The profile is resolved from the cookie at claim time instead.
    """
    now = now or timezone.now()
    return signing.dumps(
        {"g": game_slug, "t": int(now.timestamp())},
        salt=_TOKEN_SALT,
        compress=True,
    )


def verify_round_token(token, game_slug, now=None, min_seconds=None):
    """True when the token is ours, for this game, and not brand new.

    A speed bump, not proof of anything. See the module docstring.
    """
    if not token:
        return False
    min_seconds = MIN_ROUND_SECONDS if min_seconds is None else min_seconds
    try:
        data = signing.loads(token, salt=_TOKEN_SALT, max_age=TOKEN_MAX_AGE_SECONDS)
    except (signing.BadSignature, signing.SignatureExpired, ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    if data.get("g") != game_slug:
        return False
    issued = int(data.get("t") or 0)
    if issued <= 0:
        return False
    age = (now or timezone.now()).timestamp() - issued
    return min_seconds <= age <= TOKEN_MAX_AGE_SECONDS
