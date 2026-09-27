from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, AsyncSessionLocal
from app import schemas, crud, models, security
from app.ws_manager import manager

router = APIRouter(prefix="/api/orders", tags=["chat"])


@router.get("/{public_code}/messages", response_model=list[schemas.OrderMessageOut])
async def get_messages(
    public_code: str,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if not crud.user_can_view_order(order, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ ограничен")
    return order.messages


@router.post("/{public_code}/messages", response_model=schemas.OrderMessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    public_code: str,
    payload: schemas.OrderMessageCreate,
    user: models.User = Depends(security.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud.get_order_by_code(db, public_code)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сделка не найдена")
    if not crud.user_can_view_order(order, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ ограничен")

    message = models.OrderMessage(order_id=order.id, sender_id=user.id, body=payload.body)
    db.add(message)
    await db.commit()
    await db.refresh(message)

    await manager.broadcast(
        order.id,
        {
            "type": "message",
            "id": message.id,
            "sender_id": message.sender_id,
            "body": message.body,
            "created_at": message.created_at.isoformat(),
        },
    )

    return message


@router.websocket("/{public_code}/ws")
async def order_chat_socket(websocket: WebSocket, public_code: str, token: str = Query(...)):
    try:
        user_id = security.decode_access_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        order = await crud.get_order_by_code(db, public_code)
        if order is None:
            await websocket.close(code=4404)
            return
        user = await db.get(models.User, user_id)
        if user is None or not crud.user_can_view_order(order, user):
            await websocket.close(code=4403)
            return
        order_id = order.id

    await manager.connect(order_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            body = data.get("body", "").strip()
            if not body:
                continue

            async with AsyncSessionLocal() as db:
                message = models.OrderMessage(order_id=order_id, sender_id=user_id, body=body)
                db.add(message)
                await db.commit()
                await db.refresh(message)

            await manager.broadcast(
                order_id,
                {
                    "type": "message",
                    "id": message.id,
                    "sender_id": message.sender_id,
                    "body": message.body,
                    "created_at": message.created_at.isoformat(),
                },
            )
    except WebSocketDisconnect:
        manager.disconnect(order_id, websocket)
