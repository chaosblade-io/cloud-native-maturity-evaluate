import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_r_kvstore20150101.client import Client as RKvstoreClient
from alibabacloud_r_kvstore20150101 import models as kvstore_models
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.rds_oss import TairInstanceModeRecord

logger = logging.getLogger(__name__)


@dataclass
class TairCollectorConfig:
    """Tair Collector 配置"""
    aliyun_credentials: Optional[CredentialClient] = None
    region: str = ""
    tair_instance_ids: List[str] = None

    def __post_init__(self):
        if self.tair_instance_ids is None:
            self.tair_instance_ids = []


class TairCollector(CollectorBase):
    def __init__(
        self, config: TairCollectorConfig, instance_ids: Optional[List[str]] = None
    ):
        self.config = config
        self.region = config.region
        self.instance_ids = instance_ids
        self.client = self._create_client()

    def _create_client(self) -> RKvstoreClient:
        creds = self.config.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"r-kvstore.{self.region}.aliyuncs.com",
            protocol="https",
        )
        return RKvstoreClient(config)

    def _get_instance_ids(self) -> List[str]:
        """获取要采集的实例 ID 列表"""
        # 优先使用传入的 instance_ids
        if self.instance_ids:
            return self.instance_ids

        # 其次使用 config 中的 tair_instance_ids 列表
        if self.config.tair_instance_ids:
            return self.config.tair_instance_ids

        return []

    def name(self) -> str:
        return "tair_collector"

    def _collect(self) -> List:
        records: List[TairInstanceModeRecord] = []

        instance_ids = self._get_instance_ids()

        if instance_ids:
            # 采集指定实例
            logger.info(f"开始采集 {len(instance_ids)} 个指定 Tair/Redis 实例...")
            for instance_id in instance_ids:
                instance_records = self._collect_instance_detail(instance_id)
                for record in instance_records:
                    records.append(record)
                    logger.info(f"采集实例: {record.instance_id}")
        else:
            # 采集所有实例
            logger.info("开始采集所有 Tair/Redis 实例...")
            records = self._collect_all_instances()

        logger.info(f"总计采集到 {len(records)} 个 Tair/Redis 实例")

        return records

    def _collect_all_instances(self) -> List[TairInstanceModeRecord]:
        """采集该区域下所有 Tair/Redis 实例"""
        records: List[TairInstanceModeRecord] = []

        page_no = 1
        page_size = 100
        while True:
            request = kvstore_models.DescribeInstancesRequest(
                region_id=self.region,
                page_number=page_no,
                page_size=page_size,
            )
            response = self.client.describe_instances(request)
            
            if response.status_code != 200:
                raise Exception(f"DescribeInstances API 调用失败: {response.status_code}")

            body = response.body
            instances = body.instances.kvstore_instance

            for item in instances:
                record = self._parse_instance(item)
                records.append(record)
                logger.info(f"采集实例: {item.instance_id} ({item.instance_name})")

            # 检查是否还有下一页
            total_count = body.total_count
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _collect_instance_detail(self, instance_id: str) -> List[TairInstanceModeRecord]:
        records: List[TairInstanceModeRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_instances(kvstore_models.DescribeInstancesRequest(
                region_id=self.region,
                instance_ids=instance_id,
                page_number=page_no,
                page_size=page_size,
            ))
            body = response.body
            if response.status_code != 200:
                raise Exception(f"DescribeInstances API 调用失败: {response.status_code}")

            for item in body.instances.kvstore_instance:
                record = self._parse_instance(item)
                records.append(record)
                logger.info(f"采集实例: {record.instance_id} ({record.instance_name})")

            # 检查是否还有下一页
            total_count = body.total_count
            if len(records) >= total_count:
                break
            page_no += 1
        
        return records

    def _parse_instance(
        self,
        item: kvstore_models.DescribeInstancesResponseBodyInstancesKVStoreInstance,
    ) -> TairInstanceModeRecord:
        """解析实例信息为 TairInstanceModeRecord"""
        
        # 解析架构类型
        # cluster: 集群版, standard: 标准版, rwsplit: 读写分离版
        architecture_type = item.architecture_type or "standard"
        
        # 判断是否为 Serverless 实例
        is_serverless = item.instance_class == "tair.serverless" if item.instance_class else False
        
        # 获取内存大小（单位：MB）
        memory_size = item.capacity if item.capacity else 0
        
        # 检查是否配置了 TTL（通过参数或实例类型判断）
        # 注意：这里需要调用额外的 API 才能准确判断，当前使用简单判断
        has_ttl_config = False  # 默认值，需要通过其他 API 获取配置参数
        
        return TairInstanceModeRecord(
            instance_id=item.instance_id,
            instance_name=item.instance_name or "",
            architecture_type=architecture_type,
            is_serverless=is_serverless,
            pay_type=item.charge_type or "",
            memory_size=memory_size,
            has_ttl_config=has_ttl_config,
            region=item.region_id or self.region,
        )
