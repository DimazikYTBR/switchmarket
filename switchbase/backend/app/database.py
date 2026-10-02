from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def _check_table_columns(sync_conn, table) -> list[str]:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(sync_conn)
    if table.name not in inspector.get_table_names():
        return []

    existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
    expected_columns = {col.name for col in table.columns}
    return sorted(expected_columns - existing_columns)


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        missing_by_table: dict[str, list[str]] = {}
        for table in Base.metadata.sorted_tables:
            missing = await conn.run_sync(lambda sync_conn, t=table: _check_table_columns(sync_conn, t))
            if missing:
                missing_by_table[table.name] = missing

        if missing_by_table:
            details = "; ".join(f"{table}: {', '.join(cols)}" for table, cols in missing_by_table.items())
            raise RuntimeError(
                "Схема базы данных устарела относительно моделей SQLAlchemy. "
                f"Отсутствуют колонки — {details}. "
                "Это dev-окружение использует SQLite с create_all(), который не делает ALTER TABLE "
                "для уже существующих таблиц. Удалите файл switchmarket.db (или переменную database_url, "
                "если вы используете другую БД) и перезапустите сервер, чтобы схема пересоздалась с нуля. "
                "Для продакшена с реальными данными здесь нужен Alembic, а не create_all()."
            )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
