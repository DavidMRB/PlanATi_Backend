from abc import ABC, abstractmethod
import logging

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


class SmsProvider(ABC):
    @abstractmethod
    async def send_verification_code(self, phone_number: str, code: str) -> None:
        """Send a verification code to a phone number."""


class MockSmsProvider(SmsProvider):
    async def send_verification_code(self, phone_number: str, code: str) -> None:
        logger.info("MOCK SMS | To: %s | OTP: %s", phone_number, code)


def get_sms_provider(provider_name: str) -> SmsProvider:
    if provider_name.lower() == "mock":
        return MockSmsProvider()
    raise ValueError(f"Unsupported SMS provider: {provider_name}")
