import json
import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_sls20201230.client import Client as SlsClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_sls20201230 import models as sls_models

from sesora.core.collector import CollectorBase
from sesora import DataSource
from sesora.schema.sls import (
    SlsLogstoreRecord,
    SlsLogSampleRecord,
    SlsLogStructureAnalysisRecord,
    SlsIndexConfigRecord,
    SlsQueryCapabilityRecord,
    SlsArchiveConfigRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class SLSCollectorConfig:
    """SLS Collector 配置"""
    aliyun_credentials: Optional[CredentialClient] = None
    sls_project: str = ""
    sls_region: str = ""


class SLSCollector(CollectorBase):
    # 常见的标准日志字段
    STANDARD_FIELDS = {
        "timestamp": [
            "time",
            "timestamp",
            "@timestamp",
            "datetime",
            "date",
            "log_time",
            "created_at",
        ],
        "level": ["level", "log_level", "severity", "loglevel", "lvl"],
        "message": ["message", "msg", "content", "log", "text", "body"],
        "trace_id": [
            "trace_id",
            "traceid",
            "traceId",
            "x-trace-id",
            "request_id",
            "requestId",
        ],
        "service_name": [
            "service",
            "service_name",
            "serviceName",
            "app",
            "application",
            "app_name",
        ],
    }

    def __init__(self, config: SLSCollectorConfig):
        self.config = config
        self.project_name = config.sls_project
        self.sls_region = config.sls_region
        self.client = self._create_client()

    def _create_client(self) -> SlsClient:
        """使用 AK/SK 初始化 SLS 客户端"""
        creds = self.config.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"{self.sls_region}.log.aliyuncs.com",
            protocol="https",
        )
        return SlsClient(config)

    def _list_logstore_names(self) -> List[str]:
        response = self.client.list_log_stores(
            self.project_name, sls_models.ListLogStoresRequest()
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"ListLogStores API 调用失败: {response.status_code}")
        return body.logstores

    def _get_logstore_detail(self, logstore_name: str) -> SlsLogstoreRecord:
        response = self.client.get_log_store(self.project_name, logstore_name)
        body = response.body
        if response.status_code != 200:
            raise Exception(f"GetLogStore API 调用失败: {response.status_code}")
        create_time = datetime.datetime.fromtimestamp(body.create_time)
        last_modify_time = datetime.datetime.fromtimestamp(body.last_modify_time)
        return SlsLogstoreRecord(
            project_name=self.project_name,
            logstore_name=logstore_name,
            ttl=body.ttl,
            shard_count=body.shard_count,
            auto_split=body.auto_split,
            max_split_shard=body.max_split_shard,
            hot_ttl=body.hot_ttl,
            create_time=create_time,
            last_modify_time=last_modify_time,
        )

    def _get_index_config(self, logstore_name: str) -> SlsIndexConfigRecord:
        response = self.client.get_index(self.project_name, logstore_name)
        body = response.body
        if response.status_code != 200:
            raise Exception(f"GetIndex API 调用失败: {response.status_code}")

        # 解析字段索引
        field_names = []
        keys = []
        for key_name, key_config in body.keys.items():
            field_names.append(key_name)
            keys.append(key_name)

        has_fulltext = body.line is not None

        is_enabled = len(field_names) > 0 or has_fulltext

        return SlsIndexConfigRecord(
            project_name=self.project_name,
            logstore_name=logstore_name,
            index_enabled=is_enabled,  # 动态赋值
            fulltext_enabled=has_fulltext,
            field_index_count=len(field_names),
            keys=keys,
            field_names=field_names,
        )

    def _get_log_samples(
        self, logstore_name: str, sample_count: int = 100
    ) -> List[SlsLogSampleRecord]:
        # 查询最近 1 小时的日志
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(hours=1)
        end_time = int(end_time.timestamp())
        start_time = int(start_time.timestamp())

        # 使用纯搜索语句，不使用 SQL 分析语法（部分 Logstore 不支持）
        response = self.client.get_logs(
            self.project_name,
            logstore_name,
            sls_models.GetLogsRequest(
                from_=start_time,
                to=end_time,
                query="*",  # 纯搜索语句
                line=sample_count,  # 通过 line 参数限制返回数量
            ),
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"GetLogs API 调用失败: {response.status_code}")

        records = []
        for log in body:
            timestamp_str = log.get("__time__")
            timestamp = datetime.datetime.fromtimestamp(int(timestamp_str))

            # 移除 SLS 内置字段，保留业务字段作为 contents
            content_keys = [k for k in log.keys() if not k.startswith("__")]
            contents = json.dumps({k: log[k] for k in content_keys})

            records.append(
                SlsLogSampleRecord(
                    project_name=self.project_name,
                    logstore_name=logstore_name,
                    timestamp=timestamp,
                    source=log.get("__source__", ""),
                    contents=contents,
                    topic=log.get("__topic__", ""),
                )
            )
        return records

    def _analyze_log_structure(
        self, logstore_name: str, samples: List[SlsLogSampleRecord]
    ) -> SlsLogStructureAnalysisRecord:
        """
        分析日志结构
        策略：
        1. 尝试解析 JSON，仅当解析结果为 dict 时视为有效结构化日志。
        2. 使用不区分大小写的匹配检测标准字段。
        3. 基于阈值判定字段是否存在（可配置）。
        """
        if not samples:
            return SlsLogStructureAnalysisRecord(
                project_name=self.project_name,
                logstore_name=logstore_name,
                sample_count=0,
                json_parse_rate=0.0,
                is_json_format=False,
                has_timestamp_field=False,
                has_level_field=False,
                has_message_field=False,
                has_trace_id_field=False,
                has_service_name_field=False,
                trace_id_injection_rate=0.0,
                standard_fields=[],
            )

        total = len(samples)
        json_success = 0
        has_timestamp = 0
        has_level = 0
        has_message = 0
        has_trace_id = 0
        has_service_name = 0
        detected_standard_fields: set[str] = set()

        THRESHOLD_JSON = 0.8
        THRESHOLD_COMMON = 0.5
        THRESHOLD_TRACE_SVC = 0.3

        for sample in samples:
            if not sample.contents:
                continue

            try:
                content = json.loads(sample.contents)

                if not isinstance(content, dict):
                    continue

                json_success += 1
                content_keys_lower = {k.lower(): k for k in content.keys()}

                for field_type, field_names in self.STANDARD_FIELDS.items():
                    matched_key = None
                    for fn in field_names:
                        if fn.lower() in content_keys_lower:
                            matched_key = content_keys_lower[fn.lower()]
                            break

                    if matched_key:
                        detected_standard_fields.add(matched_key)

                        if field_type == "timestamp":
                            has_timestamp += 1
                        elif field_type == "level":
                            has_level += 1
                        elif field_type == "message":
                            has_message += 1
                        elif field_type == "trace_id":
                            has_trace_id += 1
                        elif field_type == "service_name":
                            has_service_name += 1

            except json.JSONDecodeError:
                continue
            except Exception as e:
                continue

        def calc_ratio(count: int) -> float:
            return count / total if total > 0 else 0.0

        return SlsLogStructureAnalysisRecord(
            project_name=self.project_name,
            logstore_name=logstore_name,
            sample_count=total,
            json_parse_rate=calc_ratio(json_success),
            is_json_format=calc_ratio(json_success) > THRESHOLD_JSON,
            has_timestamp_field=calc_ratio(has_timestamp) > THRESHOLD_COMMON,
            has_level_field=calc_ratio(has_level) > THRESHOLD_COMMON,
            has_message_field=calc_ratio(has_message) > THRESHOLD_COMMON,
            has_trace_id_field=calc_ratio(has_trace_id) > THRESHOLD_TRACE_SVC,
            has_service_name_field=calc_ratio(has_service_name) > THRESHOLD_TRACE_SVC,
            trace_id_injection_rate=calc_ratio(has_trace_id),
            standard_fields=sorted(list(detected_standard_fields)),
        )

    def _build_query_capability(
        self, logstore_name: str, index_config: SlsIndexConfigRecord
    ) -> SlsQueryCapabilityRecord:
        if index_config.index_enabled:
            return SlsQueryCapabilityRecord(
                project_name=self.project_name,
                logstore_name=logstore_name,
                supports_realtime_query=True,
                supports_aggregation=True,
                supports_sql=True,
                index_enabled=True,
                full_text_index=index_config.fulltext_enabled,
                field_index_count=index_config.field_index_count,
            )
        else:
            return SlsQueryCapabilityRecord(
                project_name=self.project_name,
                logstore_name=logstore_name,
                supports_realtime_query=False,
                supports_aggregation=False,
                supports_sql=False,
                index_enabled=False,
                full_text_index=False,
                field_index_count=0,
            )

    def _build_archive_config(
        self, logstore_name: str, logstore_record: SlsLogstoreRecord
    ) -> SlsArchiveConfigRecord:
        ttl = logstore_record.ttl or 0
        hot_ttl = logstore_record.hot_ttl or 0
        warm_ttl = max(0, ttl - hot_ttl) if ttl > hot_ttl else 0
        return SlsArchiveConfigRecord(
            project_name=self.project_name,
            logstore_name=logstore_name,
            hot_ttl_days=hot_ttl,
            warm_ttl_days=warm_ttl,
            cold_archive_enabled=hot_ttl < ttl,
            max_retention_days=ttl,
        )

    def name(self) -> str:
        return "sls_collector"

    def _collect(self) -> List:
        all_records: List = []

        logger.info(f"正在采集 SLS 信息 (Project: {self.project_name})...")

        # 1. 获取 Logstore 列表
        logstore_names = self._list_logstore_names()
        logger.info(f"发现 {len(logstore_names)} 个 Logstore")

        # 2. 遍历每个 Logstore 采集详细信息
        for logstore_name in logstore_names:
            logger.info(f"采集 Logstore: {logstore_name}")

            # 2.1 Logstore 详情
            logstore_record = self._get_logstore_detail(logstore_name)
            all_records.append(logstore_record)

            # 2.2 索引配置
            index_config = self._get_index_config(logstore_name)
            all_records.append(index_config)

            # 2.3 查询能力（基于索引配置生成）
            query_capability = self._build_query_capability(
                logstore_name, index_config
            )
            all_records.append(query_capability)

            # 2.4 归档配置（基于 Logstore 配置生成）
            archive_config = self._build_archive_config(
                logstore_name, logstore_record
            )
            all_records.append(archive_config)

            # 2.5 日志样本（仅当索引开启时才能查询）
            if index_config.index_enabled:
                samples = self._get_log_samples(logstore_name, sample_count=50)
                all_records.extend(samples)

                # 2.6 日志结构分析
                structure_analysis = self._analyze_log_structure(
                    logstore_name, samples
                )
                all_records.append(structure_analysis)

        logger.info(f"SLS 采集完成，共 {len(all_records)} 条记录")

        return all_records
