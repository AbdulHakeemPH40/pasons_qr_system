from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.kidsplay.models import Family, KidProfile, PointsLedger, Redemption, Reward
from apps.kidsplay.services import points, rewards


class RedemptionTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(phone="+971503030303", consent_at=timezone.now())
        self.kid = KidProfile.objects.create(family=self.family, nickname="Hana", avatar="donut", points_balance=100)
        PointsLedger.objects.create(kid=self.kid, delta=100, reason=PointsLedger.Reason.ADMIN_ADJUST)
        self.reward = Reward.objects.create(title="Scoop", cost_points=40, stock=1)
        self.staff = get_user_model().objects.create_user("waiter", password="pw", is_staff=True)

    def test_insufficient_points(self):
        self.reward.cost_points = 500
        self.reward.save()
        redemption, error = rewards.create_redemption(self.kid, self.reward)
        self.assertEqual(error, "insufficient_points")
        self.assertIsNone(redemption)

    def test_out_of_stock(self):
        self.reward.stock = 0
        self.reward.save()
        _, error = rewards.create_redemption(self.kid, self.reward)
        self.assertEqual(error, "out_of_stock")

    def test_confirm_keeps_deduction(self):
        redemption, error = rewards.create_redemption(self.kid, self.reward)
        self.assertEqual(error, "")
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_balance, 60)
        ok, status = rewards.confirm(redemption.code, self.staff)
        self.assertTrue(ok)
        self.assertEqual(status, "confirmed")
        self.assertEqual(points.balance(self.kid), 60)

    def test_pending_blocks_a_second(self):
        rewards.create_redemption(self.kid, self.reward)
        other = Reward.objects.create(title="Toy", cost_points=20)
        _, error = rewards.create_redemption(self.kid, other)
        self.assertEqual(error, "pending_exists")

    def test_cancel_refunds(self):
        redemption, _ = rewards.create_redemption(self.kid, self.reward)
        rewards.cancel(redemption.code, self.staff)
        self.kid.refresh_from_db()
        self.reward.refresh_from_db()
        self.assertEqual(self.kid.points_balance, 100)
        self.assertEqual(self.reward.stock, 1)
        self.assertEqual(points.balance(self.kid), 100)

    def test_expiry_refunds(self):
        redemption, _ = rewards.create_redemption(self.kid, self.reward)
        Redemption.objects.filter(pk=redemption.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(rewards.expire_due(), 1)
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.points_balance, 100)
        self.assertEqual(Redemption.objects.get().status, Redemption.Status.EXPIRED)

    def test_staff_page_requires_staff(self):
        response = self.client.get("/staff/kidsplay/redeem/")
        self.assertEqual(response.status_code, 302)
        self.client.login(username="waiter", password="pw")
        response = self.client.get("/staff/kidsplay/redeem/")
        self.assertEqual(response.status_code, 200)
