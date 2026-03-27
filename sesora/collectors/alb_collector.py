import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_alb20200616 import models as alb_models
from alibabacloud_alb20200616.client import Client as AlbClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.rds_oss import AlbListenerRecord

logger = logging.getLogger(__name__)


@dataclass
class ALBCollectorConfig:
    """ALB Collector 配置"""
    aliyun_credentials: Optional[CredentialClient] = None
    region: str = ""
    load_balancer_ids: List[str] = None

    def __post_init__(self):
        if self.load_balancer_ids is None:
            self.load_balancer_ids = []


class ALBCollector(CollectorBase):
    def __init__(self, config: ALBCollectorConfig):
        self.config = config
        self.load_balancer_ids = config.load_balancer_ids
        self.client = self._create_client()

    def _create_client(self) -> AlbClient:
        creds = self.config.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"alb.{self.config.region}.aliyuncs.com",
            protocol="https",
        )
        return AlbClient(config)

    def name(self) -> str:
        return "alb_collector"

    def _collect(self) -> List:
        records: List = []

        listeners = self._collect_listeners()
        records.extend(listeners)
        logger.info(f"总计采集到 {len(listeners)} 个 ALB 监听器")

        return records

    def _collect_listeners(self) -> List[AlbListenerRecord]:
        records: List[AlbListenerRecord] = []

        next_token = None
        max_results = 100
        while True:
            request = alb_models.ListListenersRequest(
                max_results=max_results,
            )
            if self.load_balancer_ids:
                request.load_balancer_ids = self.load_balancer_ids
            if next_token:
                request.next_token = next_token

            response = self.client.list_listeners(request)
            body = response.body
            if response.status_code != 200:
                raise Exception(f"ListListeners API 调用失败: {response.status_code}")

            for listener in body.listeners:
                record = self._parse_listener(listener)
                records.append(record)

            # 检查分页
            next_token = response.body.next_token
            if not next_token:
                break

        return records

    def _parse_listener(
        self, listener: alb_models.ListListenersResponseBodyListeners
    ) -> AlbListenerRecord:
        listener_id = listener.listener_id
        load_balancer_id = listener.load_balancer_id

        default_actions = [act.to_map() for act in listener.default_actions]

        # 解析 QUIC 配置
        quic_config = {}
        if listener.quic_config:
            quic_config = listener.quic_config.to_map()

        # 解析 XForwardedFor 配置（注意 SDK 字段名是 xforwarded_for_config）
        x_forwarded_for_config = {}
        if listener.xforwarded_for_config:
            x_forwarded_for_config = listener.xforwarded_for_config.to_map()

        return AlbListenerRecord(
            listener_id=listener_id,
            load_balancer_id=load_balancer_id,
            listener_protocol=listener.listener_protocol,
            listener_port=int(listener.listener_port),
            default_actions=default_actions,
            gzip_enabled=bool(listener.gzip_enabled),
            http2_enabled=bool(listener.http_2enabled),
            quic_config=quic_config,
            x_forwarded_for_config=x_forwarded_for_config,
        )
