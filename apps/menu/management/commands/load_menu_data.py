"""
Load a verified outlet menu dataset (JSON) into the database.

The dataset is produced from the outlet's real menu PDF (see the extraction
pipeline notes in the session log): real dish names and printed prices only.
Rows whose price could not be read are listed under "review_no_price" and are
NOT loaded — staff enter those through the panel after checking the PDF.

Usage:
    python manage.py load_menu_data apps/menu/data/menu_kingchef_intlcity.json

Idempotent: categories and items are keyed by (brand, outlet, name) and
updated in place. Item images are looked up in media/menu/items/ by the
"image" filename recorded in the dataset.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Outlet
from apps.menu.models import MenuCategory, MenuItem


class Command(BaseCommand):
    help = "Load a verified outlet menu dataset (JSON) into the database."

    def add_arguments(self, parser):
        parser.add_argument("dataset", help="path to the menu dataset JSON")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="report what would change without writing",
        )

    def handle(self, *args, **options):
        path = Path(options["dataset"])
        if not path.exists():
            raise CommandError(f"dataset not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        try:
            outlet = Outlet.objects.get(code=data["outlet"])
        except Outlet.DoesNotExist:
            raise CommandError(f"unknown outlet code: {data['outlet']}")
        brand = outlet.brand

        review = data.get("review_no_price", [])
        if review:
            self.stdout.write(self.style.WARNING(
                f"{len(review)} rows have no readable price and were not loaded "
                f"(staff should add them via the panel)."
            ))

        created = updated = 0
        with transaction.atomic():
            for cat_name, blk in sorted(
                data["categories"].items(), key=lambda kv: kv[1]["sort"]
            ):
                category, cat_created = MenuCategory.objects.update_or_create(
                    brand=brand,
                    outlet=outlet,
                    name_en=cat_name,
                    defaults={"sort_order": blk["sort"], "active": True},
                )
                for idx, spec in enumerate(blk["items"]):
                    image = spec.get("image") or ""
                    item, item_created = MenuItem.objects.update_or_create(
                        category=category,
                        brand=brand,
                        outlet=outlet,
                        name_en=spec["name"],
                        defaults={
                            "description_en": spec.get("desc", ""),
                            "regular_price": spec["price"],
                            "currency": "AED",
                            "dietary_type": spec.get(
                                "dietary_type", MenuItem.DietaryType.NON_VEG
                            ),
                            "available": True,
                            "sort_order": idx,
                            "image": f"menu/items/{image}" if image else "",
                        },
                    )
                    if item_created:
                        created += 1
                    else:
                        updated += 1
                self.stdout.write(
                    f"  {cat_name} (sort {blk['sort']}): {len(blk['items'])} items"
                )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return
        self.stdout.write(self.style.SUCCESS(
            f"{data['outlet']}: {created} created, {updated} updated."
        ))
