"""
SESORA Store 模块

数据存储抽象和实现。
"""

from .sqlite_store import DataStore, SQLiteDataStore

__all__ = [
    "DataStore",
    "SQLiteDataStore",
]
