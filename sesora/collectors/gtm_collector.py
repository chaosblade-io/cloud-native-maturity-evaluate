import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_alidns20150109.client import Client as AlidnsClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_alidns20150109 import models as alidns_models

from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.rds_oss import GtmAddressPoolRecord

logger = logging.getLogger(__name__)


@dataclass
class GTMCollectorConfig:
    """GTM Collector 配置"""
    aliyun_credentials: Optional[CredentialClient] = None


class GTMCollector(CollectorBase):
    def __init__(self, config: GTMCollectorConfig):
        self.config = config
        self.client = self._create_client()

    def _create_client(self) -> AlidnsClient:
        creds = self.config.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"alidns.aliyuncs.com",
            protocol="https",
        )
        return AlidnsClient(config)

    def name(self) -> str:
        return "gtm_collector"

    def _collect(self) -> List:
        records: List = []

        instances = self._collect_gtm_instances()
        logger.info(f"采集到 {len(instances)} 个 GTM 实例")
        for instance_id in instances:
            logger.info(f"正在采集 GTM 实例 {instance_id} 的地址池...")
            address_pools = self._collect_gtm_address_pools(instance_id)
            records.extend(address_pools)
            logger.info(f"采集到 {len(address_pools)} 个 GTM 地址池")

        return records

    def _collect_gtm_instances(self) -> List[str]:
        instance_ids: List[str] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_dns_gtm_instances(
                alidns_models.DescribeDnsGtmInstancesRequest(
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200 or body.code != "200":
                raise Exception(f"获取 GTM 实例失败")
            for instance in body.gtm_instances:
                instance_ids.append(instance.instance_id)

            if len(body.gtm_instances) < page_size:
                break
            page_no += 1

        return instance_ids

    def _collect_gtm_address_pools(
        self, instance_id: str
    ) -> List[GtmAddressPoolRecord]:
        records: List[GtmAddressPoolRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_dns_gtm_instance_address_pools(
                alidns_models.DescribeDnsGtmInstanceAddressPoolsRequest(
                    instance_id=instance_id,
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200 or body.code != "200":
                raise Exception(f"获取 GTM 实例 {instance_id} 的地址池失败")
            pools = body.addr_pools.addr_pool
            for pool in pools:
                record = self._collect_gtm_address_pool(pool)
                records.append(record)

            if len(pools) < page_size:
                break
            page_no += 1

    def _collect_gtm_address_pool(
        self,
        instance_id: str,
        pool: alidns_models.DescribeDnsGtmInstanceAddressPoolsResponseBodyAddrPoolsAddrPool,
    ) -> GtmAddressPoolRecord:
        response = self.client.describe_dns_gtm_instance_address_pool(
            alidns_models.DescribeDnsGtmInstanceAddressPoolRequest(
                pool_id=pool.addr_pool_id
            )
        )
        if response.status_code != 200 or response.body.code != "200":
            raise Exception(f"获取 GTM 地址池 {pool.addr_pool_id} 详情失败")
        detail = response.body

        return GtmAddressPoolRecord(
            pool_id=pool.addr_pool_id,
            pool_name=pool.name,
            instance_id=instance_id,
            type=pool.type,
            min_available_addr_num=1,  # TODO
            addresses=[
                {
                    "addr": addr.addr,
                }
                for addr in detail.addrs.addr
            ],
            monitor_status=detail.monitor_status,
            lb_strategy=detail.lba_strategy,
        )
    