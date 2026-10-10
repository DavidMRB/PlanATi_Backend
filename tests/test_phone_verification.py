import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.phone_verification import PhoneVerificationCode
from app.models.user import User
from app.services import phone_verification_service
from app.services.phone_verification_service import (
    PhoneVerificationError,
    normalize_colombian_phone,
    send_phone_code,
    verify_phone_code,
)


def test_normalize_colombian_phone() -> None:
    assert normalize_colombian_phone("+57 300 123 4567") == "+573001234567"
    assert normalize_colombian_phone("3001234567") == "+573001234567"


def test_invalid_colombian_phone() -> None:
    with pytest.raises(PhoneVerificationError):
        normalize_colombian_phone("311123")


def test_otp_flow_and_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_test_otp_flow_and_single_use(monkeypatch))


async def _test_otp_flow_and_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    sent_codes: list[str] = []

    class FakeSmsProvider:
        async def send_verification_code(self, _phone_number: str, code: str) -> None:
            sent_codes.append(code)

    monkeypatch.setattr(phone_verification_service, "get_sms_provider", lambda _: FakeSmsProvider())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        user = User(
            full_name="Test User",
            email="test@example.com",
            password_hash="not-used",
            status="PENDING_PHONE",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        await send_phone_code(session, user, "3001234567")
        assert len(sent_codes) == 1
        stored_code = await session.scalar(
            select(PhoneVerificationCode).where(
                PhoneVerificationCode.user_id == user.id
            )
        )
        assert stored_code.code_hash != sent_codes[0]

        await verify_phone_code(session, user, "3001234567", sent_codes[0])
        assert user.phone_verified is True
        assert user.status == "ACTIVE"
        with pytest.raises(PhoneVerificationError):
            await verify_phone_code(session, user, "3001234567", sent_codes[0])
    await engine.dispose()


def test_expired_otp_is_rejected() -> None:
    asyncio.run(_test_expired_otp_is_rejected())


async def _test_expired_otp_is_rejected() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        user = User(
            full_name="Expired User",
            email="expired@example.com",
            password_hash="not-used",
            status="PENDING_PHONE",
        )
        session.add(user)
        await session.flush()
        session.add(
            PhoneVerificationCode(
                user_id=user.id,
                phone_number="+573001234567",
                code_hash=phone_verification_service._hash_code("123456"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await session.commit()
        with pytest.raises(PhoneVerificationError, match="expiró"):
            await verify_phone_code(session, user, "3001234567", "123456")
    await engine.dispose()
