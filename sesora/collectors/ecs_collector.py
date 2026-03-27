import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_ecs20140526.client import Client as AcsClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.ecs import (
    EcsInstanceRecord,
    EcsSecurityGroupRecord,
    EcsSecurityGroupRuleRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class ECSCollectorConfig:
    """ECS Collector 配置"""
    aliyun_credentials: Optional[CredentialClient] = None
    region: str = ""


class ECSCollector(CollectorBase):
    def __init__(self, config: ECSCollectorConfig):
        self.config = config
        self.client = self._create_client()

    def _create_client(self) -> AcsClient:
        creds = self.config.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"ecs.{self.config.region}.aliyuncs.com",
            protocol="https",
        )
        return AcsClient(config)

    def name(self) -> str:
        return "ecs_collector"

    def _collect(self) -> List:
        records: List = []

        # 1. 采集 ECS 实例
        instances = self._collect_instances()
        records.extend(instances)
        logger.info(f"采集到 {len(instances)} 个 ECS 实例")

        # 2. 采集安全组
        security_groups = self._collect_security_groups()
        records.extend(security_groups)
        logger.info(f"采集到 {len(security_groups)} 个安全组")

        # 3. 采集安全组规则
        for sg in security_groups:
            rules = self._collect_security_group_rules(sg.security_group_id)
            records.extend(rules)
            logger.info(f"安全组 {sg.security_group_id}: 采集到 {len(rules)} 条规则")

        return records

    def _collect_instances(self) -> List[EcsInstanceRecord]:
        records: List[EcsInstanceRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_instances(
                ecs_models.DescribeInstancesRequest(
                    region_id=self.config.region,
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"DescribeInstances API 调用失败: {response.status_code}")

            instances = body.instances
            for instance in instances.instance:
                record = self._parse_instance(instance)
                if record:
                    records.append(record)

            total_count = body.total_count
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    @staticmethod
    def _parse_time(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _parse_instance(
        self, instance: ecs_models.DescribeInstancesResponseBodyInstancesInstance
    ) -> EcsInstanceRecord:

        # 解析 IP 地址
        private_ip = ""
        public_ip = ""

        vpc_attributes = instance.vpc_attributes
        if (
            vpc_attributes
            and vpc_attributes.private_ip_address
            and vpc_attributes.private_ip_address.ip_address
        ):
            private_ip = vpc_attributes.private_ip_address.ip_address[0]

        if instance.public_ip_address and instance.public_ip_address.ip_address:
            public_ip = instance.public_ip_address.ip_address[0]
        elif instance.eip_address and instance.eip_address.ip_address:
            public_ip = instance.eip_address.ip_address

        # 解析时间
        creation_time = self._parse_time(instance.creation_time)
        expired_time = None
        if instance.expired_time and instance.expired_time != "2099-12-31T23:59Z":
            expired_time = self._parse_time(instance.expired_time)

        # 标签
        tags = {}
        if instance.tags and instance.tags.tag:
            for tag in instance.tags.tag:
                if tag.tag_key:
                    tags[tag.tag_key] = tag.tag_value or ""

        # 安全组
        security_group_ids: List[str] = []
        if (
            instance.security_group_ids
            and instance.security_group_ids.security_group_id
        ):
            security_group_ids = list(instance.security_group_ids.security_group_id)

        return EcsInstanceRecord(
            instance_id=instance.instance_id or "",
            instance_name=instance.instance_name or "",
            instance_type=instance.instance_type or "",
            status=instance.status or "",
            region_id=instance.region_id or "",
            zone_id=instance.zone_id or "",
            vpc_id=vpc_attributes.vpc_id if vpc_attributes else "",
            vswitch_id=vpc_attributes.v_switch_id if vpc_attributes else "",
            private_ip=private_ip,
            public_ip=public_ip,
            cpu=instance.cpu or 0,
            memory=instance.memory or 0,
            os_name=instance.osname or "",
            os_type=instance.ostype or "linux",
            image_id=instance.image_id or "",
            instance_charge_type=instance.instance_charge_type or "PostPaid",
            internet_charge_type=instance.internet_charge_type or "",
            internet_max_bandwidth_out=instance.internet_max_bandwidth_out or 0,
            internet_max_bandwidth_in=instance.internet_max_bandwidth_in or 0,
            creation_time=creation_time,
            expired_time=expired_time,
            tags=tags,
            security_group_ids=security_group_ids,
        )

    def _collect_security_groups(self) -> List[EcsSecurityGroupRecord]:
        records: List[EcsSecurityGroupRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_security_groups(
                ecs_models.DescribeSecurityGroupsRequest(
                    region_id=self.config.region,
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"DescribeSecurityGroups API 调用失败: {response.status_code}")

            security_groups = body.security_groups
            for sg in security_groups.security_group:
                record = self._parse_security_group(sg)
                records.append(record)

            total_count = body.total_count
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_security_group(
        self,
        sg: ecs_models.DescribeSecurityGroupsResponseBodySecurityGroupsSecurityGroup,
    ) -> EcsSecurityGroupRecord:
        tags = {}
        if sg.tags and sg.tags.tag:
            for tag in sg.tags.tag:
                if tag.tag_key:
                    tags[tag.tag_key] = tag.tag_value or ""

        return EcsSecurityGroupRecord(
            security_group_id=sg.security_group_id or "",
            security_group_name=sg.security_group_name or "",
            vpc_id=sg.vpc_id or "",
            description=sg.description or "",
            security_group_type=sg.security_group_type or "normal",
            create_time=self._parse_time(sg.creation_time),
            tags=tags,
        )

    def _collect_security_group_rules(
        self, security_group_id: str
    ) -> List[EcsSecurityGroupRuleRecord]:
        records: List[EcsSecurityGroupRuleRecord] = []

        response = self.client.describe_security_group_attribute(
            ecs_models.DescribeSecurityGroupAttributeRequest(
                region_id=self.config.region,
                security_group_id=security_group_id,
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"DescribeSecurityGroupAttribute API 调用失败: {response.status_code}")

        # 解析入方向规则
        for rule in body.permissions.permission:
            record = self._parse_security_group_rule(rule, security_group_id)
            records.append(record)

        return records

    def _parse_security_group_rule(
        self,
        rule: ecs_models.DescribeSecurityGroupAttributeResponseBodyPermissionsPermission,
        security_group_id: str,
    ) -> EcsSecurityGroupRuleRecord:
        return EcsSecurityGroupRuleRecord(
            security_group_id=security_group_id,
            direction=rule.direction or "ingress",
            ip_protocol=rule.ip_protocol or "TCP",
            port_range=rule.port_range or "",
            source_cidr_ip=rule.source_cidr_ip or "",
            dest_cidr_ip=rule.dest_cidr_ip or "",
            source_group_id=rule.source_group_id or "",
            dest_group_id=rule.dest_group_id or "",
            policy=rule.policy or "accept",
            priority=rule.priority or 1,
            nic_type=rule.nic_type or "intranet",
            description=rule.description or "",
        )
