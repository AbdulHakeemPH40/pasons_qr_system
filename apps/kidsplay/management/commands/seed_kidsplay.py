"""Create the three games, their point tiers, and four sample rewards.

Does not invent tables. Printed QR codes already live in apps.core.QrCode.
"""

from django.core.management.base import BaseCommand

from apps.kidsplay.models import PlayGame, PointsTier, Reward


GAMES = [
    {
        "slug": "burger-stack",
        "title": "Burger Stack",
        "description": "Drop the layers. Keep the tower standing.",
        "icon": "burger",
        "sort_order": 1,
        "min_duration_ms": 5000,
        "max_duration_ms": 600000,
        "max_score": 150,
        "max_score_per_second": 2.5,
        "tiers": [(1, 5), (10, 10), (25, 20), (50, 30)],
    },
    {
        "slug": "food-catcher",
        "title": "Food Catcher",
        "description": "Catch the good food. Dodge the shoes.",
        "icon": "plate",
        "sort_order": 2,
        "min_duration_ms": 5000,
        "max_duration_ms": 600000,
        "max_score": 200,
        "max_score_per_second": 3.5,
        "tiers": [(5, 5), (20, 10), (40, 20), (70, 30)],
    },
    {
        "slug": "memory-match",
        "title": "Memory Match",
        "description": "Find the matching plates.",
        "icon": "cards",
        "sort_order": 3,
        "min_duration_ms": 8000,
        "max_duration_ms": 600000,
        "max_score": 3000,
        "max_score_per_second": 150,
        "tiers": [(100, 5), (500, 10), (1000, 20), (1800, 30)],
    },
]

REWARDS = [
    ("Free ice cream scoop", 80),
    ("Kids' drink", 40),
    ("Small toy", 150),
    ("Fruit cup", 60),
]


class Command(BaseCommand):
    help = "Seed KidsPlay games, point tiers, and sample rewards."

    def handle(self, *args, **options):
        for spec in GAMES:
            tiers = spec["tiers"]
            defaults = {key: value for key, value in spec.items() if key != "tiers"}
            game, _ = PlayGame.objects.update_or_create(slug=spec["slug"], defaults=defaults)
            for min_score, points in tiers:
                PointsTier.objects.update_or_create(
                    game=game, min_score=min_score, defaults={"points": points}
                )
            self.stdout.write(f"game {game.slug}")
        for title, cost in REWARDS:
            Reward.objects.update_or_create(
                title=title, outlet=None, defaults={"cost_points": cost, "is_active": True}
            )
            self.stdout.write(f"reward {title}")
        self.stdout.write(self.style.SUCCESS("KidsPlay seed complete."))
