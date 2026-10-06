"""Development OTP provider. Prints the code; never sends an SMS."""

from apps.kidsplay.providers.base import OTPProvider


class ConsoleOTPProvider(OTPProvider):
    def send(self, phone: str, code: str) -> None:
        print(f"[kidsplay] OTP for {phone}: {code}")
