"""
Create the staff panel accounts.

  - 1 All-brands user   every brand on the same dashboard
  - 13 Branch users     one per branch
  - 3 Head Office       IT and Admin, Operations, Marketing (optional)

Every account is written through ``panel_permissions.apply_role_to_user``, the
same function the Users panel calls, so a seeded account behaves exactly like
one created by hand.

Idempotent and safe:
  - ``--dry-run`` prints exactly what would happen and writes nothing.
  - A second real run creates nothing and changes no password. An existing
    account keeps its password; only its email, display name and scope are
    refreshed, so this table stays the source of truth for who sees what.

Passwords are generated with ``secrets`` and printed once, to be handed over
out of band. Nothing secret is written into the repository.

The four open decisions are flags, so a change of mind needs no code change:
  --domain           email domain (default pasonsgrp.com)
  --style a|b        a: bm./om./ho. prefixes   b: manager. prefixes
  --brands           limit to these codes, so PARAMOUNT can be left out with
                     --brands KINGCHEF,MILANVEG,DONARIST
  --reset-passwords  issue fresh passwords for accounts that already exist
  --password         testing only: give every account this same password
"""

import secrets

from django.contrib.auth.models import Group as AuthGroup, User
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Brand, Department, Outlet
from apps.core.panel_permissions import apply_role_to_user, scoped_outlets

# The five Head Office functions. Migration core.0007 seeds the same rows; the
# list is repeated here so the command also works on a database that predates
# that migration.
DEPARTMENTS = [
    ("MARKETING", "Marketing", "\u0627\u0644\u062a\u0633\u0648\u064a\u0642"),
    ("OPERATIONS", "Operations", "\u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a"),
    ("FINANCE", "Finance", "\u0627\u0644\u0645\u0627\u0644\u064a\u0629"),
    ("HR", "HR", "\u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0627\u0644\u0628\u0634\u0631\u064a\u0629"),
    ("IT", "IT and Admin", "\u062a\u0642\u0646\u064a\u0629 \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0627\u062a"),
]

# Head Office accounts: (username, email local part, department code).
# The username carries the ho. prefix, the address does not, matching the
# account plan (ho.admin / admin@pasongrp.com).
HEAD_OFFICE = [
    ("ho.admin", "admin", "IT"),
    ("ho.ops", "ops", "OPERATIONS"),
    ("ho.marketing", "marketing", "MARKETING"),
]

HEAD_OFFICE_GROUP = "Head office"

DEPARTMENT_NAMES = {code: name_en for code, name_en, _ in DEPARTMENTS}


class Command(BaseCommand):
    help = (
        "Create the staff panel accounts (1 all-brands user, one user per "
        "branch, optional head office) and the departments. Idempotent; "
        "--dry-run prints without writing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print exactly what would be created and write nothing.",
        )
        parser.add_argument(
            "--domain",
            default="pasonsgrp.com",
            help="Email domain for every account (default pasonsgrp.com).",
        )
        parser.add_argument(
            "--style",
            choices=["a", "b"],
            default="a",
            help="a: bm./om./ho. prefixes (default). b: manager. prefixes.",
        )
        parser.add_argument(
            "--brands",
            default="",
            help=(
                "Comma-separated brand codes to include, for example "
                "KINGCHEF,MILANVEG,DONARIST. Default: every active brand."
            ),
        )
        parser.add_argument(
            "--no-head-office",
            action="store_true",
            help="Skip the three Head Office accounts.",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Issue fresh passwords for accounts that already exist.",
        )
        parser.add_argument(
            "--password",
            default="",
            help="Testing only: give every account this same password.",
        )

    # ------------------------------------------------------------------ handle
    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        style = options["style"]
        domain = (options["domain"] or "").strip().lstrip("@") or "pasonsgrp.com"
        shared_password = options["password"]
        codes = {
            code.strip().upper()
            for code in (options["brands"] or "").split(",")
            if code.strip()
        }

        departments = self._ensure_departments(create=not self.dry_run)
        rows = self._build_rows(style, domain, codes, options)

        if not rows:
            self.stdout.write(self.style.WARNING("No accounts to create. Nothing to do."))
            return

        self._warn_on_email_conflicts(rows)

        if self.dry_run:
            self._print_plan(rows, domain, style)
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: nothing was written. Re-run without --dry-run to apply."
                )
            )
            return

        results = self._apply(rows, departments, shared_password, options["reset_passwords"])
        self._print_report(results, domain, style, shared_password)

    # -------------------------------------------------------------- departments
    def _ensure_departments(self, create):
        """Department rows by code.

        ``create`` is False during a dry run, which must not write, so a
        missing row is left absent and the label falls back to the constant
        above. Migration core.0007 seeds all five anyway.
        """
        departments = {}
        for code, name_en, name_ar in DEPARTMENTS:
            if create:
                department, _ = Department.objects.get_or_create(
                    code=code, defaults={"name_en": name_en, "name_ar": name_ar}
                )
            else:
                department = Department.objects.filter(code=code).first()
            departments[code] = department
        return departments

    # -------------------------------------------------------------------- rows
    def _names(self, kind, slug, style):
        """(username, email local part) for one manager account."""
        if style == "b":
            local = slug.replace("-", "_")
            return f"manager.{local}", f"manager.{local}"
        prefix = {"brand": "bm", "outlet": "om"}[kind]
        return f"{prefix}.{slug}", f"{prefix}.{slug}"

    def _build_rows(self, style, domain, codes, options):
        rows = []

        brands = Brand.objects.filter(status="active").order_by("code")
        if codes:
            brands = brands.filter(code__in=codes)

        rows.append(
            {
                "role": "brand_manager",
                "username": "brand_manager",
                "email": f"brand_manager@{domain}",
                "name": "All brands",
                "brand": None,
                "outlet": None,
                "department_code": None,
                "scope": "every brand, same dashboard",
            }
        )

        for brand in brands:
            outlets = Outlet.objects.filter(brand=brand, active=True).order_by("code")
            for outlet in outlets:
                username, local = self._names("outlet", outlet.code.lower(), style)
                rows.append(
                    {
                        "role": "outlet_manager",
                        "username": username,
                        "email": f"{local}@{domain}",
                        "name": outlet.official_name,
                        "brand": brand,
                        "outlet": outlet,
                        "department_code": None,
                        "scope": outlet.official_name,
                    }
                )

        if not options["no_head_office"]:
            for username, function, code in HEAD_OFFICE:
                if code not in DEPARTMENT_NAMES:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Unknown department {code}; skipping {username}."
                        )
                    )
                    continue
                rows.append(
                    {
                        "role": "head_office",
                        "username": username,
                        "email": f"{function}@{domain}",
                        "name": f"Head Office \u00b7 {DEPARTMENT_NAMES[code]}",
                        "brand": None,
                        "outlet": None,
                        "department_code": code,
                        "scope": f"department {DEPARTMENT_NAMES[code]}",
                    }
                )

        return rows

    def _warn_on_email_conflicts(self, rows):
        """An address shared with a different account breaks email sign-in."""
        for row in rows:
            clashes = User.objects.filter(email__iexact=row["email"]).exclude(
                username=row["username"]
            )
            other = clashes.first()
            if other is not None:
                self.stderr.write(
                    self.style.WARNING(
                        f"Warning: {row['email']} is already used by "
                        f"'{other.username}'. Email sign-in would be ambiguous."
                    )
                )

    # ------------------------------------------------------------------- apply
    def _apply(self, rows, departments, shared_password, reset_passwords):
        head_office_group, _ = AuthGroup.objects.get_or_create(name=HEAD_OFFICE_GROUP)
        results = []

        with transaction.atomic():
            for row in rows:
                user = User.objects.filter(username=row["username"]).first()
                is_new = user is None
                password = None

                if is_new:
                    password = shared_password or secrets.token_urlsafe(12)
                    user = User.objects.create_user(
                        username=row["username"],
                        email=row["email"],
                        password=password,
                    )
                else:
                    if row["email"] and user.email != row["email"]:
                        user.email = row["email"]
                        user.save(update_fields=["email"])
                    if shared_password:
                        password = shared_password
                        user.set_password(password)
                        user.save(update_fields=["password"])
                    elif reset_passwords:
                        password = secrets.token_urlsafe(12)
                        user.set_password(password)
                        user.save(update_fields=["password"])

                user.first_name = row["name"][:150]
                user.is_active = True
                user.save(update_fields=["first_name", "is_active"])

                apply_role_to_user(
                    user,
                    row["role"],
                    row["brand"],
                    [row["outlet"]] if row["outlet"] else [],
                    departments.get(row["department_code"]),
                )
                if row["role"] == "head_office":
                    user.groups.add(head_office_group)

                results.append({**row, "user": user, "new": is_new, "password": password})

        return results

    # ----------------------------------------------------------------- printing
    def _print_plan(self, rows, domain, style):
        self.stdout.write(f"Email domain: {domain}    username style: {style.upper()}\n")
        width = max(len(r["username"]) for r in rows)
        self.stdout.write("ROLE            USERNAME".ljust(width + 18) + "SCOPE")
        self.stdout.write("-" * (width + 52))
        for row in rows:
            exists = User.objects.filter(username=row["username"]).exists()
            marker = "refresh" if exists else "create "
            role = row["role"].replace("_", " ").title()
            self.stdout.write(
                f"{role:<15} {row['username']:<{width}} {marker}  {row['scope']}"
            )
        self.stdout.write("")
        self.stdout.write(
            f"{len(rows)} accounts in total "
            f"({sum(1 for r in rows if r['role'] == 'brand_manager')} brand, "
            f"{sum(1 for r in rows if r['role'] == 'outlet_manager')} outlet, "
            f"{sum(1 for r in rows if r['role'] == 'head_office')} head office)."
        )

    def _print_report(self, results, domain, style, shared_password):
        created = [r for r in results if r["new"]]
        refreshed = [r for r in results if not r["new"]]

        self.stdout.write(f"Email domain: {domain}    username style: {style.upper()}")
        self.stdout.write(
            f"Created {len(created)} account(s), refreshed {len(refreshed)}.\n"
        )
        self.stdout.write("ROLE            USERNAME                     OUTLETS IN SCOPE")
        self.stdout.write("-" * 76)
        for row in results:
            outlets = scoped_outlets(row["user"]).count()
            role = row["role"].replace("_", " ").title()
            self.stdout.write(
                f"{role:<15} {row['username']:<28} {outlets}"
            )

        issued = [r for r in results if r["password"]]
        if issued:
            self.stdout.write("")
            if shared_password:
                self.stdout.write(
                    self.style.WARNING(
                        "Every account uses the SAME password (--password). "
                        "Testing only: never do this on the live site."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "PASSWORDS below are shown once. Hand them over out of "
                        "band, then clear this output. They are not stored in "
                        "the repository."
                    )
                )
            for row in issued:
                self.stdout.write(f"  {row['username']:<28} {row['password']}")

        self.stdout.write("")
        self.stdout.write(
            "Note: Head Office accounts are is_staff=True, exactly as the Users\n"
            "panel sets them, which also opens Django /admin/ (they hold no model\n"
            "permissions there, so the admin index is empty). They are also in the\n"
            f"'{HEAD_OFFICE_GROUP}' group, so panel access survives if is_staff is\n"
            "ever switched off (open decision Q3)."
        )
        self.stdout.write(self.style.SUCCESS("Staff accounts ready."))
