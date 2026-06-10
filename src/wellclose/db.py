from collections.abc import Iterator
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from .config import settings

_engine = None
_Session: sessionmaker[Session] | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(settings().database_url, pool_pre_ping=True)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Create extensions + schema (T1.4)."""
    from . import models  # noqa: F401
    eng = engine()
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    models.Base.metadata.create_all(eng)
