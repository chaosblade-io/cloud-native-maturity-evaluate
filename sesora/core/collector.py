from datetime import datetime
from typing import Any, List
from abc import ABC, abstractmethod
from sesora.core.dataitem import SourceStatus
from sesora.core.dataitem import DataSource


class CollectorBase(ABC):
    @abstractmethod
    def name(self) -> str:
        """采集器名称，必须唯一"""
        pass

    def collect(self) -> DataSource:
        status = SourceStatus.OK
        records = []
        try:
            records = self._collect()
        except Exception as e:
            status = SourceStatus.ERROR
            print(f"Error collecting data for {self.name()}: {e}")

        records_dict = {}
        for record in records:
            records_dict.setdefault(record.DATAITEM_NAME, []).append(record)

        return DataSource(
            collector=self.name(),
            collected_at=datetime.now(),
            status=status,
            records=records,
            records_dict=records_dict,
        )

    @abstractmethod
    def _collect(self) -> List[Any]:
        """子类实现具体的采集逻辑，返回 DataSource 对象"""
        pass
