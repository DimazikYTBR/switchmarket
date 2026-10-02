import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import get_settings
from app import schemas, crud, models, security
from app.ws_manager import manager

router = APIRouter(prefix="/api/orders", tags=["orders"])
settings = get_settings()


def ensure_can_view(order: models.Order, user: models.User) -> None:
    if not crud.user_can_view_order(order, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ ограничен. Вы не являетесь участником этой сделки",
        )


@router.post("", response_model=schemas.OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: schemas.OrderCreate,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    listing = await crud.get_listing(db, payload.listing_id)
    if listing is None or not listing.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Лот недоступен")
    if listing.seller_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя купить собственный лот")

    order = models.Order(
        public_code=crud.generate_public_code(),
        listing_id=listing.id,
        item_id=listing.item_id,
        buyer_id=user.id,
        seller_id=listing.seller_id,
        price=listing.price,
        status=models.OrderStatus.AWAITING_PAYMENT,
    )
    listing.is_active = False
    db.add(order)
    await db.commit()
    await db.refresh(order)

    await crud.add_order_event(db, order, user.id, "order_created", f"Сделка создана покупателем {user.first_name}")

    return await crud.get_order_by_id(db, order.id)


@router.get("/queue/disputes", response_model=list[schemas.OrderOut])
async def disputes_queue(
    arbiter: models.User = Depends(security.require_arbiter),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(models.Order)
        .where(models.Order.status == models.OrderStatus.DISPUTED)
        .options(
            selectinload(models.Order.item),
            selectinload(models.Order.buyer),
            selectinload(models.Order.seller),
            selectinload(models.Order.arbiter),
        )
        .order_by(models.Order.updated_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{public_code}", response_model=schemas.OrderOut)
async def get_order(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    ensure_can_view(order, user)
    return order


@router.get("/{public_code}/events", response_model=list[schemas.OrderEventOut])
async def get_order_events(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    ensure_can_view(order, user)
    return order.events


@router.post("/{public_code}/pay", response_model=schemas.OrderOut)
async def pay_order(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if order.buyer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только покупатель может внести оплату")
    if order.status != models.OrderStatus.AWAITING_PAYMENT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Оплата уже внесена или сделка изменила статус")
    if user.available_balance < order.price:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Недостаточно доступного баланса. Пополните счёт через депозит на кошелёк платформы",
        )

    user.available_balance -= order.price
    order.status = models.OrderStatus.ESCROW_LOCKED
    await db.commit()

    await crud.add_order_event(
        db, order, user.id, "escrow_locked",
        "Средства списаны с доступного баланса покупателя и заблокированы на стороне платформы. Продавец доступа к ним не имеет",
    )
    await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    return await crud.get_order_by_id(db, order.id)


@router.post("/{public_code}/confirm-transfer", response_model=schemas.OrderOut)
async def confirm_transfer(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if order.seller_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только продавец может подтвердить передачу")
    if order.status != models.OrderStatus.ESCROW_LOCKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Сделка не находится в статусе депонирования")

    order.seller_confirmed_transfer = True
    order.status = models.OrderStatus.ASSET_TRANSFERRED
    await db.commit()

    await crud.add_order_event(db, order, user.id, "asset_transferred", "Продавец подтвердил передачу предмета")
    await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    return await crud.get_order_by_id(db, order.id)


@router.post("/{public_code}/confirm-receipt", response_model=schemas.OrderOut)
async def confirm_receipt(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if order.buyer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только покупатель может подтвердить получение")
    if order.status != models.OrderStatus.ASSET_TRANSFERRED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Предмет ещё не передан продавцом")

    order.buyer_confirmed_receipt = True
    order.status = models.OrderStatus.HOLD_PERIOD
    order.hold_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=settings.hold_period_hours)

    order.seller.pending_balance += order.price
    order.funds_in_seller_pending = True

    await db.commit()

    await crud.add_order_event(
        db, order, user.id, "hold_started",
        f"Покупатель подтвердил получение. Средства переведены в pending_balance продавца, холд до {order.hold_until.isoformat()}",
    )
    await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    return await crud.get_order_by_id(db, order.id)


@router.post("/{public_code}/dispute", response_model=schemas.OrderOut)
async def open_dispute(
    public_code: str,
    payload: schemas.DisputeOpenRequest,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    ensure_can_view(order, user)
    if order.status in (models.OrderStatus.COMPLETED, models.OrderStatus.CANCELLED, models.OrderStatus.REFUNDED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="По завершённой сделке спор не открыть")

    order.status = models.OrderStatus.DISPUTED
    order.dispute_reason = payload.reason
    await db.commit()

    await crud.add_order_event(db, order, user.id, "dispute_opened", payload.reason)
    await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    return await crud.get_order_by_id(db, order.id)


@router.post("/{public_code}/dispute/resolve", response_model=schemas.OrderOut)
async def resolve_dispute(
    public_code: str,
    payload: schemas.DisputeResolveRequest,
    arbiter: models.User = Depends(security.require_arbiter),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if order.status != models.OrderStatus.DISPUTED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="По этой сделке нет открытого спора")

    order.arbiter_id = arbiter.id

    if payload.resolution == "refund_buyer":
        if order.funds_in_seller_pending:
            order.seller.pending_balance -= order.price
        order.buyer.available_balance += order.price
        order.item.locked = False
        order.status = models.OrderStatus.REFUNDED
        detail = f"Арбитр {arbiter.first_name} вернул средства на available_balance покупателя"
    else:
        if order.funds_in_seller_pending:
            order.seller.pending_balance -= order.price
        order.seller.available_balance += order.price
        order.item.owner_id = order.buyer_id
        order.item.locked = False
        order.status = models.OrderStatus.COMPLETED
        detail = f"Арбитр {arbiter.first_name} подтвердил передачу, средства зачислены на available_balance продавца немедленно, минуя холд"

    if payload.note:
        detail += f". Комментарий арбитра: {payload.note}"

    await db.commit()
    await crud.add_order_event(db, order, arbiter.id, "dispute_resolved", detail)
    await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    return await crud.get_order_by_id(db, order.id)


async def finalize_expired_holds(db: AsyncSession) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    now = datetime.datetime.now(datetime.timezone.utc)
    result = await db.execute(
        select(models.Order)
        .where(
            models.Order.status == models.OrderStatus.HOLD_PERIOD,
            models.Order.hold_until <= now,
        )
        .options(selectinload(models.Order.seller), selectinload(models.Order.item))
    )
    orders = list(result.scalars().all())

    for order in orders:
        order.seller.pending_balance -= order.price
        order.seller.available_balance += order.price
        order.item.owner_id = order.buyer_id
        order.item.locked = False
        order.status = models.OrderStatus.COMPLETED
        await crud.add_order_event(
            db, order, None, "auto_completed",
            "Холд 24ч истёк без споров. Средства переведены из pending_balance в available_balance продавца автоматически",
        )
        await manager.broadcast(order.id, {"type": "status_changed", "status": order.status.value})

    if orders:
        await db.commit()
