import hmac
import hashlib
import json
import time
import urllib.parse
import datetime
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database import get_db
from app import models

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


class InvalidInitDataError(Exception):
    pass


def validate_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int) -> dict:
    parsed_pairs = urllib.parse.parse_qsl(init_data, strict_parsing=True)
    data = dict(parsed_pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InvalidInitDataError("missing hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items())
    )

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InvalidInitDataError("hash mismatch")

    auth_date = int(data.get("auth_date", "0"))
    if time.time() - auth_date > max_age_seconds:
        raise InvalidInitDataError("init data expired")

    user_raw = data.get("user")
    if not user_raw:
        raise InvalidInitDataError("missing user payload")

    user_payload = json.loads(user_raw)
    return user_payload


def create_access_token(user_id: int) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истёкший токен доступа",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация")

    user_id = decode_access_token(credentials.credentials)
    user = await db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


async def require_arbiter(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.ARBITER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только арбитрам платформы",
        )
    return user
