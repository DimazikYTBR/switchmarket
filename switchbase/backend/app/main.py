import asyncio
import contextlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import init_models, AsyncSessionLocal
from app.routers import auth, catalog, orders, chat, wallet
from app.routers.orders import finalize_expired_holds

settings = get_settings()


async def hold_expiry_worker() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await finalize_expired_holds(db)
        except Exception:
            pass
        await asyncio.sleep(60)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    task = asyncio.create_task(hold_expiry_worker())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(orders.router)
app.include_router(chat.router)
app.include_router(wallet.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": settings.app_name}
