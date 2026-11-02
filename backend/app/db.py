from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.config import PROJECT_ROOT, config

DB_PATH = PROJECT_ROOT / config["storage"]["db_path"]
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from backend.app import models  # noqa: F401  # 注册全部模型
    Base.metadata.create_all(engine)
    # create_all 不会给已有 SQLite 表补列；为历史安装做一次幂等轻量迁移。
    columns = {item["name"] for item in inspect(engine).get_columns("apk_files")}
    if "static_summary" not in columns:
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE apk_files ADD COLUMN static_summary JSON"))
        except OperationalError as exc:
            # 多进程同时启动时，另一个进程可能已率先完成迁移。
            if "duplicate column name" not in str(exc).lower():
                raise
