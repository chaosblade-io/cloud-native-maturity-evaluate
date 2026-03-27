import json
import logging
from datetime import datetime
from typing import List, Optional

from alibabacloud_eventbridge20200401.client import Client as EventBridgeClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_eventbridge20200401 import models as eventbridge_models

from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.eventbridge import (
    EventBridgeEventSourceRecord,
    EventBridgeEventBusRecord,
    EbEventRuleRecord,
    EbEventTargetRecord,
)

logger = logging.getLogger(__name__)


class EventBridgeCollector(CollectorBase):
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.client = self._create_client()

    def _create_client(self) -> EventBridgeClient:
        config = open_api_models.Config(
            credential=self.context.aliyun_credentials,
            endpoint=f"eventbridge-console.{self.context.region}.aliyuncs.com",
            protocol="https",
        )
        return EventBridgeClient(config)

    def name(self) -> str:
        return "eventbridge_collector"

    def _collect(self) -> List:
        records: List = []

        buses = self._collect_event_buses()

        rules, targets, bus_rule_count = self._collect_rules_and_targets(
            [bus.event_bus_name for bus in buses]
        )
        for bus in buses:
            bus.rule_count = bus_rule_count.get(bus.event_bus_name, 0)

        records.extend(buses)
        logger.info(f"采集到 {len(buses)} 个事件总线")
        records.extend(rules)
        logger.info(f"采集到 {len(rules)} 条事件规则")
        records.extend(targets)
        logger.info(f"采集到 {len(targets)} 条事件目标")

        official_sources = self._collect_aliyun_official_event_sources()
        records.extend(official_sources)
        logger.info(f"采集到 {len(official_sources)} 个阿里云官方事件源")

        user_defined_sources = self._collect_user_defined_event_sources()
        records.extend(user_defined_sources)
        logger.info(f"采集到 {len(user_defined_sources)} 个外部事件源")

        return records

    def _collect_aliyun_official_event_sources(
        self,
    ) -> List[EventBridgeEventSourceRecord]:
        if self.client is None:
            return []

        response = self.client.list_aliyun_official_event_sources()
        body = response.body
        if response.status_code != 200 or not body.success:
            code = body.code or response.status_code
            message = body.message or "unknown error"
            raise Exception(
                f"ListAliyunOfficialEventSources API 调用失败: {code} {message}"
            )

        data = body.data
        source_list = data.event_source_list if data and data.event_source_list else []
        allowed_bus_names = set(self.context.eventbridge_bus_names)

        records: List[EventBridgeEventSourceRecord] = []
        for source in source_list:
            record = self._parse_official_event_source(source)
            if allowed_bus_names and record.event_bus_name not in allowed_bus_names:
                continue
            records.append(record)

        return records

    def _collect_event_buses(self) -> List[EventBridgeEventBusRecord]:
        if self.client is None:
            return []

        next_token: Optional[str] = None
        records: List[EventBridgeEventBusRecord] = []

        while True:
            request = eventbridge_models.ListEventBusesRequest(
                limit=100,
                next_token=next_token,
            )
            response = self.client.list_event_buses(request)
            body = response.body
            if response.status_code != 200 or not body.success:
                code = body.code or response.status_code
                message = body.message or "unknown error"
                raise Exception(f"ListEventBuses API 调用失败: {code} {message}")

            data = body.data
            bus_list = data.event_buses if data and data.event_buses else []
            for bus in bus_list:
                records.append(self._parse_event_bus(bus))

            if not data or not data.next_token:
                break
            next_token = data.next_token

        return records

    def _collect_user_defined_event_sources(
        self,
    ) -> List[EventBridgeEventSourceRecord]:
        if self.client is None:
            return []

        allowed_bus_names = set(self.context.eventbridge_bus_names)
        next_token: Optional[str] = None
        records: List[EventBridgeEventSourceRecord] = []

        while True:
            request = eventbridge_models.ListUserDefinedEventSourcesRequest(
                limit=100,
                next_token=next_token,
            )

            response = self.client.list_user_defined_event_sources(request)
            body = response.body
            if response.status_code != 200 or not body.success:
                code = body.code or response.status_code
                message = body.message or "unknown error"
                raise Exception(
                    f"ListUserDefinedEventSources API 调用失败: {code} {message}"
                )

            data = body.data
            source_list = data.event_source_list if data and data.event_source_list else []
            for source in source_list:
                record = self._parse_user_defined_event_source(source)
                if allowed_bus_names and record.event_bus_name not in allowed_bus_names:
                    continue
                records.append(record)

            if not data or not data.next_token:
                break
            next_token = data.next_token

        return records

    def _collect_rules_and_targets(
        self,
        bus_names: List[str],
    ) -> tuple[List[EbEventRuleRecord], List[EbEventTargetRecord], dict[str, int]]:
        if self.client is None:
            return [], [], {}

        rule_records: List[EbEventRuleRecord] = []
        target_records: List[EbEventTargetRecord] = []
        bus_rule_count: dict[str, int] = {}

        for bus_name in bus_names:
            next_token: Optional[str] = None

            while True:
                request = eventbridge_models.ListRulesRequest(
                    event_bus_name=bus_name,
                    limit=100,
                    next_token=next_token,
                )
                response = self.client.list_rules(request)
                body = response.body
                if response.status_code != 200 or not body.success:
                    code = body.code or response.status_code
                    message = body.message or "unknown error"
                    raise Exception(f"ListRules API 调用失败: {code} {message}")

                data = body.data
                rules = data.rules if data and data.rules else []

                for rule in rules:
                    rule_records.append(self._parse_rule(rule))
                    bus_rule_count[bus_name] = bus_rule_count.get(bus_name, 0) + 1

                    for target in rule.targets or []:
                        target_records.append(
                            self._parse_rule_target(
                                target=target,
                                rule_name=rule.rule_name or "",
                                event_bus_name=rule.event_bus_name or bus_name,
                            )
                        )

                if not data or not data.next_token:
                    break
                next_token = data.next_token

        return rule_records, target_records, bus_rule_count

    def _parse_official_event_source(
        self,
        source: eventbridge_models.ListAliyunOfficialEventSourcesResponseBodyDataEventSourceList,
    ) -> EventBridgeEventSourceRecord:
        event_types = []
        for event_type in source.event_types or []:
            event_types.append(
                {
                    "name": event_type.name or "",
                    "short_name": event_type.short_name or "",
                    "group_name": event_type.group_name or "",
                    "event_source_name": event_type.event_source_name or "",
                }
            )

        return EventBridgeEventSourceRecord(
            event_source_name=source.name or "",
            event_bus_name=source.event_bus_name or "default",
            description=source.description or "",
            event_source_type=source.type or "",
            source_type=source.name or "",
            full_name=source.full_name or "",
            arn=source.arn or "",
            status=source.status or "",
            event_types=event_types,
            config={"event_types": event_types},
            create_time=self._from_timestamp_ms(source.ctime),
        )

    def _parse_event_bus(
        self,
        bus: eventbridge_models.ListEventBusesResponseBodyDataEventBuses,
    ) -> EventBridgeEventBusRecord:
        bus_name = bus.event_bus_name or ""
        is_default_bus = bus_name.lower() == "default"

        return EventBridgeEventBusRecord(
            event_bus_name=bus_name,
            description=bus.description or "",
            event_bus_type="CloudService" if is_default_bus else "Custom",
            bus_type="Default" if is_default_bus else "Custom",
            rule_count=0,
            create_time=self._from_timestamp_ms(bus.create_timestamp),
        )

    def _parse_rule(
        self,
        rule: eventbridge_models.ListRulesResponseBodyDataRules,
    ) -> EbEventRuleRecord:
        filter_pattern = self._parse_filter_pattern(rule.filter_pattern)

        return EbEventRuleRecord(
            rule_name=rule.rule_name or "",
            event_bus_name=rule.event_bus_name or "",
            description=rule.description or "",
            filter_pattern=filter_pattern,
            status=rule.status or "ENABLE",
            targets=[target.to_map() for target in (rule.targets or [])],
            create_time=self._from_timestamp_ms(rule.created_timestamp),
        )

    def _parse_rule_target(
        self,
        target: eventbridge_models.ListRulesResponseBodyDataRulesTargets,
        rule_name: str,
        event_bus_name: str,
    ) -> EbEventTargetRecord:
        target_map = target.to_map()
        retry_strategy: dict = {}
        if "PushRetryStrategy" in target_map:
            retry_strategy = {"push_retry_strategy": target_map["PushRetryStrategy"]}

        dead_letter_queue = target_map.get("DeadLetterQueue", {})
        transform_config: dict = {}
        if "ParamList" in target_map:
            transform_config = {"param_list": target_map["ParamList"]}

        return EbEventTargetRecord(
            target_id=target.id or "",
            rule_name=rule_name,
            event_bus_name=event_bus_name,
            target_type=target.type or "",
            target_endpoint=target.endpoint or "",
            retry_strategy=retry_strategy,
            dead_letter_queue=dead_letter_queue,
            transform_config=transform_config,
        )

    def _parse_user_defined_event_source(
        self,
        source: eventbridge_models.ListUserDefinedEventSourcesResponseBodyDataEventSourceList,
    ) -> EventBridgeEventSourceRecord:
        return EventBridgeEventSourceRecord(
            event_source_name=source.name or "",
            event_bus_name=source.event_bus_name or "default",
            description="",
            event_source_type=source.type or "UserDefined",
            source_type=source.external_source_type or source.name or "",
            full_name="",
            arn=source.arn or "",
            status=source.status or "",
            event_types=[],
            config=source.to_map(),
            create_time=self._from_timestamp_ms(source.ctime),
        )

    @staticmethod
    def _parse_filter_pattern(filter_pattern: Optional[str]) -> dict:
        if not filter_pattern:
            return {}
        try:
            parsed = json.loads(filter_pattern)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": filter_pattern}
        except (TypeError, ValueError):
            return {"raw": filter_pattern}

    @staticmethod
    def _from_timestamp_ms(timestamp_ms: Optional[float]) -> Optional[datetime]:
        if timestamp_ms in (None, 0, ""):
            return None
        return datetime.fromtimestamp(float(timestamp_ms) / 1000)
