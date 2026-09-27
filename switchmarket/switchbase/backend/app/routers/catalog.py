import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app import schemas, crud, models, security, ton_client

router = APIRouter(prefix="/api", tags=["catalog"])


@router.post("/inventory/sync", response_model=list[schemas.ItemOut])
async def sync_inventory(
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.ton_wallet_address:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала подключите TON-кошелёк для чтения инвентаря подарков",
        )

    try:
        gifts = await ton_client.fetch_wallet_nfts(user.ton_wallet_address)
    except ton_client.TonApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    existing_result = await db.execute(select(models.Item).where(models.Item.owner_id == user.id))
    existing_by_gift_id = {item.external_gift_id: item for item in existing_result.scalars().all()}

    for gift in gifts:
        item = existing_by_gift_id.get(gift["external_gift_id"])
        if item is None:
            item = models.Item(
                owner_id=user.id,
                external_gift_id=gift["external_gift_id"],
                title=gift["title"],
                preview_url=gift["preview_url"],
                rarity_number=gift["rarity_number"],
                attributes_json=json.dumps(gift["attributes"]),
                locked=False,
            )
            db.add(item)
        else:
            item.title = gift["title"]
            item.preview_url = gift["preview_url"]
            item.rarity_number = gift["rarity_number"]
            item.attributes_json = json.dumps(gift["attributes"])

    await db.commit()

    result = await db.execute(select(models.Item).where(models.Item.owner_id == user.id))
    return list(result.scalars().all())


@router.get("/inventory", response_model=list[schemas.ItemOut])
async def get_my_inventory(
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud.get_user_items(db, user.id)


@router.get("/listings", response_model=list[schemas.ListingOut])
async def browse_listings(db: AsyncSession = Depends(get_db)):
    return await crud.get_active_listings(db)


@router.post("/listings", response_model=schemas.ListingOut, status_code=status.HTTP_201_CREATED)
async def create_listing(
    payload: schemas.ListingCreate,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(models.Item, payload.item_id)
    if item is None or item.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Предмет не найден в вашем инвентаре")
    if item.locked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Предмет уже участвует в активной сделке")

    listing = models.Listing(item_id=item.id, seller_id=user.id, price=payload.price, is_active=True)
    item.locked = True
    db.add(listing)
    await db.commit()

    return await crud.get_listing(db, listing.id)


@router.delete("/listings/{listing_id}")
async def cancel_listing(
    listing_id: int,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    listing = await crud.get_listing(db, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Лот не найден")
    if listing.seller_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш лот")

    listing.is_active = False
    listing.item.locked = False
    await db.commit()
    return {"status": "cancelled"}
