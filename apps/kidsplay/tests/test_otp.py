from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.kidsplay.models import OTPChallenge
from apps.kidsplay.services import otp


class OTPTests(TestCase):
    def test_normalizes_uae_local_number(self):
        self.assertEqual(otp.normalize_phone("0501234567"), "+971501234567")
        self.assertEqual(otp.normalize_phone(""), "")

    def test_correct_code(self):
        ok, _ = otp.request_code("+971501234567")
        self.assertTrue(ok)
        challenge = OTPChallenge.objects.get()
        challenge.code_hash = otp._hash("+971501234567", "123456")
        challenge.save(update_fields=["code_hash"])
        ok, reason = otp.verify_code("0501234567", "123456")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_wrong_code_counts(self):
        otp.request_code("+971501234567")
        ok, reason = otp.verify_code("+971501234567", "000000")
        self.assertFalse(ok)
        self.assertEqual(reason, "wrong_code")
        self.assertEqual(OTPChallenge.objects.get().attempts, 1)

    def test_expired_code(self):
        otp.request_code("+971501234567")
        OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        ok, reason = otp.verify_code("+971501234567", "000000")
        self.assertEqual(reason, "expired")

    def test_max_attempts(self):
        otp.request_code("+971501234567")
        OTPChallenge.objects.update(attempts=5)
        ok, reason = otp.verify_code("+971501234567", "000000")
        self.assertEqual(reason, "max_attempts")

    def test_resend_cooldown(self):
        otp.request_code("+971501234567")
        ok, reason = otp.request_code("+971501234567")
        self.assertFalse(ok)
        self.assertEqual(reason, "cooldown")
