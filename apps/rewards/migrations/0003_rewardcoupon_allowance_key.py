"""
Give RewardCoupon the allowance key, then let the database enforce it.

Before this migration the one-dessert-and-one-discount-per-mobile-per-month
rule lived only in `apps.rewards.services._took_this_kind_this_month`, which
reads before it writes. Two claims landing in the same instant could both
read "not yet" and both issue. The unique index added here removes that
window: the second INSERT fails, and the engine turns that failure into the
same refusal the read would have produced.

The backfill is deliberately defensive. Rows that already duplicate a key
(the same number, kind and month) keep a NULL key instead of being deleted
or merged, because NULL never collides in a unique index. History stays
exactly as it is and only new rows are constrained.
"""

from django.db import migrations, models
from django.utils import timezone


def fill_allowance_keys(apps, schema_editor):
    RewardCoupon = apps.get_model("rewards", "RewardCoupon")
    seen = set()
    for row in (
        RewardCoupon.objects.select_related("profile")
        .order_by("issued_at", "pk")
        .iterator()
    ):
        if row.status == "void" or not row.profile_id:
            continue
        phone = row.profile.phone or None
        if not phone or not row.issued_at:
            continue
        period = timezone.localtime(row.issued_at).strftime("%Y-%m")
        key = (phone, row.reward_type, period)
        if key in seen:
            continue
        seen.add(key)
        row.phone_key = phone
        row.allowance_period = period
        row.save(update_fields=["phone_key", "allowance_period"])


class Migration(migrations.Migration):

    dependencies = [
        ("rewards", "0002_rewardprogress_rewardround"),
    ]

    operations = [
        migrations.AddField(
            model_name="rewardcoupon",
            name="phone_key",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="E.164 of the winning guest at issue time; the allowance key",
                max_length=24,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="rewardcoupon",
            name="allowance_period",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="YYYY-MM of the win; the allowance window",
                max_length=7,
                null=True,
            ),
        ),
        migrations.RunPython(fill_allowance_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="rewardcoupon",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "void"), _negated=True),
                fields=("phone_key", "reward_type", "allowance_period"),
                name="one_prize_per_kind_per_phone_per_month",
            ),
        ),
    ]
