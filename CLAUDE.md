# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PlanATi backend: a FastAPI API for searching, rating and managing gastronomic establishments. Code, comments, API error messages and docs are written in Spanish — keep new user-facing strings in Spanish.

## Commands

```bash
pip install -r requirements-dev.txt     # runtime + pytest + aiosqlite
docker compose up -d                    # PostGIS 16 on host port 5433 (not 5432)
python -m alembic upgrade head          # apply migrations
uvicorn app.main:app --reload           # health check: GET /api/v1/health
pytest                                  # all tests
pytest tests/test_phone_verification.py::test_otp_flow_and_single_use   # single test
```

`DATABASE_URL` uses `postgresql+asyncpg://...`; the config default points at port 5432, so with the Compose database set `.env` to port 5433. Copy `.env.example` to `.env` for local setup.

## Architecture

Layering is `app/api/routes/*` (HTTP, status codes) → `app/services/*` (business logic, takes an `AsyncSession` as first arg) → `app/models/*` (SQLAlchemy 2.x declarative, `app/db/base.py:Base`). Pydantic DTOs live in `app/schemas/`. Services signal domain errors with `ValueError` or custom exceptions (e.g. `PhoneVerificationError`) that routes translate into `HTTPException`. All routers are mounted under `settings.api_v1_prefix` (`/api/v1`) in `app/main.py`.

- **Async everywhere**: the app uses `create_async_engine` + `asyncpg`; the `get_db` dependency in `app/api/dependencies.py` yields an `AsyncSession`. Alembic, however, runs synchronously — `migrations/env.py` rewrites the URL from `+asyncpg` to `+psycopg`.
- **Migrations** are hand-numbered (`migrations/versions/000N_*.py`). New models must be imported in `app/models/__init__.py` so `Base.metadata` (used by Alembic and by tests' `create_all`) sees them.
- **Settings** come from `app/core/config.py` (`pydantic-settings`, reads `.env`, module-level `settings` singleton).

### Authentication and access control

- JWT (HS256, `sub` = user id) created in `app/core/security.py`. `get_current_user` accepts the token from an `Authorization: Bearer` header **or** the `HttpOnly` cookie named by `settings.access_token_cookie_name`; `set_auth_cookie`/`clear_auth_cookie` manage the cookie. The branch is migrating to cookie-only sessions — see `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md` for the target design (JWT never in JSON/URL, CSRF protection).
- Google OAuth (`app/integrations/google.py`): `/auth/google` sets a signed `oauth_state` cookie → `/auth/google/callback` verifies it, issues a short-lived one-time code (`OAuthLoginCode`, stored hashed) and redirects to `{FRONTEND_URL}/google-callback?code=...` → frontend calls `POST /auth/google/exchange` to get the session.
- Phone OTP (`app/services/phone_verification_service.py`): Colombian numbers normalized to `+57...`; codes stored hashed, single-use, with expiry/attempt/resend-cooldown limits from settings. SMS goes through a provider abstraction in `app/integrations/sms.py`; `SMS_PROVIDER=mock` only logs the code (it is never returned in HTTP responses). Tests swap the provider by monkeypatching `phone_verification_service.get_sms_provider`.
- User lifecycle: new users start with `status="PENDING_PHONE"`, `phone_verified=False`; verifying the OTP sets `ACTIVE`. A user with a verified phone cannot change it through `PATCH /users/me` (400). Changing it goes through `POST /users/me/phone/send-code` and `POST /users/me/phone/verify`, which leave the account `ACTIVE` with the old number until the new one is confirmed. Only the first-time setup (`/auth/phone/send-code`) puts the account in `PENDING_PHONE`. Use the dependencies `require_active_user` (verified + `ACTIVE`) for any route that creates/modifies establishments, reviews, etc., and `require_admin` (role `admin` + active) for admin routes.

### Other integrations

- `app/services/storage.py`: Cloudflare R2 via boto3 presigned upload URLs; returns 503 when R2 credentials are missing.
- Proximity search (`GET /establishments/nearby`) computes haversine distance in Python; PostGIS is available but not yet used for spatial queries.

## Tests

Tests use SQLite with `Base.metadata.create_all`, not Postgres. There is no pytest-asyncio. Service-level tests wrap async code in `asyncio.run(...)` (see `tests/test_phone_verification.py`). API tests use the fixtures in `tests/conftest.py`: each test gets a temporary SQLite file (not `:memory:`, which breaks across `TestClient`'s event loop), `get_db` is overridden, and `make_client()` returns a `TestClient` with its own cookie jar (one per actor). There are also `admin_client`, `register_restaurant(suffix)` and `approved_restaurant(suffix)` fixtures.

Alembic revision ids must be at most 32 characters (`alembic_version.version_num` is VARCHAR(32)).

### Restaurant accounts

`role="restaurant"` users are created by `POST /auth/restaurant/register` together with their `Establishment` (`status` is `PENDING`, `APPROVED` or `REJECTED`). They skip OTP verification: their access is gated by the establishment's approval. Routes under `/restaurant` use `require_restaurant_user` or `require_approved_restaurant`, which always resolve the establishment by `owner_id`. Never accept an `establishment_id` from the client there. `require_approved_restaurant` raises `EstablishmentAccessError`, which `app/main.py` turns into a 403 `{"detail", "status"}` response. Products and combos are both `MenuItem` (`is_combo`); a combo's composition is `ComboItem`. The public directory only shows `APPROVED` establishments.

## Planning docs

`restaurant-account-backend.md` is a step-by-step implementation plan (addressed to Claude Code) for restaurant accounts, admin approval (`PENDING`/`APPROVED`/`REJECTED`), product/combo catalog and public exposure; respect its explicit out-of-scope list when working on that feature. `Login/register.md` holds the original Google OAuth + OTP requirements.
