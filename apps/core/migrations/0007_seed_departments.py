"""Seed the five Head Office departments.

Reference data only. It is created with get_or_create so re-running the
migration is harmless, and the reverse deletes exactly these five codes.
The capability each code grants lives in
``apps.core.panel_permissions.DEPARTMENT_CAPABILITIES``.
"""

from django.db import migrations

DEPARTMENTS = [
    ("MARKETING", "Marketing", "\u0627\u0644\u062a\u0633\u0648\u064a\u0642"),
    ("OPERATIONS", "Operations", "\u0627\u0644\u0639\u0645\u0644\u064a\u0627\u062a"),
    ("FINANCE", "Finance", "\u0627\u0644\u0645\u0627\u0644\u064a\u0629"),
    ("HR", "HR", "\u0627\u0644\u0645\u0648\u0627\u0631\u062f \u0627\u0644\u0628\u0634\u0631\u064a\u0629"),
    ("IT", "IT and Admin", "\u062a\u0642\u0646\u064a\u0629 \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0627\u062a"),
]


def create_departments(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    for code, name_en, name_ar in DEPARTMENTS:
        Department.objects.get_or_create(
            code=code, defaults={"name_en": name_en, "name_ar": name_ar}
        )


def remove_departments(apps, schema_editor):
    Department = apps.get_model("core", "Department")
    Department.objects.filter(code__in=[code for code, _, _ in DEPARTMENTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_department_outletmanager_department"),
    ]

    operations = [
        migrations.RunPython(create_departments, remove_departments),
    ]
