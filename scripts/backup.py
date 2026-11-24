"""Back up trading.db and longterm.db (keeps last 30 of each).  Usage: python scripts/backup.py"""
import _bootstrap  # noqa: F401

from tradingos.db.session import backup_databases

if __name__ == "__main__":
    for p in backup_databases():
        print("backup:", p)
