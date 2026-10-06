"""Delete a family's personal data. Ledger totals stay, names do not."""

from django.db import transaction

from apps.kidsplay.models import Family, PointsLedger


def delete_family(family: Family) -> None:
    """Remove the family and kids. Ledger rows keep their points, not the nickname."""
    with transaction.atomic():
        kid_ids = list(family.kids.values_list("pk", flat=True))
        PointsLedger.objects.filter(kid_id__in=kid_ids).update(
            kid=None, ref_type="anonymized", ref_id=""
        )
        family.delete()
