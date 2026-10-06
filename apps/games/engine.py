"""
Game Engine and Concurrency-Safe Reward Allocation.
Spec Part C.5: Dish Match game result evaluation, device throttling,
and transactional reward allocation tied strictly to the QR outlet.
"""

import hashlib
import random
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.games.models import Game, Reward


def get_device_hash(request):
    ip = request.META.get("REMOTE_ADDR", "")
    ua = request.META.get("HTTP_USER_AGENT", "")
    raw = f"{settings.SECRET_KEY}:{ip}:{ua}"
    return hashlib.sha256(raw.encode()).hexdigest()


def resolve_active_game(brand, outlet=None):
    """
    Priority: Outlet override game -> Brand default game -> None.
    """
    if outlet:
        outlet_game = Game.objects.filter(outlet=outlet, enabled=True).first()
        if outlet_game and outlet_game.is_live:
            return outlet_game

    brand_game = Game.objects.filter(brand=brand, outlet__isnull=True, enabled=True).first()
    if brand_game and brand_game.is_live:
        return brand_game
    return None


def evaluate_game_submission(game, outlet, qr_code, moves, time_seconds, device_hash, session_key=""):
    """
    Evaluate player completion:
    - Verifies plausible moves and time
    - Checks max_winners, daily_limit, per_device_daily_limit
    - Rolls win_probability
    - Transactionally creates a Reward with unique coupon code
    Returns: (won: bool, reward: Reward or None, message: str)
    """
    if not game or not game.is_live:
        return False, None, "Game is currently not active."

    # Anti-cheat check: min plausible moves (for 6 pairs, min 6 moves, typically >=8)
    if moves < 6 or time_seconds < 4:
        return False, None, "Game finished suspiciously fast."

    today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)

    # Concurrency safe execution
    with transaction.atomic():
        # Lock game row for update to prevent race conditions on max_winners
        locked_game = Game.objects.select_for_update().get(pk=game.pk)

        # 1. Check total max winners
        total_won = Reward.objects.filter(game=locked_game).count()
        if total_won >= locked_game.max_winners:
            return False, None, "All available discount rewards for this campaign have been claimed."

        # 2. Check daily limit
        daily_won = Reward.objects.filter(
            game=locked_game,
            issued_at__gte=today_start
        ).count()
        if daily_won >= locked_game.daily_limit:
            return False, None, "Daily limit of rewards reached. Please try again tomorrow!"

        # 3. Check per-device daily limit
        if device_hash:
            device_count = Reward.objects.filter(
                game=locked_game,
                device_hash=device_hash,
                issued_at__gte=today_start
            ).count()
            if device_count >= locked_game.per_device_daily_limit:
                return False, None, "You have already won a reward today! Try again tomorrow."

        # 4. Probability roll
        roll = random.random()
        if roll > locked_game.win_probability:
            return False, None, "Great effort! Better luck next time."

        # 5. Create Reward
        prefix = locked_game.coupon_prefix or "WIN"
        coupon_code = Reward.generate_code(prefix)

        # Ensure uniqueness
        while Reward.objects.filter(coupon_code=coupon_code).exists():
            coupon_code = Reward.generate_code(prefix)

        if locked_game.reward_type == Game.RewardType.PERCENT:
            reward_value = f"{locked_game.discount_percent}% OFF"
        else:
            reward_value = f"{locked_game.coupon_amount:.0f} AED OFF"

        expires_at = timezone.now() + timedelta(days=locked_game.voucher_valid_days)

        reward = Reward.objects.create(
            game=locked_game,
            outlet=outlet,  # strictly tied to QR outlet
            qr_code=qr_code,
            reward_type=locked_game.reward_type,
            reward_value=reward_value,
            coupon_code=coupon_code,
            expires_at=expires_at,
            device_hash=device_hash,
            session_key=session_key,
            status=Reward.Status.ISSUED
        )

        return True, reward, "Congratulations! You won a dining voucher."
