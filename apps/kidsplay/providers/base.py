"""OTP delivery. Real SMS providers implement this later."""

from abc import ABC, abstractmethod


class OTPProvider(ABC):
    @abstractmethod
    def send(self, phone: str, code: str) -> None:
        """Deliver a one-time code to a phone number."""
