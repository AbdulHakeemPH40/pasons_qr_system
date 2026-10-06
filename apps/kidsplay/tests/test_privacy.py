from django.test import TestCase
from django.utils import timezone

from apps.kidsplay.models import Family, KidProfile, PointsLedger
from apps.kidsplay.services import privacy


class PrivacyTests(TestCase):
    def test_delete_removes_family_and_anonymizes_ledger(self):
        family = Family.objects.create(phone="+971504040404", consent_at=timezone.now())
        kid = KidProfile.objects.create(family=family, nickname="Noor", avatar="burger")
        PointsLedger.objects.create(
            kid=kid, delta=10, reason=PointsLedger.Reason.GAME, ref_type="GameSession", ref_id="abc"
        )
        privacy.delete_family(family)
        self.assertFalse(Family.objects.filter(phone="+971504040404").exists())
        self.assertFalse(KidProfile.objects.exists())
        row = PointsLedger.objects.get()
        self.assertEqual(row.delta, 10)
        self.assertEqual(row.ref_id, "")
        self.assertEqual(row.ref_type, "anonymized")
