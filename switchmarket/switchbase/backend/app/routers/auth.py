from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import get_settings
from app import schemas, crud, security

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/telegram", response_model=schemas.AuthResponse)
async def login_via_telegram(payload: schemas.TelegramAuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        tg_user = security.validate_telegram_init_data(
            init_data=payload.init_data,
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_init_data_max_age_seconds,
        )
    except security.InvalidInitDataError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не удалось подтвердить подлинность данных Telegram",
        )

    user = await crud.get_or_create_user(db, tg_user)
    token = security.create_access_token(user.id)
    return schemas.AuthResponse(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
async def read_current_user(user=Depends(security.get_current_user)):
    return user
