"""
Game reward suite (client rules 2026-10-16, second pass).

Locks the reward contract the client set when the first pass was reviewed and
rejected as too easy:

  * MERELY PLAYING NEVER PAYS -- not a coupon, not a dessert, in any game
  * PAY FOR A CLIMB, NOT FOR A SCORE
      chess-master   Level 1 and Level 2 pay nothing; a Level 3 win pays the
                     dessert; a Level 4 win pays the 10% discount. A win only
                     counts on the rung the guest is standing on, so the
                     ladder cannot be jumped.
      memory-match   never a coupon, and a dessert only after five qualifying
                     rounds inside seven days
      flappy-burger  never a coupon, and a dessert only when one real round
                     clears 25 pipes
      2048           pure play, pays nothing
  * THE ROUND HAS TO BE REALLY PLAYED -- the per-game effort floor
  * BEING VERIFIED IS THE GATE ON BEING PAID, NEVER ON PLAYING
  * one dessert AND one discount per mobile number per calendar month, across
    every game, so a cleared cookie buys nothing and a dessert does not
    spend the discount
  * a per-brand monthly cap
  * a winning round needs a real round token; a bare POST cannot mint one

Scores, durations and action counts all arrive from the browser and none of
them are proof of a real win. The tests below lock the RULES, and the module
docstring of apps/rewards/services.py is where the honesty about what those
rules can and cannot guarantee lives.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Brand, Outlet, QrCode, SmartPage
from apps.guests.models import GuestProfile

from .models import (
    BrandRewardSettings,
    RewardCoupon,
    RewardProgress,
    RewardRound,
    RewardRule,
    RewardTier,
    RewardType,
)
from .services import (
    MIN_ROUND_SECONDS,
    Reason,
    current_rung,
    effective_rules,
    evaluate_round,
    sign_round_token,
    verify_round_token,
)

# What a real round of each game looks like, matching the registry floors.
CHESS_EFFORT = {"duration": 90, "actions": 12}
MEMORY_EFFORT = {"duration": 45, "actions": 8}
FLAPPY_EFFORT = {"duration": 25, "actions": 15}
# A Level 3 win scores 600x... no: 200 x level + captures. Level 3 -> 600.
CHESS_WIN_L3 = 620
CHESS_WIN_L4 = 820
MEMORY_GOOD = 500
# Flappy Burger's line, in pipes (client 2026-10-16, third pass).
FLAPPY_LINE = 25


def _hours_open_all_day():
    return {
        d: {"open": "00:00", "close": "23:59", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }


class RewardFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(
            name_en="King Chef Rewards", code="KINGCHEF-RW", status="active"
        )
        cls.outlet = Outlet.objects.create(
            code="KINGCHEF-RW-INTL",
            slug="rewards-international-city",
            official_name="King Chef - International City",
            brand=cls.brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        cls.page = SmartPage.objects.create(
            brand=cls.brand,
            outlet=cls.outlet,
            slug="rewards-intlcity",
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
            qr_code_name="KINGCHEF-RW-TABLE-001",
            redirect_key="kcrw-table-001",
        )

class ProfileRewardFixtures(RewardFixtures):
    """Adds the guest the unit tests hand to evaluate_round.

    `self.profile` is VERIFIED the way the client defined it (first name,
    last name and a mobile number), because a reward can only be paid to a
    verified guest. Tests about the gate itself use `self.unverified`.
    """

    def setUp(self):
        self.profile = GuestProfile.objects.create(
            guest_id="reward-guest-1",
            first_name="Reem",
            last_name="Al Suwaidi",
            phone="+971501234567",
        )
        self.unverified = GuestProfile.objects.create(
            guest_id="reward-guest-anon", first_name="Sam"
        )

    def climb(self, rung, profile=None):
        """Put a guest on a ladder rung without playing for it."""
        row, _created = RewardProgress.objects.get_or_create(
            profile=profile or self.profile, game_slug="chess-master"
        )
        row.rung = rung
        row.save(update_fields=["rung", "updated_at"])
        return row


class EffectiveRulesTests(TestCase):
    """The registry defaults, and how a DB row overrides just one tier."""

    def test_chess_keeps_both_lines(self):
        rules = effective_rules("chess-master")
        self.assertEqual([r.tier for r in rules], [RewardTier.HIGH, RewardTier.GOOD])
        self.assertEqual(rules[0].min_score, 600)
        self.assertEqual(rules[1].min_score, 300)
        self.assertEqual(rules[0].reward_type, RewardType.PERCENT)
        self.assertEqual(rules[1].reward_type, RewardType.DESSERT)

    def test_memory_match_has_only_the_dessert_line(self):
        """Memory Match never pays a coupon (client rule)."""
        rules = effective_rules("memory-match")
        self.assertEqual([r.tier for r in rules], [RewardTier.GOOD])
        self.assertEqual(rules[0].reward_type, RewardType.DESSERT)
        self.assertEqual(rules[0].percent, 0)

    def test_the_pure_play_game_has_no_rules_at_all(self):
        self.assertEqual(effective_rules("2048"), [])

    def test_a_game_with_no_configured_reward_pays_nothing(self):
        self.assertEqual(effective_rules("no-such-game"), [])

    def test_a_db_row_overrides_only_its_own_tier(self):
        RewardRule.objects.create(
            game_slug="chess-master",
            tier=RewardTier.GOOD,
            min_score=50,
            reward_type=RewardType.DESSERT,
        )
        rules = {r.tier: r for r in effective_rules("chess-master")}
        self.assertEqual(rules[RewardTier.GOOD].min_score, 50)
        # the high tier keeps its registry default
        self.assertEqual(rules[RewardTier.HIGH].min_score, 600)

    def test_an_inactive_row_switches_that_tier_off(self):
        RewardRule.objects.create(
            game_slug="chess-master",
            tier=RewardTier.HIGH,
            min_score=9999,
            active=False,
        )
        tiers = [r.tier for r in effective_rules("chess-master")]
        self.assertNotIn(RewardTier.HIGH, tiers)
        self.assertIn(RewardTier.GOOD, tiers)

    def test_an_inactive_row_on_memory_match_leaves_nothing_to_win(self):
        RewardRule.objects.create(
            game_slug="memory-match",
            tier=RewardTier.GOOD,
            min_score=400,
            active=False,
        )
        self.assertEqual(effective_rules("memory-match"), [])


# A real round of 2048, matching the registry floor.
TILES_EFFORT = {"duration": 60, "actions": 20}


class TilesTests(ProfileRewardFixtures):
    """2048 pays only when the 2048 tile is actually reached.

    Client 2026-10-16: the first time a guest reaches the 2048 tile, a free
    dessert. Reaching it again does not pay again until that guest has five
    real reaches stored against their name and mobile. The fifth reach pays
    10% off, and never a second dessert. A high score that never made the
    tile pays nothing.
    """

    def reach(self, reached=True, profile=None, score=2048, **overrides):
        effort = dict(TILES_EFFORT)
        effort.update(overrides)
        return evaluate_round(
            profile or self.profile,
            "2048",
            score,
            self.brand,
            self.outlet,
            result="win" if reached else "",
            **effort,
        )

    def test_the_first_time_the_2048_tile_is_reached_pays_a_dessert(self):
        outcome = self.reach()
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.label, "Free dessert")
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)
        self.assertEqual(outcome.coupon.percent, 0)

    def test_a_high_score_that_never_made_the_tile_pays_nothing(self):
        outcome = self.reach(reached=False, score=20000)
        self.assertIs(outcome.reason, Reason.LOW_SCORE)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_the_second_reach_does_not_pay_another_dessert(self):
        self.assertTrue(self.reach().issued)
        outcome = self.reach()
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1)

    def test_a_round_too_short_to_be_real_does_not_count(self):
        outcome = self.reach(duration=TILES_EFFORT["duration"] - 1)
        self.assertIs(outcome.reason, Reason.EFFORT)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardRound.objects.count(), 0)

    def test_an_unverified_guest_is_not_paid(self):
        outcome = self.reach(profile=self.unverified)
        self.assertIs(outcome.reason, Reason.NOT_VERIFIED)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(
            RewardRound.objects.filter(profile=self.unverified, qualified=True).count(), 1
        )

    def test_a_refusal_never_says_how_many_reaches_are_left(self):
        self.assertTrue(self.reach().issued)
        outcome = self.reach()
        spoken = (outcome.message + " " + str(outcome.progress)).lower()
        for leaked in ("5", "four", "of 5", "to go", "reaches", "2048"):
            self.assertNotIn(leaked, spoken)

    def test_a_new_cookie_with_the_same_mobile_does_not_restart_the_count(self):
        self.assertTrue(self.reach().issued)
        fresh = GuestProfile.objects.create(
            guest_id="reward-guest-fresh",
            first_name="Reem",
            last_name="Al Suwaidi",
            phone=self.profile.phone,
        )
        outcome = self.reach(profile=fresh)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1)

    def test_the_fifth_reach_pays_ten_percent_off(self):
        self.assertTrue(self.reach().issued)
        for _ in range(3):
            self.assertIsNone(self.reach().coupon)
        outcome = self.reach()
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.reward_type, RewardType.PERCENT)
        self.assertEqual(outcome.coupon.percent, 10)
        self.assertEqual(outcome.coupon.label, "10% off")
        self.assertEqual(RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1)


class ThresholdTests(ProfileRewardFixtures):
    """Flappy Burger: one real round of 25 pipes pays the free dessert.

    Client 2026-10-16, third pass: "flappy burger if 25 above is gone allow
    it desserts to user". Never a coupon and never the 10% discount, and the
    weekly cooldown is what keeps a single round from being easy money.
    """

    def flap(self, score, profile=None, **overrides):
        effort = dict(FLAPPY_EFFORT)
        effort.update(overrides)
        return evaluate_round(
            profile or self.profile,
            "flappy-burger",
            score,
            self.brand,
            self.outlet,
            **effort,
        )

    def test_flappy_is_no_longer_pure_play(self):
        """A guard against this game being reverted to pays-nothing."""
        outcome = self.flap(FLAPPY_LINE)
        self.assertIsNot(outcome.reason, Reason.PURE_PLAY)

    def test_a_round_of_25_pipes_pays_the_free_dessert(self):
        outcome = self.flap(FLAPPY_LINE)
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.label, "Free dessert")
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)
        self.assertEqual(outcome.coupon.tier, RewardTier.GOOD)
        self.assertIs(outcome.reason, Reason.ISSUED)

    def test_a_round_above_25_also_pays_the_dessert(self):
        self.assertTrue(self.flap(61).issued)

    def test_a_round_of_24_pipes_pays_nothing(self):
        outcome = self.flap(FLAPPY_LINE - 1)
        self.assertIs(outcome.reason, Reason.LOW_SCORE)
        self.assertIsNone(outcome.coupon)
        spoken = (outcome.message + " " + str(outcome.progress)).lower()
        self.assertNotIn("25", spoken)
        self.assertNotIn("min_score", spoken)

    def test_it_never_pays_a_coupon_or_a_discount(self):
        """Only the good tier is in play. There is no path to 10% off here."""
        outcome = self.flap(9999)
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)
        self.assertNotEqual(outcome.coupon.tier, RewardTier.HIGH)
        self.assertEqual(outcome.coupon.percent, 0)
        self.assertEqual(effective_rules("flappy-burger")[0].tier, RewardTier.GOOD)
        self.assertEqual(
            [r.tier for r in effective_rules("flappy-burger")], [RewardTier.GOOD]
        )

    def test_the_effort_floor_still_applies(self):
        outcome = self.flap(FLAPPY_LINE, duration=FLAPPY_EFFORT["duration"] - 1)
        self.assertIs(outcome.reason, Reason.EFFORT)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardRound.objects.count(), 0)

    def test_an_unverified_guest_plays_but_is_not_paid(self):
        outcome = self.flap(FLAPPY_LINE, profile=self.unverified)
        self.assertIs(outcome.reason, Reason.NOT_VERIFIED)
        self.assertIsNone(outcome.coupon)

    def test_the_cooldown_stops_a_second_dessert_the_same_week(self):
        self.assertTrue(self.flap(FLAPPY_LINE).issued)
        outcome = self.flap(FLAPPY_LINE)
        self.assertIs(outcome.reason, Reason.COOLDOWN)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(RewardCoupon.objects.count(), 1)

    def test_the_line_can_be_retuned_with_a_rule_row(self):
        """Staff raise the bar to 40 without a code change."""
        RewardRule.objects.create(
            game_slug="flappy-burger",
            tier=RewardTier.GOOD,
            min_score=40,
            reward_type=RewardType.DESSERT,
        )
        self.assertIs(self.flap(FLAPPY_LINE).reason, Reason.LOW_SCORE)
        self.assertTrue(self.flap(40).issued)

    def test_switching_the_tier_off_leaves_nothing_to_win(self):
        RewardRule.objects.create(
            game_slug="flappy-burger",
            tier=RewardTier.GOOD,
            min_score=25,
            active=False,
        )
        outcome = self.flap(9999)
        self.assertIs(outcome.reason, Reason.PURE_PLAY)
        self.assertIsNone(outcome.coupon)

    def test_the_progress_does_not_say_what_the_line_is(self):
        outcome = self.flap(3)
        self.assertEqual(outcome.progress.get("mode"), "threshold")
        self.assertNotIn("min_score", outcome.progress)
        self.assertNotIn("prize", outcome.progress)


class EffortFloorTests(ProfileRewardFixtures):
    """A round has to be really played. One tap is not a round."""

    def test_a_chess_round_below_the_time_floor_is_refused(self):
        outcome = evaluate_round(
            self.profile,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            duration=CHESS_EFFORT["duration"] - 1,
            actions=CHESS_EFFORT["actions"],
        )
        self.assertIs(outcome.reason, Reason.EFFORT)
        self.assertIsNone(outcome.coupon)

    def test_a_chess_round_below_the_action_floor_is_refused(self):
        outcome = evaluate_round(
            self.profile,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            duration=CHESS_EFFORT["duration"],
            actions=CHESS_EFFORT["actions"] - 1,
        )
        self.assertIs(outcome.reason, Reason.EFFORT)

    def test_a_memory_round_below_the_floor_does_not_count_towards_the_run(self):
        for _ in range(6):
            evaluate_round(
                self.profile,
                "memory-match",
                MEMORY_GOOD,
                self.brand,
                self.outlet,
                duration=MEMORY_EFFORT["duration"] - 1,
                actions=MEMORY_EFFORT["actions"],
            )
        self.assertEqual(RewardRound.objects.count(), 0)
        self.assertEqual(RewardCoupon.objects.count(), 0)


class ChessLadderTests(ProfileRewardFixtures):
    """Win rung N to unlock rung N+1. Only the top two rungs pay."""

    def win(self, level, score=None, profile=None, result="win"):
        return evaluate_round(
            profile or self.profile,
            "chess-master",
            CHESS_WIN_L3 if level == 3 else CHESS_WIN_L4 if level == 4 else 220,
            self.brand,
            self.outlet,
            level=level,
            result=result,
            **CHESS_EFFORT,
        )

    def test_level_1_pays_nothing_and_unlocks_level_2(self):
        outcome = self.win(1)
        self.assertIs(outcome.reason, Reason.RUNG_FREE)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(current_rung(self.profile, "chess-master"), 2)
        self.assertIn("Level 1", outcome.message)

    def test_level_2_pays_nothing_and_unlocks_level_3(self):
        self.climb(2)
        outcome = self.win(2)
        self.assertIs(outcome.reason, Reason.RUNG_FREE)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(current_rung(self.profile, "chess-master"), 3)

    def test_a_level_3_win_pays_the_dessert_and_unlocks_level_4(self):
        self.climb(3)
        outcome = self.win(3)
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.label, "Free dessert")
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)
        self.assertEqual(outcome.coupon.tier, RewardTier.GOOD)
        self.assertEqual(current_rung(self.profile, "chess-master"), 4)

    def test_a_level_4_win_pays_the_ten_percent_discount(self):
        self.climb(4)
        outcome = self.win(4)
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.label, "10% off")
        self.assertEqual(outcome.coupon.reward_type, RewardType.PERCENT)
        self.assertEqual(outcome.coupon.percent, 10)
        self.assertEqual(RewardCoupon.objects.count(), 1)

    def test_a_level_3_win_pays_the_dessert_never_the_discount_too(self):
        self.climb(3)
        outcome = self.win(3)
        self.assertEqual(RewardCoupon.objects.count(), 1)
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)

    def test_the_ladder_cannot_be_jumped(self):
        """The whole point: Level 4 is worth nothing from rung 1."""
        outcome = self.win(4)
        self.assertIs(outcome.reason, Reason.LOCKED)
        self.assertIsNone(outcome.coupon)
        self.assertEqual(current_rung(self.profile, "chess-master"), 1)

    def test_only_a_win_climbs_the_ladder(self):
        for result in ("loss", "draw"):
            outcome = self.win(1, result=result)
            self.assertIs(outcome.reason, Reason.NOT_A_WIN, result)
            self.assertEqual(current_rung(self.profile, "chess-master"), 1, result)
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_replaying_an_earlier_level_does_not_rewind_the_ladder(self):
        self.climb(3)
        self.win(1)
        self.assertEqual(current_rung(self.profile, "chess-master"), 3)

    def test_the_ladder_survives_across_rounds(self):
        self.win(1)
        self.win(2)
        self.assertEqual(current_rung(self.profile, "chess-master"), 3)
        self.assertEqual(
            RewardRound.objects.filter(game_slug="chess-master").count(), 2
        )

    def test_progress_is_reported_back_so_the_guest_can_see_the_climb(self):
        outcome = self.win(1)
        self.assertEqual(outcome.progress["mode"], "ladder")
        self.assertEqual(outcome.progress["rung"], 2)
        self.assertEqual(outcome.progress["levels"], 4)
        # where they stand, never which rung pays what
        self.assertNotIn("prizes", outcome.progress)

    def test_a_score_below_the_quality_line_pays_nothing(self):
        self.climb(3)
        outcome = evaluate_round(
            self.profile,
            "chess-master",
            299,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            **CHESS_EFFORT,
        )
        self.assertIs(outcome.reason, Reason.LOW_SCORE)
        self.assertIsNone(outcome.coupon)


class VerificationGateTests(ProfileRewardFixtures):
    """Being verified gates BEING PAID. It never gates playing."""

    def test_an_unverified_guest_can_win_but_cannot_be_paid(self):
        self.climb(3, profile=self.unverified)
        outcome = evaluate_round(
            self.unverified,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            **CHESS_EFFORT,
        )
        self.assertIs(outcome.reason, Reason.NOT_VERIFIED)
        self.assertIsNone(outcome.coupon)
        # the climb still counts: they did the work, only the payout waits
        self.assertEqual(current_rung(self.unverified, "chess-master"), 4)

    def test_an_unverified_guest_cannot_jump_the_ladder_either(self):
        """Play is open to them; the rung still has to be climbed in order."""
        outcome = evaluate_round(
            self.unverified,
            "chess-master",
            CHESS_WIN_L4,
            self.brand,
            self.outlet,
            level=4,
            result="win",
            **CHESS_EFFORT,
        )
        self.assertIs(outcome.reason, Reason.LOCKED)
        self.assertEqual(current_rung(self.unverified, "chess-master"), 1)

    def test_a_name_and_a_mobile_number_is_enough(self):
        outcome = self._chess_win(self.profile)
        self.assertTrue(outcome.issued)

    def test_google_sign_in_is_enough(self):
        google = GuestProfile.objects.create(
            guest_id="reward-guest-google",
            email="reem@example.com",
            email_verified=True,
            google_sub="google-sub-1",
        )
        outcome = self._chess_win(google)
        self.assertTrue(outcome.issued)

    def test_a_name_without_a_mobile_is_not_verified(self):
        named = GuestProfile.objects.create(
            guest_id="reward-guest-named", first_name="Reem", last_name="Al Suwaidi"
        )
        outcome = self._chess_win(named)
        self.assertIs(outcome.reason, Reason.NOT_VERIFIED)

    def test_the_refusal_points_at_the_form(self):
        outcome = self._chess_win(self.unverified)
        self.assertIn("name and mobile", outcome.message.lower())

    def test_the_guest_is_reported_as_unverified_to_the_shell(self):
        outcome = self._chess_win(self.unverified)
        self.assertFalse(outcome.progress["verified"])

    def _chess_win(self, profile):
        row, _created = RewardProgress.objects.get_or_create(
            profile=profile, game_slug="chess-master"
        )
        row.rung = 3
        row.save(update_fields=["rung", "updated_at"])
        return evaluate_round(
            profile,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            **CHESS_EFFORT,
        )


class MemoryMatchStreakTests(ProfileRewardFixtures):
    """A dessert, never a coupon, and only after a run of real rounds."""

    def play(self, score=MEMORY_GOOD, **effort):
        params = dict(MEMORY_EFFORT)
        params.update(effort)
        return evaluate_round(
            self.profile,
            "memory-match",
            score,
            self.brand,
            self.outlet,
            **params,
        )

    def test_four_qualifying_rounds_pay_nothing(self):
        for _ in range(4):
            outcome = self.play()
            self.assertIs(outcome.reason, Reason.NOT_YET)
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_five_qualifying_rounds_pay_the_dessert(self):
        for _ in range(4):
            self.play()
        outcome = self.play()
        self.assertTrue(outcome.issued)
        self.assertEqual(outcome.coupon.label, "Free dessert")
        self.assertEqual(outcome.coupon.reward_type, RewardType.DESSERT)

    def test_memory_match_never_pays_a_percentage_coupon(self):
        """The client was explicit: Memory Match allows desserts only."""
        for _ in range(5):
            outcome = self.play(score=9999)
        self.assertTrue(outcome.issued)
        self.assertNotEqual(outcome.coupon.reward_type, RewardType.PERCENT)
        self.assertEqual(outcome.coupon.percent, 0)
        self.assertEqual(
            set(
                RewardCoupon.objects.values_list("reward_type", flat=True)
            ),
            {RewardType.DESSERT},
        )

    def test_a_round_below_the_quality_line_does_not_count(self):
        for _ in range(4):
            self.play(score=MEMORY_GOOD)
        self.play(score=50)  # played out, but not a good game
        self.assertEqual(RewardCoupon.objects.count(), 0)
        # and the run is still one short
        outcome = self.play()
        self.assertTrue(outcome.issued)

    def test_the_progress_counts_up_so_the_guest_can_see_it(self):
        outcome = self.play()
        self.assertEqual(outcome.progress["mode"], "streak")
        self.assertEqual(outcome.progress["rounds_done"], 1)
        self.assertNotIn("rounds_needed", outcome.progress)
        self.assertNotIn("rounds_left", outcome.progress)

    def test_a_short_run_does_not_say_how_many_rounds_pay(self):
        """The guest hears 'keep playing', never '4 more and you win'."""
        outcome = self.play()
        spoken = (outcome.message + " " + str(outcome.progress)).lower()
        self.assertNotIn("of 5", spoken)
        self.assertNotIn("rounds_needed", spoken)
        self.assertNotIn("to go", spoken)

    def test_the_run_is_only_the_last_seven_days(self):
        old = timezone.now() - timedelta(days=8)
        RewardRound.objects.filter(game_slug="memory-match").delete()
        for _ in range(5):
            round_row = self.play()
        RewardRound.objects.filter(game_slug="memory-match").update(created_at=old)
        outcome = self.play()
        self.assertIs(outcome.reason, Reason.NOT_YET)
        self.assertEqual(outcome.progress["rounds_done"], 1)


class FarmingLimitsTests(ProfileRewardFixtures):
    """The cooldown, the phone key and the monthly cap."""

    def issue_dessert(self, profile=None):
        """A real dessert win: chess Level 3, already climbed to that rung."""
        profile = profile or self.profile
        row, _created = RewardProgress.objects.get_or_create(
            profile=profile, game_slug="chess-master"
        )
        row.rung = 3
        row.save(update_fields=["rung", "updated_at"])
        return evaluate_round(
            profile,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            **CHESS_EFFORT,
        )

    def issue_chess_win(self, profile=None, level=4):
        profile = profile or self.profile
        row, _created = RewardProgress.objects.get_or_create(
            profile=profile, game_slug="chess-master"
        )
        row.rung = level
        row.save(update_fields=["rung", "updated_at"])
        return evaluate_round(
            profile,
            "chess-master",
            CHESS_WIN_L4,
            self.brand,
            self.outlet,
            level=level,
            result="win",
            **CHESS_EFFORT,
        )

    def test_a_second_reward_inside_the_cooldown_is_refused(self):
        self.assertTrue(self.issue_chess_win().issued)
        second = self.issue_chess_win()
        self.assertIs(second.reason, Reason.COOLDOWN)
        self.assertEqual(RewardCoupon.objects.count(), 1)

    def test_the_monthly_allowance_spans_every_game(self):
        """A dessert from chess spends the dessert, whatever game asks next."""
        self.assertTrue(self.issue_dessert().issued)
        for _ in range(5):
            outcome = evaluate_round(
                self.profile,
                "memory-match",
                MEMORY_GOOD,
                self.brand,
                self.outlet,
                **MEMORY_EFFORT,
            )
        self.assertIs(outcome.reason, Reason.COOLDOWN)
        self.assertEqual(
            RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1
        )

    def test_two_profiles_with_the_same_mobile_share_one_cooldown(self):
        """Clearing cookies must not buy a fresh allowance."""
        self.assertTrue(self.issue_chess_win().issued)
        twin = GuestProfile.objects.create(
            guest_id="reward-guest-cleared-cookies",
            first_name="Reem",
            last_name="Al Suwaidi",
            phone="+971501234567",
        )
        outcome = self.issue_chess_win(profile=twin)
        self.assertIs(outcome.reason, Reason.COOLDOWN)
        self.assertEqual(RewardCoupon.objects.count(), 1)

    def test_a_cleared_cookie_cannot_take_a_second_dessert(self):
        """The monthly dessert is keyed on the mobile, not the browser."""
        self.assertTrue(self.issue_dessert().issued)
        twin = GuestProfile.objects.create(
            guest_id="reward-guest-cleared-cookies-dessert",
            first_name="Reem",
            last_name="Al Suwaidi",
            phone="+971501234567",
        )
        outcome = self.issue_dessert(profile=twin)
        self.assertIs(outcome.reason, Reason.COOLDOWN)
        self.assertEqual(
            RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1
        )

    def test_a_different_mobile_gets_its_own_cooldown(self):
        self.assertTrue(self.issue_chess_win().issued)
        other = GuestProfile.objects.create(
            guest_id="reward-guest-other",
            first_name="Noura",
            last_name="Al Mansoori",
            phone="+971501234568",
        )
        self.assertTrue(self.issue_chess_win(profile=other).issued)

    def test_a_new_calendar_month_frees_both_allowances(self):
        """Last month's prizes do not spend this month."""
        dessert = self.issue_dessert()
        discount = self.issue_chess_win()
        self.assertTrue(dessert.issued and discount.issued)
        RewardCoupon.objects.filter(profile=self.profile).update(
            issued_at=timezone.now() - timedelta(days=40)
        )
        self.assertTrue(self.issue_dessert().issued)
        self.assertTrue(self.issue_chess_win().issued)
        self.assertEqual(RewardCoupon.objects.count(), 4)

    def test_a_second_dessert_in_the_same_month_is_refused(self):
        """One free dessert per mobile per calendar month.

        The old weekly cooldown expired after 7 days and then paid again.
        Eight days is still the same month, so a second dessert must not.
        """
        first = self.issue_dessert()
        self.assertTrue(first.issued)
        RewardCoupon.objects.filter(pk=first.coupon.pk).update(
            issued_at=timezone.now() - timedelta(days=8)
        )
        second = self.issue_dessert()
        self.assertIs(second.reason, Reason.COOLDOWN)
        self.assertIsNone(second.coupon)
        self.assertEqual(
            RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1
        )

    def test_a_dessert_does_not_spend_the_discount_allowance(self):
        """The two prizes are separate monthly allowances, not one shared pot."""
        self.assertTrue(self.issue_dessert().issued)
        discount = self.issue_chess_win()
        self.assertTrue(discount.issued)
        self.assertEqual(discount.coupon.reward_type, RewardType.PERCENT)
        self.assertEqual(RewardCoupon.objects.count(), 2)

    def test_a_second_discount_in_the_same_month_is_refused(self):
        first = self.issue_chess_win()
        self.assertTrue(first.issued)
        RewardCoupon.objects.filter(pk=first.coupon.pk).update(
            issued_at=timezone.now() - timedelta(days=8)
        )
        second = self.issue_chess_win()
        self.assertIs(second.reason, Reason.COOLDOWN)
        self.assertEqual(
            RewardCoupon.objects.filter(reward_type=RewardType.PERCENT).count(), 1
        )

    def test_redeeming_a_coupon_does_not_free_another_this_month(self):
        """Handing the prize over at the till is not a reset button."""
        first = self.issue_dessert()
        first.coupon.status = RewardCoupon.Status.REDEEMED
        first.coupon.save(update_fields=["status", "updated_at"])
        second = self.issue_dessert()
        self.assertIs(second.reason, Reason.COOLDOWN)
        self.assertEqual(
            RewardCoupon.objects.filter(reward_type=RewardType.DESSERT).count(), 1
        )

    def test_a_voided_coupon_does_not_block_the_next_win(self):
        first = self.issue_chess_win()
        first.coupon.status = RewardCoupon.Status.VOID
        first.coupon.save(update_fields=["status", "updated_at"])
        self.assertTrue(self.issue_chess_win().issued)

    def test_switching_the_brand_off_stops_every_reward(self):
        BrandRewardSettings.objects.create(brand=self.brand, is_active=False)
        outcome = self.issue_chess_win()
        self.assertIs(outcome.reason, Reason.BRAND_OFF)

    def test_the_monthly_brand_cap_stops_issuing(self):
        BrandRewardSettings.objects.create(brand=self.brand, monthly_coupon_cap=1)
        self.assertTrue(self.issue_chess_win().issued)
        other = GuestProfile.objects.create(
            guest_id="reward-guest-cap",
            first_name="Noura",
            last_name="Al Mansoori",
            phone="+971501234568",
        )
        outcome = self.issue_chess_win(profile=other)
        self.assertIs(outcome.reason, Reason.CAP)

    def test_without_a_profile_there_is_no_reward(self):
        outcome = evaluate_round(None, "chess-master", CHESS_WIN_L4, self.brand)
        self.assertIs(outcome.reason, Reason.NO_PROFILE)

    def test_the_code_is_readable_and_brand_prefixed(self):
        coupon = self.issue_chess_win().coupon
        prefix, _, body = coupon.code.partition("-")
        self.assertEqual(prefix, "KIN")
        self.assertEqual(len(body), 6)
        # no characters that get misread off a phone screen
        self.assertFalse(set(body) & set("01OIL"))


class CouponLifecycleTests(ProfileRewardFixtures):
    def _coupon(self):
        row, _created = RewardProgress.objects.get_or_create(
            profile=self.profile, game_slug="chess-master"
        )
        row.rung = 3
        row.save(update_fields=["rung", "updated_at"])
        return evaluate_round(
            self.profile,
            "chess-master",
            CHESS_WIN_L3,
            self.brand,
            self.outlet,
            level=3,
            result="win",
            **CHESS_EFFORT,
        ).coupon

    def test_expiry_is_computed_from_the_rule(self):
        coupon = self._coupon()
        self.assertGreater(coupon.expires_at, timezone.now() + timedelta(days=13))
        self.assertLess(coupon.expires_at, timezone.now() + timedelta(days=15))
        self.assertFalse(coupon.is_expired)

    def test_marking_expired_retires_only_an_issued_coupon(self):
        coupon = self._coupon()
        RewardCoupon.objects.filter(pk=coupon.pk).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        coupon.refresh_from_db()
        self.assertTrue(coupon.is_expired)
        self.assertFalse(coupon.is_usable)
        self.assertEqual(coupon.mark_expired(), RewardCoupon.Status.EXPIRED)

        redeemed = RewardCoupon.objects.create(
            code="KIN-AAAAAA",
            profile=self.profile,
            game_slug="2048",
            tier=RewardTier.GOOD,
            score=1,
            reward_type=RewardType.DESSERT,
            status=RewardCoupon.Status.REDEEMED,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(redeemed.mark_expired(), RewardCoupon.Status.REDEEMED)


class RoundTokenTests(TestCase):
    """A speed bump, not proof: bound to the game and to a short window."""

    def test_a_freshly_signed_token_verifies_for_its_own_game(self):
        token = sign_round_token("2048")
        # age is below the floor right after signing, which is the point
        self.assertFalse(verify_round_token(token, "2048"))
        self.assertTrue(verify_round_token(token, "2048", min_seconds=0))

    def test_a_token_for_another_game_is_refused(self):
        token = sign_round_token("2048")
        self.assertFalse(verify_round_token(token, "chess-master", min_seconds=0))

    def test_garbage_and_missing_tokens_are_refused(self):
        for token in ("", "nope", "a.b.c", None):
            self.assertFalse(verify_round_token(token, "2048", min_seconds=0))

    def test_a_round_faster_than_the_floor_is_refused(self):
        now = timezone.now()
        token = sign_round_token("2048", now=now)
        self.assertFalse(
            verify_round_token(token, "2048", now=now, min_seconds=MIN_ROUND_SECONDS)
        )
        later = now + timedelta(seconds=MIN_ROUND_SECONDS + 1)
        self.assertTrue(verify_round_token(token, "2048", now=later))

    def test_an_old_token_is_refused(self):
        stale = timezone.now() - timedelta(hours=6)
        token = sign_round_token("2048", now=stale)
        self.assertFalse(verify_round_token(token, "2048", min_seconds=0))


class GamesEventRewardTests(RewardFixtures):
    """The wiring: /games/event/ is the only way a coupon is ever issued."""

    def _url(self):
        return reverse("games_event")

    def _round_token(self, slug="chess-master"):
        return sign_round_token(slug, now=timezone.now() - timedelta(seconds=30))

    def _post(self, **overrides):
        payload = {
            "slug": "chess-master",
            "kind": "finished",
            "score": str(CHESS_WIN_L4),
            "qr": self.qr.redirect_key,
            "level": "4",
            "result": "win",
            "duration": str(CHESS_EFFORT["duration"]),
            "actions": str(CHESS_EFFORT["actions"]),
        }
        payload.update(overrides)
        return self.client.post(self._url(), payload)

    def _verify(self, profile):
        """Attach a verified guest to this client (signed identity cookie)."""
        from apps.guests import identity

        self.client.cookies[identity.COOKIE_NAME] = identity.sign_guest_id(
            profile.guest_id
        )
        return profile

    def _verified(self, rung=4, guest_id="wire-guest"):
        profile = GuestProfile.objects.create(
            guest_id=guest_id,
            first_name="Reem",
            last_name="Al Suwaidi",
            phone="+971501234567",
        )
        return self._at_rung(profile, rung)

    def _unverified(self, rung=4, guest_id="wire-guest-anon"):
        profile = GuestProfile.objects.create(
            guest_id=guest_id, first_name="Sam"
        )
        return self._at_rung(profile, rung)

    def _at_rung(self, profile, rung):
        row, _created = RewardProgress.objects.get_or_create(
            profile=profile, game_slug="chess-master"
        )
        row.rung = rung
        row.save(update_fields=["rung", "updated_at"])
        return self._verify(profile)

    def _flap(self, **overrides):
        """A finished Flappy Burger round over the real endpoint."""
        payload = {
            "slug": "flappy-burger",
            "kind": "finished",
            "score": str(FLAPPY_LINE + 5),
            "qr": self.qr.redirect_key,
            "duration": str(FLAPPY_EFFORT["duration"]),
            "actions": str(FLAPPY_EFFORT["actions"]),
            "token": self._round_token("flappy-burger"),
        }
        payload.update(overrides)
        return self.client.post(self._url(), payload)

    def test_a_flappy_round_of_25_pipes_issues_the_dessert_over_http(self):
        """The whole chain: routing, token, cookie, engine, coupon code."""
        self._verified()
        response = self._flap()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["reason"], Reason.ISSUED)
        self.assertEqual(data["reward"]["label"], "Free dessert")
        # the win ticket picks its face from these two facts
        self.assertEqual(data["reward"]["kind"], RewardType.DESSERT)

        coupon = RewardCoupon.objects.get()
        self.assertEqual(coupon.code, data["reward"]["code"])
        self.assertEqual(coupon.game_slug, "flappy-burger")
        self.assertEqual(coupon.reward_type, RewardType.DESSERT)

    def test_a_flappy_round_of_24_pipes_is_refused_over_http(self):
        self._verified()
        data = self._flap(score=str(FLAPPY_LINE - 1)).json()
        self.assertIsNone(data["reward"])
        self.assertEqual(data["reason"], Reason.LOW_SCORE)
        self.assertNotIn("min_score", data["progress"])

    def test_a_flappy_round_without_the_effort_fields_is_refused_over_http(self):
        """duration and actions must arrive, or the effort floor blocks it."""
        self._verified()
        data = self._flap(duration="0", actions="0").json()
        self.assertIsNone(data["reward"])
        self.assertEqual(data["reason"], Reason.EFFORT)
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_a_winning_round_with_a_token_issues_a_coupon(self):
        self._verified()
        response = self._post(token=self._round_token())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIsNotNone(data["reward"])
        self.assertEqual(data["reward"]["label"], "10% off")
        self.assertTrue(data["reward"]["code"])
        self.assertEqual(data["reason"], Reason.ISSUED)
        # the win ticket picks its face from these two facts
        self.assertEqual(data["reward"]["kind"], RewardType.PERCENT)
        self.assertEqual(data["reward"]["percent"], 10)

        coupon = RewardCoupon.objects.get()
        self.assertEqual(coupon.code, data["reward"]["code"])
        self.assertEqual(coupon.brand, self.brand)
        self.assertEqual(coupon.outlet, self.outlet)
        self.assertEqual(coupon.game_slug, "chess-master")

    def test_a_round_below_the_line_issues_nothing_but_still_records(self):
        self._verified(rung=3)
        response = self._post(level="3", score="10", token=self._round_token())
        data = response.json()
        self.assertIsNone(data["reward"])
        self.assertEqual(data["reason"], Reason.LOW_SCORE)
        self.assertEqual(RewardCoupon.objects.count(), 0)
        self.assertEqual(self.brand.game_events.count(), 1)

    def test_a_bare_post_without_a_token_cannot_mint_a_reward(self):
        self._verified()
        response = self._post(score=str(CHESS_WIN_L4))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["reward"])
        self.assertEqual(data["reason"], Reason.TOKEN)
        # the shell is never left with a payload it cannot explain
        self.assertTrue(data["message"])
        self.assertIn("progress", data)
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_a_forged_token_cannot_mint_a_reward(self):
        self._verified()
        response = self._post(token="forged.token.value")
        self.assertIsNone(response.json()["reward"])
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_a_token_for_another_game_cannot_mint_a_reward(self):
        self._verified()
        response = self._post(token=self._round_token("memory-match"))
        self.assertIsNone(response.json()["reward"])
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_played_never_issues_a_reward(self):
        self._verified()
        response = self._post(kind="played", token=self._round_token())
        self.assertIsNone(response.json()["reward"])
        self.assertEqual(RewardCoupon.objects.count(), 0)

    def test_a_second_winning_round_does_not_issue_a_second_coupon(self):
        self._verified()
        first = self._post(token=self._round_token())
        self.assertIsNotNone(first.json()["reward"])
        second = self._post(token=self._round_token())
        self.assertIsNone(second.json()["reward"])
        self.assertEqual(RewardCoupon.objects.count(), 1)

    def test_an_unverified_guest_gets_no_coupon_but_the_climb_counts(self):
        """Being verified gates BEING PAID, never playing (client rule)."""
        self._unverified()
        response = self._post(token=self._round_token())
        data = response.json()
        self.assertIsNone(data["reward"])
        self.assertEqual(data["reason"], Reason.NOT_VERIFIED)
        self.assertFalse(data["verified"])
        self.assertIn("name and mobile", data["message"].lower())
        # the round is on the trail, so verifying later keeps the progress
        self.assertEqual(RewardRound.objects.count(), 1)

    def test_the_response_names_the_prizes_and_the_climb(self):
        self._verified()
        data = self._post(token=self._round_token()).json()
        self.assertEqual(data["progress"]["mode"], "ladder")
        self.assertEqual(data["progress"]["levels"], 4)
        self.assertTrue(data["verified"])

    def test_the_play_page_embeds_a_round_token(self):
        response = self.client.get(reverse("games_play", args=["chess-master"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-token=")
        self.assertNotContains(response, 'data-token=""')

    def test_the_play_page_offers_the_sign_in_prompt_to_an_unverified_guest(self):
        """Before every game start, for a guest who is not verified yet."""
        response = self.client.get(
            reverse("games_play", args=["chess-master"]),
            {"back": "/q/" + self.qr.redirect_key + "/"},
        )
        self.assertContains(response, 'id="game-nudge"')
        self.assertContains(response, "Win a discount or a free dessert")

    def test_the_play_page_has_no_prompt_once_the_guest_is_verified(self):
        self._verified()
        response = self.client.get(reverse("games_play", args=["chess-master"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="game-nudge"')

    def test_the_play_page_publishes_where_the_guest_stands(self):
        self._verified(rung=2)
        response = self.client.get(reverse("games_play", args=["chess-master"]))
        self.assertContains(response, 'id="games-progress"')
        self.assertContains(response, '"rung": 2')


class PanelRewardTests(ProfileRewardFixtures):
    """The panel surface: the coupon list and the once-only redeem."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.head_office = User.objects.create_user("ho-rewards", password="pw-ho-12345")
        cls.head_office.is_staff = True
        cls.head_office.save(update_fields=["is_staff"])

    def _coupon(self, **overrides):
        data = {
            "code": "KIN-ABC123",
            "profile": self.profile,
            "brand": self.brand,
            "outlet": self.outlet,
            "game_slug": "2048",
            "tier": RewardTier.GOOD,
            "score": 1000,
            "reward_type": RewardType.DESSERT,
            "expires_at": timezone.now() + timedelta(days=14),
        }
        data.update(overrides)
        return RewardCoupon.objects.create(**data)

    def test_the_coupon_pages_need_a_staff_login(self):
        for name in ("panel_rewards", "panel_guests"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/panel/login/", response["Location"])

    def test_head_office_sees_the_coupon_list(self):
        self._coupon()
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_rewards"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KIN-ABC123")
        self.assertContains(response, "Free dessert")

    def test_redeeming_flips_the_coupon_once(self):
        coupon = self._coupon()
        self.client.force_login(self.head_office)

        response = self.client.post(
            reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "redeemed")

        coupon.refresh_from_db()
        self.assertEqual(coupon.status, RewardCoupon.Status.REDEEMED)
        self.assertEqual(coupon.redeemed_by, self.head_office)
        self.assertIsNotNone(coupon.redeemed_at)

    def test_a_second_redeem_is_refused_and_changes_nothing(self):
        coupon = self._coupon()
        self.client.force_login(self.head_office)
        self.client.post(reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True)
        coupon.refresh_from_db()
        first_moment = coupon.redeemed_at

        response = self.client.post(
            reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True
        )
        self.assertContains(response, "cannot be redeemed")
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, RewardCoupon.Status.REDEEMED)
        self.assertEqual(coupon.redeemed_at, first_moment)

    def test_an_expired_coupon_cannot_be_redeemed(self):
        coupon = self._coupon(expires_at=timezone.now() - timedelta(days=1))
        self.client.force_login(self.head_office)
        self.client.post(reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True)
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, RewardCoupon.Status.EXPIRED)
        self.assertIsNone(coupon.redeemed_at)

    def test_the_list_retires_expired_coupons_on_sight(self):
        coupon = self._coupon(expires_at=timezone.now() - timedelta(days=1))
        self.client.force_login(self.head_office)
        self.client.get(reverse("panel_rewards"))
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, RewardCoupon.Status.EXPIRED)

    def test_the_code_filter_finds_what_staff_typed(self):
        self._coupon(code="KIN-ZZ9ZZ9")
        self._coupon(code="KIN-AAAAAA", profile=self.profile)
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_rewards"), {"code": "zz9zz9"})
        self.assertContains(response, "KIN-ZZ9ZZ9")
        self.assertNotContains(response, "KIN-AAAAAA")

    def test_a_redeemed_coupon_offers_no_redeem_button(self):
        coupon = self._coupon(status=RewardCoupon.Status.REDEEMED)
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_rewards"), {"status": "all"})
        self.assertContains(response, "KIN-ABC123")
        self.assertNotContains(response, reverse("panel_coupon_redeem", args=[coupon.pk]))

    def test_a_branch_manager_only_sees_their_own_branch(self):
        from apps.core.models import Brand, Outlet
        from apps.core.panel_permissions import apply_role_to_user

        mine = self._coupon(code="KIN-MINE01")
        other_brand = Brand.objects.create(
            name_en="Other Brand", code="OTHER-RW", status="active"
        )
        other_outlet = Outlet.objects.create(
            code="OTHER-RW-1",
            slug="other-rewards-branch",
            official_name="Other Branch",
            brand=other_brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        theirs = self._coupon(code="KIN-THEIR1", brand=other_brand, outlet=other_outlet)

        manager = User.objects.create_user("branch-rewards", password="pw-br-12345")
        apply_role_to_user(manager, "outlet_manager", None, [self.outlet])
        self.client.force_login(manager)

        response = self.client.get(reverse("panel_rewards"), {"status": "all"})
        self.assertContains(response, mine.code)
        self.assertNotContains(response, theirs.code)

        # and cannot redeem outside their own branch
        refused = self.client.post(reverse("panel_coupon_redeem", args=[theirs.pk]))
        self.assertEqual(refused.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, RewardCoupon.Status.ISSUED)

    def test_a_branch_manager_redeems_a_coupon_from_their_own_branch(self):
        from apps.core.panel_permissions import apply_role_to_user

        coupon = self._coupon()
        manager = User.objects.create_user("branch-redeem", password="pw-br-12345")
        apply_role_to_user(manager, "outlet_manager", None, [self.outlet])
        self.client.force_login(manager)

        self.client.post(reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True)
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, RewardCoupon.Status.REDEEMED)
        self.assertEqual(coupon.redeemed_by, manager)

    def test_staff_find_a_guest_by_the_mobile_they_typed(self):
        coupon = self._coupon(code="KIN-MOBILE")
        self.client.force_login(self.head_office)
        response = self.client.get(
            reverse("panel_rewards"), {"mobile": "050 123 4567", "status": "all"}
        )
        self.assertContains(response, "Reem Al Suwaidi")
        self.assertContains(response, coupon.code)
        self.assertContains(response, "+971501234567")

    def test_a_mobile_search_hides_every_other_guest(self):
        self._coupon(code="KIN-MINE99")
        other = GuestProfile.objects.create(
            guest_id="other-mobile",
            first_name="Omar",
            last_name="Hassan",
            phone="+971509990099",
        )
        self._coupon(code="KIN-OTHER9", profile=other)
        self.client.force_login(self.head_office)
        response = self.client.get(
            reverse("panel_rewards"), {"mobile": "0501234567", "status": "all"}
        )
        self.assertContains(response, "KIN-MINE99")
        self.assertNotContains(response, "KIN-OTHER9")
        self.assertNotContains(response, "Omar Hassan")

    def test_an_unknown_mobile_shows_nobody(self):
        self._coupon()
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_rewards"), {"mobile": "0509999999"})
        self.assertContains(response, "No guest found")
        self.assertNotContains(response, "KIN-ABC123")

    def test_a_branch_manager_cannot_find_another_branch_by_mobile(self):
        from apps.core.models import Brand, Outlet
        from apps.core.panel_permissions import apply_role_to_user

        other_brand = Brand.objects.create(
            name_en="Hidden Brand", code="HIDDEN-RW", status="active"
        )
        other_outlet = Outlet.objects.create(
            code="HIDDEN-RW-1",
            slug="hidden-rewards-branch",
            official_name="Hidden Branch",
            brand=other_brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        hidden = GuestProfile.objects.create(
            guest_id="hidden-guest",
            first_name="Noor",
            last_name="Ali",
            phone="+971501111111",
        )
        self._coupon(
            code="KIN-HIDDEN",
            profile=hidden,
            brand=other_brand,
            outlet=other_outlet,
        )
        manager = User.objects.create_user("branch-lookup", password="pw-br-12345")
        apply_role_to_user(manager, "outlet_manager", None, [self.outlet])
        self.client.force_login(manager)

        response = self.client.get(
            reverse("panel_rewards"), {"mobile": "0501111111", "status": "all"}
        )
        self.assertNotContains(response, "KIN-HIDDEN")
        self.assertNotContains(response, "Noor Ali")

    def test_totals_count_redeemed_desserts_and_discounts_only(self):
        self._coupon(
            code="KIN-DESERT",
            status=RewardCoupon.Status.REDEEMED,
            reward_type=RewardType.DESSERT,
        )
        self._coupon(
            code="KIN-TENOFF",
            status=RewardCoupon.Status.REDEEMED,
            reward_type=RewardType.PERCENT,
            percent=10,
        )
        self._coupon(code="KIN-WAITING", reward_type=RewardType.DESSERT)
        self.client.force_login(self.head_office)
        response = self.client.get(reverse("panel_rewards"), {"status": "all"})
        self.assertContains(response, "Desserts given")
        self.assertContains(response, "Discounts given")
        self.assertContains(response, "10% points in total")

    def test_a_branch_managers_totals_exclude_another_branch(self):
        from apps.core.models import Brand, Outlet
        from apps.core.panel_permissions import apply_role_to_user

        self._coupon(
            code="KIN-OURS01",
            status=RewardCoupon.Status.REDEEMED,
            reward_type=RewardType.DESSERT,
        )
        other_brand = Brand.objects.create(
            name_en="Far Brand", code="FAR-RW", status="active"
        )
        other_outlet = Outlet.objects.create(
            code="FAR-RW-1",
            slug="far-rewards-branch",
            official_name="Far Branch",
            brand=other_brand,
            opening_hours=_hours_open_all_day(),
            active=True,
        )
        self._coupon(
            code="KIN-THEIRS",
            status=RewardCoupon.Status.REDEEMED,
            reward_type=RewardType.PERCENT,
            percent=10,
            brand=other_brand,
            outlet=other_outlet,
        )
        manager = User.objects.create_user("branch-totals", password="pw-br-12345")
        apply_role_to_user(manager, "outlet_manager", None, [self.outlet])
        self.client.force_login(manager)

        response = self.client.get(reverse("panel_rewards"), {"status": "all"})
        self.assertContains(response, "KIN-OURS01")
        self.assertNotContains(response, "KIN-THEIRS")
        self.assertContains(response, "0% points in total")

    def test_redeeming_is_written_to_the_change_log(self):
        from apps.core.models import ChangeLog

        coupon = self._coupon()
        self.client.force_login(self.head_office)
        self.client.post(reverse("panel_coupon_redeem", args=[coupon.pk]), follow=True)
        entry = ChangeLog.objects.get(action="reward_redeem")
        self.assertEqual(entry.user, self.head_office)
        self.assertEqual(entry.brand, self.brand)
        self.assertIn(coupon.code, entry.object_repr)
