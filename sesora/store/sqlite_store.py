"""
SQLiteDataStore 实现

平台无关数据层的存储引擎实现，使用 SQLite 作为后端存储。
支持 DataItem 的持久化、查询和多来源管理。
"""
import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Union

from dacite import from_dict, Config

from ..core.dataitem import DataItem, DataSource
from ..schema.registry import get_record_type


class DataStore(ABC):
    """
    DataStore 抽象基类
    
    定义平台无关数据层的标准接口，所有存储引擎实现需继承此类。
    """
    
    @abstractmethod
    def put(self, name: str, source: DataSource) -> None:
        """写入某 DataItem 的一个来源数据"""
        pass
    
    @abstractmethod
    def available(self, name: str) -> bool:
        """判断 DataItem 是否可用（任一来源 ok 即可用）"""
        pass
    
    @abstractmethod
    def get(self, name: str, from_collector: str = None) -> list[Any]:
        """
        获取 DataItem 的 records
        
        Args:
            name: DataItem 名称
            from_collector: 指定采集器来源，为 None 则返回最优来源
            
        Returns:
            记录列表，自动反序列化为对应强类型
        """
        pass
    
    @abstractmethod
    def get_merged(self, name: str, dedup_key: str) -> list[Any]:
        """
        合并所有来源的记录，按 dedup_key 字段去重
        
        Args:
            name: DataItem 名称
            dedup_key: 去重字段名
            
        Returns:
            去重后的记录列表
        """
        pass
    
    @abstractmethod
    def query(self, name: str, **filters) -> list[Any]:
        """
        基于字段过滤查询
        
        Args:
            name: DataItem 名称
            **filters: 字段过滤条件
            
        Returns:
            符合条件的记录列表
        """
        pass
    
    @abstractmethod
    def all_available(self, names: list[str]) -> bool:
        """判断一批 DataItem 是否全部可用"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭存储连接"""
        pass


class SQLiteDataStore(DataStore):
    """
    SQLite 实现的 DataStore
    
    使用 SQLite 作为存储引擎，支持：
    - 零部署，单文件嵌入式
    - SQL 过滤查询
    - 持久化，支持增量补充
    - 内存缓存，提升读取性能
    """
    
    def __init__(self, db_path: Union[str, Path] = None):
        """
        初始化 SQLiteDataStore
        
        Args:
            db_path: SQLite 数据库文件路径，为 None 则使用内存数据库
        """
        if db_path is None:
            # 使用内存数据库
            self.db_path = None
            self._conn = sqlite3.connect(":memory:")
        else:
            self.db_path = Path(db_path)
            self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._cache: dict[str, DataItem] = {}  # 内存缓存
        self._init_tables()
    
    def _init_tables(self) -> None:
        """初始化数据库表结构"""
        cursor = self._conn.cursor()
        
        # DataItem 元数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_items (
                name TEXT PRIMARY KEY,
                status TEXT CHECK(status IN ('available', 'unavailable', 'partial')),
                updated_at INTEGER
            )
        """)
        
        # 数据来源表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_sources (
                item_name TEXT,
                collector TEXT,
                status TEXT CHECK(status IN ('ok', 'error', 'not_configured')),
                collected_at INTEGER,
                records_json TEXT,
                PRIMARY KEY (item_name, collector),
                FOREIGN KEY (item_name) REFERENCES data_items(name)
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_data_sources_item_name 
            ON data_sources(item_name)
        """)
        
        self._conn.commit()
    
    @staticmethod
    def _serialize_record(record) -> Any:
        """
        将一个记录对象递归序列化为 JSON 可序列化的结构
        
        支持嵌套 dataclass、list、dict 和 datetime。
        """
        if hasattr(record, '__dataclass_fields__'):
            return {k: SQLiteDataStore._serialize_record(v) for k, v in record.__dict__.items()}
        elif isinstance(record, datetime):
            return record.isoformat()
        elif isinstance(record, list):
            return [SQLiteDataStore._serialize_record(item) for item in record]
        elif isinstance(record, dict):
            return {k: SQLiteDataStore._serialize_record(v) for k, v in record.items()}
        else:
            return record

    def put(self, name: str, source: DataSource) -> None:
        """
        写入某 DataItem 的一个来源数据
        
        Args:
            name: DataItem 名称
            source: 数据来源
        """
        cursor = self._conn.cursor()
        now = int(datetime.now().timestamp())
        
        # 序列化 records（递归处理嵌套 dataclass）
        records_data = [self._serialize_record(record) for record in source.records]
        
        records_json = json.dumps(records_data, ensure_ascii=False, default=str)
        
        # 插入或更新 data_items
        cursor.execute("""
            INSERT INTO data_items (name, status, updated_at)
            VALUES (?, 'available', ?)
            ON CONFLICT(name) DO UPDATE SET
                status = CASE 
                    WHEN excluded.status = 'available' OR data_items.status = 'available' 
                    THEN 'available' 
                    ELSE 'partial' 
                END,
                updated_at = excluded.updated_at
        """, (name, now))
        
        # 插入或更新 data_sources
        cursor.execute("""
            INSERT INTO data_sources (item_name, collector, status, collected_at, records_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(item_name, collector) DO UPDATE SET
                status = excluded.status,
                collected_at = excluded.collected_at,
                records_json = excluded.records_json
        """, (name, source.collector, source.status, 
              int(source.collected_at.timestamp()), records_json))
        
        self._conn.commit()
        
        # 清除缓存
        if name in self._cache:
            del self._cache[name]
    
    def available(self, name: str) -> bool:
        """
        判断 DataItem 是否可用
        
        只要任一来源 status=ok，整体即为 available
        
        Args:
            name: DataItem 名称
            
        Returns:
            是否可用
        """
        # 先检查缓存
        if name in self._cache:
            return self._cache[name].status == "available"
        
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT status FROM data_sources 
            WHERE item_name = ? AND status = 'ok'
            LIMIT 1
        """, (name,))
        
        return cursor.fetchone() is not None
    
    def _deserialize_records(self, name: str, records_data: list[dict]) -> list[Any]:
        """
        将 JSON 数据反序列化为对应的强类型 Record
        
        Args:
            name: DataItem 名称
            records_data: JSON 数据列表
            
        Returns:
            强类型 Record 列表
        """
        record_type = get_record_type(name)
        if record_type is None:
            # 未找到类型定义，返回原始 dict
            return records_data
        
        records = []
        for data in records_data:
            try:
                record = from_dict(
                    data_class=record_type,
                    data=data,
                    config=Config(
                        type_hooks={
                            datetime: lambda v: (
                                datetime.fromisoformat(v.replace('Z', '+00:00'))
                                if isinstance(v, str) else v
                            )
                        }
                    ),
                )
                records.append(record)
            except Exception as e:
                # 反序列化失败，记录日志并返回原始 dict
                import logging
                logging.getLogger(__name__).warning(
                    f"DataItem '{name}' 第 {len(records)+1} 条记录反序列化失败: {e}, 将使用原始 dict"
                )
                records.append(data)
        
        return records
    
    def get(self, name: str, from_collector: str = None) -> list[Any]:
        """
        获取 DataItem 的 records
        
        Args:
            name: DataItem 名称
            from_collector: 指定采集器来源，为 None 则返回最优来源（status=ok 的第一个来源）
            
        Returns:
            记录列表，自动反序列化为对应强类型
        """
        cursor = self._conn.cursor()
        
        if from_collector:
            # 指定来源
            cursor.execute("""
                SELECT records_json FROM data_sources 
                WHERE item_name = ? AND collector = ? AND status = 'ok'
            """, (name, from_collector))
        else:
            # 获取最优来源（status=ok 的第一个）
            cursor.execute("""
                SELECT records_json FROM data_sources 
                WHERE item_name = ? AND status = 'ok'
                ORDER BY collected_at DESC
                LIMIT 1
            """, (name,))
        
        row = cursor.fetchone()
        if row is None:
            return []
        
        records_data = json.loads(row['records_json'])
        return self._deserialize_records(name, records_data)
    
    def get_merged(self, name: str, dedup_key: str) -> list[Any]:
        """
        合并所有来源的记录，按 dedup_key 字段去重
        
        Args:
            name: DataItem 名称
            dedup_key: 去重字段名
            
        Returns:
            去重后的记录列表
        """
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT records_json FROM data_sources 
            WHERE item_name = ? AND status = 'ok'
        """, (name,))
        
        seen_keys = set()
        merged_records = []
        
        for row in cursor.fetchall():
            records_data = json.loads(row['records_json'])
            records = self._deserialize_records(name, records_data)
            
            for record in records:
                key_value = getattr(record, dedup_key, None)
                if key_value is None:
                    # 尝试从 dict 获取
                    key_value = record.get(dedup_key) if isinstance(record, dict) else None
                
                if key_value is not None and key_value not in seen_keys:
                    seen_keys.add(key_value)
                    merged_records.append(record)
                elif key_value is None:
                    # 无法去重，直接添加
                    merged_records.append(record)
        
        return merged_records
    
    def query(self, name: str, **filters) -> list[Any]:
        """
        基于字段过滤查询
        
        注意：当前实现为内存过滤，大数据量时性能有限。
        如需高性能查询，可考虑在 records_json 上建立虚拟表或使用 JSON1 扩展。
        
        Args:
            name: DataItem 名称
            **filters: 字段过滤条件，支持精确匹配
            
        Returns:
            符合条件的记录列表
        """
        records = self.get(name)
        
        if not filters:
            return records
        
        filtered = []
        for record in records:
            match = True
            for key, value in filters.items():
                record_value = getattr(record, key, None)
                if record_value is None and isinstance(record, dict):
                    record_value = record.get(key)
                
                if record_value != value:
                    match = False
                    break
            
            if match:
                filtered.append(record)
        
        return filtered
    
    def all_available(self, names: list[str]) -> bool:
        """
        判断一批 DataItem 是否全部可用
        
        Args:
            names: DataItem 名称列表
            
        Returns:
            是否全部可用
        """
        return all(self.available(name) for name in names)
    
    def get_dataitem_status(self, name: str) -> dict:
        """
        获取 DataItem 的详细状态信息
        
        Args:
            name: DataItem 名称
            
        Returns:
            包含状态和来源信息的字典
        """
        cursor = self._conn.cursor()
        
        # 获取整体状态
        cursor.execute("""
            SELECT status, updated_at FROM data_items WHERE name = ?
        """, (name,))
        item_row = cursor.fetchone()
        
        # 获取各来源状态
        cursor.execute("""
            SELECT collector, status, collected_at FROM data_sources 
            WHERE item_name = ?
        """, (name,))
        sources = [
            {
                "collector": row["collector"],
                "status": row["status"],
                "collected_at": datetime.fromtimestamp(row["collected_at"])
            }
            for row in cursor.fetchall()
        ]
        
        return {
            "name": name,
            "status": item_row["status"] if item_row else "unavailable",
            "updated_at": datetime.fromtimestamp(item_row["updated_at"]) if item_row and item_row["updated_at"] else None,
            "sources": sources
        }
    
    def list_dataitems(self) -> list[str]:
        """
        列出所有已存储的 DataItem 名称
        
        Returns:
            DataItem 名称列表
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT name FROM data_items")
        return [row["name"] for row in cursor.fetchall()]
    
    def close(self) -> None:
        """关闭数据库连接"""
        self._conn.close()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
