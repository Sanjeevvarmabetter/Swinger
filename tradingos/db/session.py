"""Engine/session factories and backups for the two SQLite databases."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tradingos.config import load_config
from tradingos.db.models import LongTermBase, TradingBase


def make_engine(path: Path | str) -> Engine:
    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{path}"
    return create_engine(url, future=True, connect_args={"check_same_thread": False})


def add_missing_columns(eng: Engine, base) -> list[str]:
    """Lightweight additive migration: ALTER TABLE ADD COLUMN for model columns missing in an existing table.

    Only nullable/defaulted scalar columns are added; nothing is ever dropped or rewritten.
    """
    from sqlalchemy import inspect, text
    insp = inspect(eng)
    added = []
    with eng.begin() as conn:
        for table in base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=eng.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    v = col.default.arg
                    default = f" DEFAULT {v!r}" if isinstance(v, str) else f" DEFAULT {v}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}{default}'))
                added.append(f"{table.name}.{col.name}")
    return added


@lru_cache(maxsize=None)
def _trading_engine(path: str) -> Engine:
    eng = make_engine(path)
    TradingBase.metadata.create_all(eng)
    add_missing_columns(eng, TradingBase)
    return eng


@lru_cache(maxsize=None)
def _longterm_engine(path: str) -> Engine:
    eng = make_engine(path)
    LongTermBase.metadata.create_all(eng)
    return eng


def trading_engine() -> Engine:
    return _trading_engine(str(load_config().trading_db_path))


def longterm_engine() -> Engine:
    return _longterm_engine(str(load_config().longterm_db_path))


@contextmanager
def session_scope(engine: Engine | None = None):
    """Transactional scope around a series of operations (defaults to trading.db)."""
    factory = sessionmaker(bind=engine or trading_engine(), expire_on_commit=False, future=True)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def backup_databases(keep: int = 30) -> list[Path]:
    """Hot-backup both SQLite files using the sqlite3 backup API (safe while in use)."""
    cfg = load_config()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out: list[Path] = []
    for src in (cfg.trading_db_path, cfg.longterm_db_path):
        if not src.exists():
            continue
        dest = cfg.backup_dir / f"{src.stem}-{stamp}.db"
        with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
            s.backup(d)
        out.append(dest)
        backups = sorted(cfg.backup_dir.glob(f"{src.stem}-*.db"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)
    return out


def daily_backup_if_needed() -> Path | None:
    """Create at most one automatic backup per calendar day."""
    cfg = load_config()
    today = datetime.now().strftime("%Y%m%d")
    if any(cfg.backup_dir.glob(f"trading-{today}-*.db")):
        return None
    made = backup_databases()
    return made[0] if made else None


def restore_note() -> str:
    return ("To restore: stop the app, copy a file from the backups folder over data/trading.db "
            "(or longterm.db), then restart.")


__all__ = ["session_scope", "trading_engine", "longterm_engine", "make_engine",
           "backup_databases", "daily_backup_if_needed", "restore_note"]
