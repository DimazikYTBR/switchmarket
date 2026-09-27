import enum
import datetime
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class UserRole(str, enum.Enum):
    USER = "user"
    VERIFIED = "verified"
    ARBITER = "arbiter"


class OrderStatus(str, enum.Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    ESCROW_LOCKED = "escrow_locked"
    ASSET_TRANSFERRED = "asset_transferred"
    HOLD_PERIOD = "hold_period"
    COMPLETED = "completed"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ton_wallet_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deposit_memo: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    available_balance: Mapped[float] = mapped_column(Float, default=0.0)
    pending_balance: Mapped[float] = mapped_column(Float, default=0.0)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["Item"]] = relationship(back_populates="owner", foreign_keys="Item.owner_id")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    external_gift_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(256))
    preview_url: Mapped[str] = mapped_column(String(512))
    rarity_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped["User"] = relationship(back_populates="items", foreign_keys=[owner_id])


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped["Item"] = relationship()
    seller: Mapped["User"] = relationship(foreign_keys=[seller_id])


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    arbiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    price: Mapped[float] = mapped_column(Float)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.AWAITING_PAYMENT)
    seller_confirmed_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    buyer_confirmed_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    funds_in_seller_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    item: Mapped["Item"] = relationship()
    buyer: Mapped["User"] = relationship(foreign_keys=[buyer_id])
    seller: Mapped["User"] = relationship(foreign_keys=[seller_id])
    arbiter: Mapped["User | None"] = relationship(foreign_keys=[arbiter_id])
    messages: Mapped[list["OrderMessage"]] = relationship(back_populates="order", order_by="OrderMessage.created_at")
    events: Mapped[list["OrderEvent"]] = relationship(back_populates="order", order_by="OrderEvent.created_at")


class WithdrawalStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED_SENT = "approved_sent"
    REJECTED = "rejected"


class Deposit(Base):
    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tx_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    amount: Mapped[float] = mapped_column(Float)
    memo_matched: Mapped[str] = mapped_column(String(64))
    credited_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    destination_address: Mapped[str] = mapped_column(String(128))
    status: Mapped[WithdrawalStatus] = mapped_column(SAEnum(WithdrawalStatus), default=WithdrawalStatus.PENDING_REVIEW)
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    processed_by: Mapped["User | None"] = relationship(foreign_keys=[processed_by_id])


class OrderMessage(Base):
    __tablename__ = "order_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped["Order"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship()


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped["Order"] = relationship(back_populates="events")
