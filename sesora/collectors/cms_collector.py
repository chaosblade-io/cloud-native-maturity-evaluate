from datetime import datetime, timedelta
from typing import List

from alibabacloud_cms20190101 import models as cms_models
from alibabacloud_cms20190101.client import Client as CmsClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.cms import (
    CmsContactRecord,
    CmsAlarmChannelSummaryRecord,
    CmsAlarmRuleRecord,
    CmsContactGroupRecord,
    CmsAlarmHistoryRecord,
    CmsEventTriggerRecord,
)


class CMSCollector(CollectorBase):
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.client = self._create_client()

    def _create_client(self) -> CmsClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint="metrics.aliyuncs.com",
            protocol="https",
        )
        return CmsClient(config)

    def name(self) -> str:
        return "cms_collector"

    def _collect(self) -> List:
        history_hours: int = 24
        records: List = []

        # 采集联系人
        contacts = self._collect_contacts()
        records.extend(contacts)
        print(f"采集到 {len(contacts)} 个联系人")

        # 生成通道汇总记录
        channel_summary = self._generate_channel_summary(contacts)
        records.append(channel_summary)
        print(f"生成通道汇总记录: {channel_summary.channel_types}")

        # 采集告警规则
        alarm_rules = self._collect_alarm_rules()
        records.extend(alarm_rules)
        print(f"采集到 {len(alarm_rules)} 条告警规则")

        # 采集联系组
        contact_groups = self._collect_contact_groups()
        records.extend(contact_groups)
        print(f"采集到 {len(contact_groups)} 个联系组")

        # 采集告警历史
        alarm_history = self._collect_alarm_history(hours=history_hours)
        records.extend(alarm_history)
        print(
            f"采集到 {len(alarm_history)} 条告警历史（最近 {history_hours} 小时）"
        )

        # 采集事件触发器
        event_triggers = self._collect_event_triggers()
        records.extend(event_triggers)
        print(f"采集到 {len(event_triggers)} 个事件触发器")

        return records

    def _collect_contacts(self) -> List[CmsContactRecord]:
        records: List[CmsContactRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.describe_contact_list(
                cms_models.DescribeContactListRequest(
                    page_number=page_no, page_size=page_size
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取联系人失败：{body.message}")

            for contact in body.contacts.contact:
                record = self._parse_contact(contact)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_contact(
        self, contact: cms_models.DescribeContactListResponseBodyContactsContact
    ) -> CmsContactRecord:
        channels = []
        channels_data = contact.channels
        if channels_data.sms:
            channels.append("SMS")
        if channels_data.mail:
            channels.append("Email")
        if channels_data.ding_web_hook:
            channels.append("DingTalk")
        return CmsContactRecord(
            contact_name=contact.name,
            channels=channels,
            phone=channels_data.sms,
            email=channels_data.mail,
            dingtalk_webhook=channels_data.ding_web_hook,
            desc=contact.desc,
        )

    def _generate_channel_summary(
        self, contacts: List[CmsContactRecord]
    ) -> CmsAlarmChannelSummaryRecord:
        channel_types = set()
        has_sms = False
        has_email = False
        has_dingtalk = False
        has_phone = False
        has_webhook = False

        for contact in contacts:
            for channel in contact.channels:
                channel_types.add(channel)
                if channel == "SMS":
                    has_sms = True
                    has_phone = True
                elif channel == "Email":
                    has_email = True
                elif channel == "DingTalk":
                    has_dingtalk = True
                    has_webhook = True

        return CmsAlarmChannelSummaryRecord(
            total_contacts=len(contacts),
            channel_types=list(channel_types),
            channel_count=len(channel_types),
            has_sms=has_sms,
            has_email=has_email,
            has_dingtalk=has_dingtalk,
            has_phone=has_phone,
            has_webhook=has_webhook,
        )

    def _collect_alarm_rules(self) -> List[CmsAlarmRuleRecord]:
        records: List[CmsAlarmRuleRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.describe_metric_rule_list(
                cms_models.DescribeMetricRuleListRequest(
                    page=page_no, page_size=page_size
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取告警规则失败：{body.message if body else response.status_code}")

            for alarm in body.alarms.alarm:
                record = self._parse_alarm_rule(alarm)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_alarm_rule(
        self, alarm: cms_models.DescribeMetricRuleListResponseBodyAlarmsAlarm
    ) -> CmsAlarmRuleRecord:
        # 解析告警级别和表达式
        level = "Info"
        expression = ""
        escalations = alarm.escalations

        # 按优先级判断告警级别
        if escalations.critical.comparison_operator:
            level = "Critical"
            expression = self._build_expression(escalations.critical.to_map())
        elif escalations.warn.comparison_operator:
            level = "Warning"
            expression = self._build_expression(escalations.warn.to_map())
        elif escalations.info.comparison_operator:
            level = "Info"
            expression = self._build_expression(escalations.info.to_map())

        # 解析动作类型
        action_types = []
        contact_groups_str = alarm.contact_groups
        contact_groups = (
            [cg.strip() for cg in contact_groups_str.split(",")]
            if contact_groups_str
            else []
        )
        if contact_groups:
            action_types.append("contact_group")

        webhook_url = alarm.webhook
        if webhook_url:
            action_types.append("webhook")

        # 判断是否配置通知
        has_notification = bool(contact_groups or webhook_url)

        return CmsAlarmRuleRecord(
            rule_id=alarm.rule_id,
            rule_name=alarm.rule_name,
            namespace=alarm.namespace,
            metric_name=alarm.metric_name,
            expression=expression,
            level=level,
            enable_state=alarm.enable_state,
            action_types=action_types,
            contact_groups=contact_groups,
            webhook_url=webhook_url,
            silence_time=alarm.silence_time,
            effective_time=alarm.effective_interval,
            has_notification=has_notification,
        )

    def _build_expression(self, escalation: dict) -> str:
        """
        构建告警表达式
        """
        statistics = escalation.get("Statistics", "Average")
        operator = escalation.get("ComparisonOperator", "")
        threshold = escalation.get("Threshold", "")

        # 简化运算符显示
        operator_map = {
            "GreaterThanOrEqualToThreshold": ">=",
            "GreaterThanThreshold": ">",
            "LessThanOrEqualToThreshold": "<=",
            "LessThanThreshold": "<",
            "NotEqualToThreshold": "!=",
            "GreaterThanYesterday": ">昨天",
            "LessThanYesterday": "<昨天",
            "GreaterThanLastWeek": ">上周",
            "LessThanLastWeek": "<上周",
            "GreaterThanLastPeriod": ">上周期",
            "LessThanLastPeriod": "<上周期",
        }
        simple_operator = operator_map.get(operator, operator)

        return f"{statistics}{simple_operator}{threshold}"

    def _collect_contact_groups(self) -> List[CmsContactGroupRecord]:
        records: List[CmsContactGroupRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.describe_contact_group_list(
                cms_models.DescribeContactGroupListRequest(
                    page_number=page_no, page_size=page_size
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取联系组失败：{body.message if body else response.status_code}")

            contact_groups = body.contact_group_list.contact_group
            for group in contact_groups:
                record = self._parse_contact_group(group)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_contact_group(
        self,
        group: cms_models.DescribeContactGroupListResponseBodyContactGroupListContactGroup,
    ) -> CmsContactGroupRecord:
        # 解析联系人列表
        contacts = []
        contacts_data = group.contacts.contact
        for contact in contacts_data:
            contacts.append(contact)

        return CmsContactGroupRecord(
            group_name=group.name,
            contacts=contacts,
            enable_subscribed=group.enable_subscribed,
            describe=group.describe,
        )

    def _collect_alarm_history(self, hours: int = 24) -> List[CmsAlarmHistoryRecord]:
        records: List[CmsAlarmHistoryRecord] = []

        # 计算时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        end_time = int(end_time.timestamp() * 1000)  # 转换为毫秒
        start_time = int(start_time.timestamp() * 1000)  # 转换为毫秒

        page_no = 1
        page_size = 100

        while True:
            response = self.client.describe_alert_log_list(
                cms_models.DescribeAlertLogListRequest(
                    start_time=start_time,
                    end_time=end_time,
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取告警历史失败：{body.message if body else response.status_code}")
            alarm_history_list = body.alert_log_list
            for alarm in alarm_history_list:
                record = self._parse_alarm_history(alarm)
                records.append(record)

            # TODO: make this limit configurable
            if len(alarm_history_list) < page_size or len(records) >= 2000:
                break
            page_no += 1

        return records

    def _parse_alarm_history(
        self, alarm: cms_models.DescribeAlertLogListResponseBodyAlertLogList
    ) -> CmsAlarmHistoryRecord:
        # 解析时间戳
        timestamp = datetime.fromtimestamp(int(alarm.alert_time) / 1000)

        # 解析维度信息
        dimensions = {}
        dimensions_data = alarm.dimensions
        for dim in dimensions_data:
            dimensions[dim.key] = dim.value

        return CmsAlarmHistoryRecord(
            alarm_id=alarm.log_id,
            alarm_name=alarm.event_name,
            rule_id=alarm.rule_id,
            rule_name=alarm.rule_name,
            level=alarm.level,
            message=alarm.message,
            namespace=alarm.namespace,
            metric_name=alarm.metric_name,
            dimensions=dimensions,
            timestamp=timestamp,
        )

    def _collect_event_triggers(self) -> List[CmsEventTriggerRecord]:
        records: List[CmsEventTriggerRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_event_rule_list(
                cms_models.DescribeEventRuleListRequest(
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取事件触发器失败：{body.message if body else response.status_code}")

            event_rules = body.event_rules.event_rule
            for rule in event_rules:
                record = self._parse_event_trigger(rule)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_event_trigger(
        self, rule: cms_models.DescribeEventRuleListResponseBodyEventRulesEventRule
    ) -> CmsEventTriggerRecord:
        return CmsEventTriggerRecord(
            trigger_name=rule.name,
            enabled=rule.state == "ENABLED",
        )
