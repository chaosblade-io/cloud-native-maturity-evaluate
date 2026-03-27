import logging
from datetime import datetime
from typing import List, Optional

from alibabacloud_rds20140815.client import Client as RdsClient

from alibabacloud_rds20140815 import models as rds_models
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.rds_oss import (
    RdsInstanceRecord,
    RdsBackupPolicyRecord,
    RdsProxyRecord,
)

logger = logging.getLogger(__name__)


class RDSCollector(CollectorBase):
    def __init__(
        self, context: AssessmentContext, instance_ids: Optional[List[str]] = None
    ):
        self.context = context
        self.rds_region = context.rds_region or context.region
        self.instance_ids = instance_ids
        self.client = self._create_client()

    def _create_client(self) -> RdsClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint="rds.aliyuncs.com",
            protocol="https",
        )
        return RdsClient(config)

    def _get_instance_ids(self) -> List[str]:
        # 优先使用传入的 instance_ids
        if self.instance_ids:
            return self.instance_ids

        # 其次使用 context 中的 rds_instance_ids 列表
        if self.context.rds_instance_ids:
            return self.context.rds_instance_ids

        return []

    def name(self) -> str:
        return "rds_collector"

    def _collect(self) -> List:
        records: List = []

        instance_ids = self._get_instance_ids()

        if instance_ids:
            # 采集指定实例
            logger.info(f"开始采集 {len(instance_ids)} 个指定 RDS 实例...")
            for instance_id in instance_ids:
                record = self._collect_instance_detail(instance_id)
                if record:
                    records.append(record)
                    logger.info(f"采集实例: {instance_id}")
        else:
            # 采集所有实例
            logger.info("开始采集所有 RDS 实例...")
            records = self._collect_all_instances()

        logger.info(f"总计采集到 {len(records)} 个 RDS 实例")

        # 采集备份策略
        logger.info("开始采集备份策略...")
        instance_records = [r for r in records if isinstance(r, RdsInstanceRecord)]
        for instance in instance_records:
            backup_policy = self._collect_backup_policy(
                instance.db_instance_id, instance.engine
            )
            records.append(backup_policy)
            logger.info(f"采集备份策略: {instance.db_instance_id}")

        backup_policy_count = sum(
            1 for r in records if isinstance(r, RdsBackupPolicyRecord)
        )
        logger.info(f"总计采集到 {backup_policy_count} 个备份策略")

        # 采集代理配置和代理实例
        logger.info("开始采集代理信息...")
        for instance in instance_records:
            proxy_instance = self._collect_db_proxy(instance.db_instance_id)
            records.append(proxy_instance)

        proxy_instance_count = sum(
            1 for r in records if isinstance(r, RdsProxyRecord)
        )
        logger.info(f"总计采集到 {proxy_instance_count} 个代理实例")

        return records

    def _collect_all_instances(self) -> List[RdsInstanceRecord]:
        records: List[RdsInstanceRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_dbinstances(
                rds_models.DescribeDBInstancesRequest(
                    region_id="cn-hongkong",  # TODO: make this configurable
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"DescribeDBInstances API 调用失败: {response.status_code}")

            items = body.items
            for item in items.dbinstance:
                instance_id = item.dbinstance_id
                record = self._collect_instance_detail(instance_id)
                records.append(record)
                logger.info(f"采集实例: {instance_id}")

            # 检查是否还有下一页
            total_count = body.total_record_count
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _collect_instance_detail(self, instance_id: str) -> RdsInstanceRecord:
        response = self.client.describe_dbinstance_attribute(
            rds_models.DescribeDBInstanceAttributeRequest(dbinstance_id=instance_id)
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"DescribeDBInstanceAttribute API 调用失败: {response.status_code}")
        items = body.items.dbinstance_attribute
        item = items[0]  # TODO: why?
        return self._parse_instance(item)

    def _collect_backup_policy(
        self, instance_id: str, engine: str
    ) -> RdsBackupPolicyRecord:
        response = self.client.describe_backup_policy(
            rds_models.DescribeBackupPolicyRequest(dbinstance_id=instance_id)
        )
        if response.status_code != 200:
            raise Exception(f"DescribeBackupPolicy API 调用失败: {response.status_code}")
        return self._parse_backup_policy(response.body, instance_id, engine)

    def _parse_backup_policy(
        self,
        backup: rds_models.DescribeBackupPolicyResponseBody,
        instance_id: str,
        engine: str,
    ) -> RdsBackupPolicyRecord:
        # 解析备份周期
        period_str = backup.preferred_backup_period
        preferred_backup_period = [
            p.strip() for p in period_str.split(",") if p.strip()
        ]

        # 解析日志备份保留天数
        log_backup_retention = backup.log_backup_retention_period

        # 检查是否启用日志备份
        enable_backup_log = backup.enable_backup_log.lower() in ["true", "1", "yes"]

        response = self.client.describe_instance_cross_backup_policy(
            rds_models.DescribeInstanceCrossBackupPolicyRequest(
                dbinstance_id=instance_id, region_id=self.rds_region
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"DescribeInstanceCrossBackupPolicy API 调用失败: {response.status_code}")
        cross_backup_enabled = body.backup_enabled == "Enabled"
        cross_backup_region = body.cross_backup_region

        return RdsBackupPolicyRecord(
            instance_id=instance_id,
            instance_type=engine,
            backup_retention_period=backup.backup_retention_period,
            preferred_backup_time=backup.preferred_backup_time,
            preferred_backup_period=preferred_backup_period,
            backup_method=backup.backup_method,
            enable_backup_log=enable_backup_log,
            log_backup_retention_period=log_backup_retention,
            cross_backup_enabled=cross_backup_enabled,
            cross_backup_region=cross_backup_region,
        )

    def _collect_db_proxy(self, instance_id: str) -> RdsProxyRecord:
        response = self.client.describe_dbproxy(
            rds_models.DescribeDBProxyRequest(
                dbinstance_id=instance_id, region_id=self.rds_region
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"DescribeDBProxy API 调用失败: {response.status_code}")

        return RdsProxyRecord(
            instance_id=instance_id,
            status=body.dbproxy_instance_status,
        )

    def _parse_instance(
        self,
        item: rds_models.DescribeDBInstanceAttributeResponseBodyItemsDBInstanceAttribute,
    ) -> RdsInstanceRecord:
        # 解析创建时间
        create_time = datetime.fromisoformat(item.creation_time.replace("Z", "+00:00"))

        # TODO: what is this?
        tags = {}
        response = self.client.describe_dbinstance_by_tags(
            rds_models.DescribeDBInstanceByTagsRequest(
                region_id=self.rds_region, dbinstance_id=item.dbinstance_id
            )
        )
        body = response.body
        if response.status_code == 200:
            tags_data = body.items.dbinstance_tag
            if tags_data:
                tag = tags_data[0].tags.tag[0]
                tags[tag.tag_key] = tag.tag_value

        # 解析自动升级小版本
        auto_upgrade = item.auto_upgrade_minor_version == "Auto"

        proxy_type = item.proxy_type
        connection_pool_enabled = proxy_type == 2

        return RdsInstanceRecord(
            db_instance_id=item.dbinstance_id,
            db_instance_description=item.dbinstance_description,
            db_instance_type=item.dbinstance_type,
            db_instance_class=item.dbinstance_class,
            engine=item.engine,
            engine_version=item.engine_version,
            db_instance_status=item.dbinstance_status,
            zone_id=item.zone_id,
            region_id=item.region_id,
            auto_upgrade_minor_version=auto_upgrade,
            instance_network_type=item.instance_network_type,
            connection_string=item.connection_string,
            port=item.port,
            max_iops=item.max_iops,
            max_connections=item.max_connections,
            connection_pool_enabled=connection_pool_enabled,
            create_time=create_time,
            tags=tags,
        )
