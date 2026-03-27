import logging
from datetime import datetime
from dacite import from_dict, Config

from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.registry import DATAITEM_SCHEMA_REGISTRY

logger = logging.getLogger(__name__)


class GenericCollector(CollectorBase):
    def __init__(self, data, collector_name="external"):
        self.data = data
        self.collector_name = collector_name

    def name(self) -> str:
        return self.collector_name

    def _collect(self) -> list:
        records = []
        for dataitem_name, records_data in self.data.items():
            record_class = DATAITEM_SCHEMA_REGISTRY.get(dataitem_name)
            if not record_class:
                logger.warning(f"未知的 DataItem: '{dataitem_name}'，已跳过")
                continue
            for data in records_data:
                record = from_dict(
                    data_class=record_class,
                    data=data,
                    config=Config(
                        strict=False,
                        cast=[int, float, bool, str],
                        type_hooks={datetime: datetime.fromisoformat},
                    ),
                )
                records.append(record)
            return records
