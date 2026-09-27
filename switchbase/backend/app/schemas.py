import datetime
from pydantic import BaseModel, Field
from app.models import UserRole, OrderStatus


class TelegramAuthRequest(BaseModel):
    init_data: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    photo_url: str | None
    ton_wallet_address: str | None
    deposit_memo: str
    available_balance: float
    pending_balance: float
    role: UserRole

    class Config:
        from_attributes = True


class DepositInstructionsOut(BaseModel):
    platform_wallet_address: str
    memo: str


class DepositOut(BaseModel):
    id: int
    tx_hash: str
    amount: float
    credited_at: datetime.datetime

    class Config:
        from_attributes = True


class WithdrawalRequest(BaseModel):
    amount: float = Field(gt=0)
    destination_address: str = Field(min_length=10, max_length=128)


class WithdrawalOut(BaseModel):
    id: int
    amount: float
    destination_address: str
    status: str
    tx_hash: str | None
    requested_at: datetime.datetime
    processed_at: datetime.datetime | None

    class Config:
        from_attributes = True


class WithdrawalDecision(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    tx_hash: str | None = None
    note: str | None = None


class ItemOut(BaseModel):
    id: int
    title: str
    preview_url: str
    rarity_number: str | None
    attributes_json: str
    locked: bool

    class Config:
        from_attributes = True


class ListingCreate(BaseModel):
    item_id: int
    price: float = Field(gt=0)


class ListingOut(BaseModel):
    id: int
    price: float
    is_active: bool
    created_at: datetime.datetime
    item: ItemOut
    seller: UserOut

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    listing_id: int


class OrderOut(BaseModel):
    id: int
    public_code: str
    price: float
    status: OrderStatus
    seller_confirmed_transfer: bool
    buyer_confirmed_receipt: bool
    hold_until: datetime.datetime | None
    dispute_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    item: ItemOut
    buyer: UserOut
    seller: UserOut

    class Config:
        from_attributes = True


class OrderMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class OrderMessageOut(BaseModel):
    id: int
    sender_id: int
    body: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class OrderEventOut(BaseModel):
    id: int
    actor_id: int | None
    event_type: str
    detail: str | None
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class DisputeOpenRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class DisputeResolveRequest(BaseModel):
    resolution: str = Field(pattern="^(refund_buyer|release_seller)$")
    note: str | None = None
