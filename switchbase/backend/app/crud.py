import secrets
import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app import models


async def get_or_create_user(db: AsyncSession, tg_user: dict) -> models.User:
    telegram_id = int(tg_user["id"])
    result = await db.execute(select(models.User).where(models.User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = models.User(
            telegram_id=telegram_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name", "Пользователь"),
            last_name=tg_user.get("last_name"),
            photo_url=tg_user.get("photo_url"),
            deposit_memo=f"SM-{secrets.randbelow(9 * 10**8) + 10**8}",
            available_balance=0.0,
            pending_balance=0.0,
            role=models.UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.username = tg_user.get("username")
        user.first_name = tg_user.get("first_name", user.first_name)
        user.last_name = tg_user.get("last_name")
        user.photo_url = tg_user.get("photo_url")
        await db.commit()
        await db.refresh(user)

    return user


async def get_user_items(db: AsyncSession, owner_id: int) -> list[models.Item]:
    result = await db.execute(
        select(models.Item).where(models.Item.owner_id == owner_id).order_by(models.Item.created_at.desc())
    )
    return list(result.scalars().all())


async def get_active_listings(db: AsyncSession) -> list[models.Listing]:
    result = await db.execute(
        select(models.Listing)
        .where(models.Listing.is_active.is_(True))
        .options(selectinload(models.Listing.item), selectinload(models.Listing.seller))
        .order_by(models.Listing.created_at.desc())
    )
    return list(result.scalars().all())


async def get_listing(db: AsyncSession, listing_id: int) -> models.Listing | None:
    result = await db.execute(
        select(models.Listing)
        .where(models.Listing.id == listing_id)
        .options(selectinload(models.Listing.item), selectinload(models.Listing.seller))
    )
    return result.scalar_one_or_none()


def generate_public_code() -> str:
    return f"sm-{secrets.randbelow(9 * 10**8) + 10**8}"


async def get_order_by_code(db: AsyncSession, public_code: str) -> models.Order | None:
    result = await db.execute(
        select(models.Order)
        .where(models.Order.public_code == public_code)
        .options(
            selectinload(models.Order.item),
            selectinload(models.Order.buyer),
            selectinload(models.Order.seller),
            selectinload(models.Order.arbiter),
            selectinload(models.Order.messages),
        )
    )
    return result.scalar_one_or_none()


async def get_order_by_id(db: AsyncSession, order_id: int) -> models.Order | None:
    result = await db.execute(
        select(models.Order)
        .where(models.Order.id == order_id)
        .options(
            selectinload(models.Order.item),
            selectinload(models.Order.buyer),
            selectinload(models.Order.seller),
            selectinload(models.Order.arbiter),
        )
    )
    return result.scalar_one_or_none()


async def add_order_event(
    db: AsyncSession,
    order: models.Order,
    actor_id: int | None,
    event_type: str,
    detail: str | None = None,
) -> models.OrderEvent:
    event = models.OrderEvent(order_id=order.id, actor_id=actor_id, event_type=event_type, detail=detail)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


def user_can_view_order(order: models.Order, user: models.User) -> bool:
    if user.id == order.buyer_id or user.id == order.seller_id:
        return True
    if user.role == models.UserRole.ARBITER:
        return True
    return False
