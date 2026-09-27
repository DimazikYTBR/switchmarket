import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.config import get_settings
from app import schemas, models, security, ton_client, crud

router = APIRouter(prefix="/api/wallet", tags=["wallet"])
settings = get_settings()


@router.post("/connect")
async def connect_wallet(
    address: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.ton_wallet_address = address
    await db.commit()
    return {"status": "connected", "address": address}


@router.get("/deposit/instructions", response_model=schemas.DepositInstructionsOut)
async def deposit_instructions(user: models.User = Depends(security.get_current_user)):
    return schemas.DepositInstructionsOut(
        platform_wallet_address=settings.platform_wallet_address,
        memo=user.deposit_memo,
    )


@router.post("/deposit/sync", response_model=schemas.UserOut)
async def sync_deposits(
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        transactions = await ton_client.fetch_incoming_transactions(settings.platform_wallet_address)
    except ton_client.TonApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    existing_result = await db.execute(select(models.Deposit.tx_hash))
    already_credited = {row[0] for row in existing_result.all()}

    for tx in transactions:
        if tx["comment"] != user.deposit_memo:
            continue
        if tx["tx_hash"] in already_credited:
            continue

        amount_ton = tx["amount_nano"] / 1_000_000_000
        if amount_ton <= 0:
            continue

        deposit = models.Deposit(
            user_id=user.id,
            tx_hash=tx["tx_hash"],
            amount=amount_ton,
            memo_matched=tx["comment"],
        )
        db.add(deposit)
        user.available_balance += amount_ton
        already_credited.add(tx["tx_hash"])

    await db.commit()
    await db.refresh(user)
    return user


@router.get("/deposits", response_model=list[schemas.DepositOut])
async def list_my_deposits(
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.Deposit).where(models.Deposit.user_id == user.id).order_by(models.Deposit.credited_at.desc())
    )
    return list(result.scalars().all())


@router.post("/withdraw", response_model=schemas.WithdrawalOut, status_code=status.HTTP_201_CREATED)
async def request_withdrawal(
    payload: schemas.WithdrawalRequest,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.amount < settings.withdrawal_min_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Минимальная сумма вывода {settings.withdrawal_min_amount} GRAM",
        )
    if payload.amount > user.available_balance:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Сумма превышает доступный баланс. Средства в холде выводить нельзя",
        )

    user.available_balance -= payload.amount
    withdrawal = models.Withdrawal(
        user_id=user.id,
        amount=payload.amount,
        destination_address=payload.destination_address,
        status=models.WithdrawalStatus.PENDING_REVIEW,
    )
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


@router.get("/withdrawals", response_model=list[schemas.WithdrawalOut])
async def list_my_withdrawals(
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.Withdrawal).where(models.Withdrawal.user_id == user.id).order_by(models.Withdrawal.requested_at.desc())
    )
    return list(result.scalars().all())


@router.get("/withdrawals/queue", response_model=list[schemas.WithdrawalOut])
async def withdrawal_queue(
    arbiter: models.User = Depends(security.require_arbiter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(models.Withdrawal)
        .where(models.Withdrawal.status == models.WithdrawalStatus.PENDING_REVIEW)
        .order_by(models.Withdrawal.requested_at.asc())
    )
    return list(result.scalars().all())


@router.post("/withdrawals/{withdrawal_id}/decision", response_model=schemas.WithdrawalOut)
async def decide_withdrawal(
    withdrawal_id: int,
    payload: schemas.WithdrawalDecision,
    arbiter: models.User = Depends(security.require_arbiter),
    db: AsyncSession = Depends(get_db),
):
    withdrawal = await db.get(models.Withdrawal, withdrawal_id)
    if withdrawal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка на вывод не найдена")
    if withdrawal.status != models.WithdrawalStatus.PENDING_REVIEW:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Заявка уже обработана")

    if payload.action == "approve":
        if not payload.tx_hash:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Укажите хэш исходящей транзакции")
        withdrawal.status = models.WithdrawalStatus.APPROVED_SENT
        withdrawal.tx_hash = payload.tx_hash
    else:
        withdrawal.status = models.WithdrawalStatus.REJECTED
        owner = await db.get(models.User, withdrawal.user_id)
        owner.available_balance += withdrawal.amount

    withdrawal.processed_by_id = arbiter.id
    withdrawal.processed_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal
