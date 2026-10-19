"""
Create the staff panel accounts from the client's account sheet (a CSV).

The sheet is the handover document: one row per person, with the role, the
username, the email, the password and the scope written in the client's own
words ("All brands", "King Chef, Al Quoz"). This command turns that sheet
into real accounts, so nobody has to retype fifteen rows by hand and get one
of them wrong.

Expected columns (header row required, order does not matter):

    Role, Username, Email, Password, Brand, Branch

Role values understood:
    Superuser   -> is_superuser + is_staff, no scoped manager profile
    Brand user  -> brand manager, one brand, or every brand when the sheet
                   says "All brands"
    Branch user -> outlet manager, limited to the branches on that row

Two rules make this safe to run on a live server:

  * All or nothing. Every row is resolved before anything is written. One
    unknown branch stops the whole import with a clear message, so a typo in
    the sheet cannot leave half the staff with accounts and half without.
  * Idempotent. A second run creates nothing. Existing accounts are refreshed
    to the sheet's scope and email, and their password is left alone unless
    ``--passwords always`` is passed.

The sheet holds plain text passwords, so it must never be committed. Pass it
by path, run the import, then delete the file from the server.

Usage:
    python manage.py import_staff_csv Docs/panel_accounts.csv --dry-run
    python manage.py import_staff_csv Docs/panel_accounts.csv
    python manage.py import_staff_csv /tmp/staff.csv --passwords always
"""

import csv
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Brand, Outlet
from apps.core.panel_permissions import apply_role_to_user, scoped_outlets

ROLE_SUPERUSER = "superuser"
ROLE_BRAND = "brand_manager"
ROLE_OUTLET = "outlet_manager"

# The sheet's wording mapped to the three things an account can be. Only the
# first word matters, so "Brand user" and "Brand manager" both land here.
ROLE_WORDS = {
    "superuser": ROLE_SUPERUSER,
    "admin": ROLE_SUPERUSER,
    "brand": ROLE_BRAND,
    "branch": ROLE_OUTLET,
    "outlet": ROLE_OUTLET,
}

ALL_BRANDS_WORDS = {"", "all", "all brands", "every brand", "every brands"}
ALL_BRANCHES_WORDS = {"", "all", "all branches", "every branch", "every branches"}

REQUIRED_COLUMNS = ("role", "username", "email", "password", "brand", "branch")


def _norm(text):
    """Fold a scope label so the sheet and the database can be compared.

    The sheet writes "King Chef, Al Quoz"; the database stores
    "King Chef — Al Quoz". Commas, em dashes and en dashes all become a
    space, then whitespace is collapsed, so the two read the same.
    """
    text = (text or "").lower()
    for char in ("\u2014", "\u2013", ",", ".", "_"):
        text = text.replace(char, " ")
    text = text.replace("-", " ")
    return " ".join(text.split())


class Command(BaseCommand):
    help = (
        "Create or refresh staff panel accounts from the client's CSV "
        "(Role, Username, Email, Password, Brand, Branch). Idempotent; "
        "--dry-run prints without writing."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the account sheet (CSV).")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Resolve every row and print the plan, writing nothing.",
        )
        parser.add_argument(
            "--passwords",
            choices=["create", "always", "never"],
            default="create",
            help=(
                "create: set the sheet's password only on new accounts "
                "(default). always: reset every account to the sheet's "
                "password. never: create accounts with an unusable password."
            ),
        )

    # ------------------------------------------------------------------ handle
    def handle(self, *args, **options):
        path = Path(options["csv_path"]).expanduser()
        if not path.is_file():
            raise CommandError(f"No such file: {path}")

        rows = self._read_sheet(path)
        planned = [self._resolve(row, index) for index, row in enumerate(rows, start=2)]

        self._reject_duplicates(planned)

        if options["dry_run"]:
            self._print_plan(planned)
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: nothing was written. Re-run without --dry-run to apply."
                )
            )
            return

        results = self._apply(planned, options["passwords"])
        self._print_report(results)

    # --------------------------------------------------------------- the sheet
    def _read_sheet(self, path):
        """Rows of the sheet, with the header folded to lower case."""
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                headers = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
                missing = [c for c in REQUIRED_COLUMNS if c not in headers]
                if missing:
                    raise CommandError(
                        f"{path.name} is missing column(s): {', '.join(missing)}. "
                        f"Expected: {', '.join(c.title() for c in REQUIRED_COLUMNS)}."
                    )
                rows = []
                for raw in reader:
                    row = {
                        (key or "").strip().lower(): (value or "").strip()
                        for key, value in raw.items()
                    }
                    # A blank line at the end of the sheet is not a person.
                    if any(row.get(c) for c in ("username", "email", "role")):
                        rows.append(row)
        except UnicodeDecodeError as exc:
            raise CommandError(f"{path.name} is not valid UTF-8: {exc}") from exc

        if not rows:
            raise CommandError(f"{path.name} has a header but no account rows.")
        return rows

    # --------------------------------------------------------------- resolving
    def _resolve(self, row, line):
        """Turn one sheet row into a plan of exactly what will be written."""
        username = row.get("username", "")
        role_word = (row.get("role") or "").split()[0].lower() if row.get("role") else ""
        role = ROLE_WORDS.get(role_word)
        if not username:
            raise CommandError(f"Line {line}: no username.")
        if role is None:
            raise CommandError(
                f"Line {line}: unknown role {row.get('role')!r}. "
                f"Use Superuser, Brand user or Branch user."
            )

        plan = {
            "line": line,
            "username": username,
            "email": row.get("email", ""),
            "password": row.get("password", ""),
            "role": role,
            "brand": None,
            "outlets": [],
            "scope": "",
        }

        if role == ROLE_SUPERUSER:
            plan["scope"] = "every brand and branch (Django admin)"
            return plan

        if role == ROLE_BRAND:
            plan["brand"] = self._resolve_brand(row.get("brand", ""), line)
            plan["scope"] = (
                plan["brand"].name_en if plan["brand"] else "every brand, same dashboard"
            )
            return plan

        outlet = self._resolve_outlet(row, username, line)
        plan["outlets"] = [outlet]
        plan["scope"] = outlet.official_name
        return plan

    def _resolve_brand(self, label, line):
        """None means every brand, which is a real scope, not a missing value."""
        if _norm(label) in ALL_BRANDS_WORDS:
            return None
        brand = Brand.objects.filter(name_en__iexact=label).first()
        if brand is None:
            brand = Brand.objects.filter(code__iexact=label).first()
        if brand is None:
            known = ", ".join(Brand.objects.order_by("code").values_list("name_en", flat=True))
            raise CommandError(
                f"Line {line}: brand {label!r} does not exist. Known brands: {known}."
            )
        return brand

    def _resolve_outlet(self, row, username, line):
        """Find the branch a branch user row belongs to.

        The username carries the branch code after its prefix (br.kingchef-alquoz
        is KINGCHEF-ALQUOZ), so that is tried first: it is exact. The written
        branch name is the second try, folded so commas and dashes do not
        matter. Both failing is a real error, never a silent guess.
        """
        suffix = username.split(".", 1)[1] if "." in username else ""
        if suffix:
            outlet = Outlet.objects.filter(code__iexact=suffix).first()
            if outlet is not None:
                return outlet

        label = row.get("branch", "")
        if _norm(label) in ALL_BRANCHES_WORDS:
            raise CommandError(
                f"Line {line}: {username} is a branch user but the Branch "
                f"column says {label!r}. Give one branch per branch user."
            )

        wanted = _norm(label)
        matches = [
            outlet
            for outlet in Outlet.objects.select_related("brand")
            if _norm(outlet.official_name) == wanted or _norm(outlet.code) == wanted
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(o.code for o in matches)
            raise CommandError(
                f"Line {line}: branch {label!r} matches more than one outlet "
                f"({names}). Use one of those codes in the Username column."
            )
        raise CommandError(
            f"Line {line}: branch {label!r} does not exist and the username "
            f"{username!r} does not name an outlet code either."
        )

    def _reject_duplicates(self, planned):
        seen = {}
        for plan in planned:
            key = plan["username"].lower()
            if key in seen:
                raise CommandError(
                    f"Lines {seen[key]} and {plan['line']} both use the username "
                    f"{plan['username']!r}. One username, one account."
                )
            seen[key] = plan["line"]

    # ------------------------------------------------------------------- apply
    def _apply(self, planned, password_policy):
        superusers = []
        managers = []
        results = []

        with transaction.atomic():
            for plan in planned:
                user, is_new = self._ensure_user(plan, password_policy)
                if plan["role"] == ROLE_SUPERUSER:
                    self._make_superuser(user)
                    superusers.append(user)
                else:
                    apply_role_to_user(
                        user, plan["role"], plan["brand"], plan["outlets"]
                    )
                    managers.append(user)
                results.append({**plan, "user": user, "new": is_new})

        return results

    def _ensure_user(self, plan, password_policy):
        user = User.objects.filter(username__iexact=plan["username"]).first()
        is_new = user is None

        if is_new:
            # "never" exists for the case where the sheet is shared before the
            # passwords are, so the account exists but nobody can sign in yet.
            password = plan["password"] if password_policy != "never" else None
            user = User(username=plan["username"], email=plan["email"])
            if password:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save()
            return user, True

        changed = []
        if plan["email"] and user.email != plan["email"]:
            user.email = plan["email"]
            changed.append("email")
        if not user.is_active:
            user.is_active = True
            changed.append("is_active")
        if password_policy == "always" and plan["password"]:
            user.set_password(plan["password"])
            changed.append("password")
        if changed:
            user.save(update_fields=changed)
        return user, False

    def _make_superuser(self, user):
        """Superuser: full access, and no scoped profile to contradict it."""
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.save(update_fields=["is_superuser", "is_staff", "is_active"])
        # A superuser is never limited to a brand or branch. If an older run
        # left a profile behind, it would only confuse the Users list.
        profile = getattr(user, "outlet_manager_profile", None)
        if profile is not None:
            profile.outlets.clear()
            profile.delete()

    # ----------------------------------------------------------------- printing
    def _print_plan(self, planned):
        self.stdout.write("ROLE            USERNAME                    SCOPE")
        self.stdout.write("-" * 78)
        for plan in planned:
            exists = User.objects.filter(username__iexact=plan["username"]).exists()
            marker = "refresh" if exists else "create "
            role = plan["role"].replace("_", " ").title()
            self.stdout.write(
                f"{role:<15} {plan['username']:<27} {marker}  {plan['scope']}"
            )
        self.stdout.write("")
        self.stdout.write(
            f"{len(planned)} account(s) in the sheet "
            f"({sum(1 for p in planned if p['role'] == ROLE_SUPERUSER)} superuser, "
            f"{sum(1 for p in planned if p['role'] == ROLE_BRAND)} brand, "
            f"{sum(1 for p in planned if p['role'] == ROLE_OUTLET)} branch)."
        )

    def _print_report(self, results):
        created = [r for r in results if r["new"]]
        refreshed = [r for r in results if not r["new"]]

        self.stdout.write(
            f"Created {len(created)} account(s), refreshed {len(refreshed)}."
        )
        self.stdout.write("")
        self.stdout.write("ROLE            USERNAME                    OUTLETS IN SCOPE")
        self.stdout.write("-" * 78)
        for result in results:
            user = result["user"]
            count = "all" if user.is_superuser else str(scoped_outlets(user).count())
            role = result["role"].replace("_", " ").title()
            self.stdout.write(f"{role:<15} {user.username:<27} {count}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("Staff accounts from the sheet are ready.")
        )
