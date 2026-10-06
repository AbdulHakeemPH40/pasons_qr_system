"""Keep the three spec games present. Rewards stay a seed/admin choice."""

from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.kidsplay.management.commands.seed_kidsplay import GAMES
from apps.kidsplay.models import PlayGame, PointsTier


@receiver(post_migrate)
def ensure_games(sender, **kwargs):
    if sender.label != "kidsplay":
        return
    for spec in GAMES:
        tiers = spec["tiers"]
        defaults = {key: value for key, value in spec.items() if key not in ("tiers", "slug")}
        game, _ = PlayGame.objects.update_or_create(slug=spec["slug"], defaults=defaults)
        for min_score, points in tiers:
            PointsTier.objects.update_or_create(
                game=game, min_score=min_score, defaults={"points": points}
            )
