import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from alibabacloud_arms20190808 import models as arms_models
from alibabacloud_arms20190808.client import Client as ARMSClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.apm import (
    ApmServiceRecord,
    ApmTraceRecord,
    ApmServiceDependencyRecord,
    ApmTopologyMetricsRecord,
    ApmSamplingConfigRecord,
    ApmExternalDatabaseRecord,
    ApmServiceDbMappingRecord,
    ApmExternalMessageRecord,
)

logger = logging.getLogger(__name__)


def map_rpc_type(rpc_type) -> str:
    mapping = {
        -3: "app",
        -2: "front",
        -1: "unknown",
        0: "http",
        1: "hsf_client",
        2: "hsf",
        3: "notify_client",
        4: "tddl",
        5: "tair",
        7: "dubbo_client",
        8: "dubbo",
        9: "grpc",
        10: "grpc_client",
        11: "dsf_client",
        12: "dsf",
        13: "mq_client",
        16: "thrift",
        17: "thrift_client",
        18: "sofa",
        19: "sofa_client",
        23: "kafka_client",
        25: "http_client",
        40: "local",
        41: "async",
        52: "DB2",
        53: "Informix",
        54: "SequoiaDB",
        55: "Gbase",
        56: "GaussDB",
        57: "KingBase",
        58: "influxdb",
        59: "clickhouse",
        60: "mysql",
        61: "mysql",
        62: "oracle",
        63: "postgresql",
        64: "mongodb",
        65: "ppas",
        66: "sqlserver",
        67: "mariadb",
        68: "dmdb",
        69: "oceanbase",
        70: "redis",
        71: "memcached",
        72: "elasticsearch",
        73: "kudu",
        98: "user_method",
        100: "root",
        101: "client",
        102: "server",
        103: "producer",
        104: "consumer",
        105: "db",
        106: "xtrace_other",
        252: "mq",
        254: "notify",
        256: "kafka",
        1301: "schedulerx",
        1302: "XXL_Job",
        1303: "Spring_Scheduled",
        1304: "Quartz",
        1305: "ElasticJob",
        1308: "Jdk_Timer",
    }
    try:
        rpc_type_int = int(rpc_type)
        return mapping.get(rpc_type_int, str(rpc_type))
    except (ValueError, TypeError):
        return str(rpc_type) if rpc_type else "UNKNOWN"


class ARMSCollector(CollectorBase):
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.client = self._create_client()
        self._logging_configs = {}

    def _create_client(self) -> ARMSClient:
        creds = self.context.aliyun_credentials
        region = self.context.region
        config = open_api_models.Config(
            credential=creds,
            protocol="https",
            endpoint=f"arms.{region}.aliyuncs.com",
        )
        return ARMSClient(config)

    def name(self) -> str:
        return "arms_collector"

    def _collect(self) -> List:
        hours: int = 24
        records: List = []

        # 1. 采集应用列表
        services = self._collect_trace_apps()
        records.extend(services)
        logger.info(f"采集到 {len(services)} 个 ARMS 应用")
        services = services[:15]  # TODO: remove this limit
        logger.info("采集应用列表(first 15)")

        pid_to_service = {svc.pid: svc.service_name for svc in services}

        # 2. 基于应用的 pid 采集服务依赖和拓扑指标
        for svc in services:
            logger.info(f"采集应用 {svc.service_name} 的服务依赖和拓扑指标")
            # 采集服务依赖及其指标（appstat.incall）
            deps = self._collect_service_incall(svc.pid, pid_to_service, hours)
            records.extend(deps)

        dep_count = sum(
            1 for r in records if isinstance(r, ApmServiceDependencyRecord)
        )
        topo_count = sum(
            1 for r in records if isinstance(r, ApmTopologyMetricsRecord)
        )
        logger.info(f"采集到 {dep_count} 条服务依赖关系")
        logger.info(f"采集到 {topo_count} 条拓扑指标")

        # 3. 采集外部数据库调用
        logger.info("采集外部数据库调用...")
        all_db_records: List[ApmExternalDatabaseRecord] = []
        for svc in services:
            db_recs = self._collect_external_databases(
                svc.pid, svc.service_name, hours
            )
            all_db_records.extend(db_recs)
        records.extend(all_db_records)
        logger.info(f"采集到 {len(all_db_records)} 条外部数据库调用记录")

        # 4. 推导服务-数据库映射
        logger.info("推导服务-数据库映射...")
        db_mappings = self._derive_service_db_mappings(all_db_records)
        records.extend(db_mappings)
        logger.info(f"推导出 {len(db_mappings)} 条服务-数据库映射")

        # 5. 采集外部消息队列调用
        logger.info("采集外部消息队列调用...")
        all_msg_records: List[ApmExternalMessageRecord] = []
        for svc in services:
            msg_recs = self._collect_external_messages(
                svc.pid, svc.service_name, hours
            )
            all_msg_records.extend(msg_recs)
        records.extend(all_msg_records)
        logger.info(f"采集到 {len(all_msg_records)} 条外部消息队列调用记录")

        # 6. 采集链路数据 (SearchTracesByPage + GetTrace)
        logger.info("采集链路数据...")
        trace_records = self._collect_traces(services, hours)
        records.extend(trace_records)
        error_trace_count = sum(1 for t in trace_records if t.has_error)
        slow_trace_count = sum(1 for t in trace_records if t.duration_ms > 1000)
        logger.info(
            f"采集到 {len(trace_records)} 条链路记录"
            f" (错误: {error_trace_count}, 慢: {slow_trace_count})"
        )

        # 7. 采集每个应用的配置（采样配置 + 集成配置）
        logger.info("采集应用配置...")
        config_records = self._collect_app_configs(services)
        records.extend(config_records)
        apm_sampling_count = sum(
            1 for r in config_records if isinstance(r, ApmSamplingConfigRecord)
        )
        logger.info(f"采集到 {apm_sampling_count} 条采样配置(SamplingConfig)")

        return records

    def _collect_trace_apps(self) -> List[ApmServiceRecord]:
        records: List[ApmServiceRecord] = []
        # TODO: 当前是列举出来了所有的当前region下的service，后续应该需要增加条件，限制只去取对应评估的service列表
        # TODO: filter by cluster_id

        response = self.client.list_trace_apps(
            arms_models.ListTraceAppsRequest(region_id=self.context.region)
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            raise Exception(f"ListTraceApps API 调用失败: {body.message}")

        for app in body.trace_apps:
            app_type = app.type
            if app_type.upper() == "RETCODE":
                continue
            record = self._parse_trace_app(app)
            records.append(record)

        return records

    def _parse_trace_app(
        self, app: arms_models.ListTraceAppsResponseBodyTraceApps
    ) -> ApmServiceRecord:
        app_name = app.app_name

        # 解析创建时间（毫秒时间戳）
        create_time = datetime.fromtimestamp(app.create_time / 1000)

        # 解析更新时间（毫秒时间戳）
        update_time = datetime.fromtimestamp(app.update_time / 1000)

        # 解析标签为 dict
        labels_dict = {}
        for tag in app.tags:
            labels_dict[tag.key] = tag.value

        # 额外信息也放到 labels 中
        cluster_id = app.cluster_id
        namespace = app.namespace
        source = app.source
        workload_kind = app.workload_kind
        workload_name = app.workload_name

        if cluster_id:
            labels_dict["cluster_id"] = cluster_id
        if namespace:
            labels_dict["namespace"] = namespace
        if source:
            labels_dict["source"] = source
        if workload_kind:
            labels_dict["workload_kind"] = workload_kind
        if workload_name:
            labels_dict["workload_name"] = workload_name

        # 推断 service_type
        # Todo: 这里认为不合理
        service_type = "web"
        app_type = (getattr(app, "type", "") or "").upper()
        if app_type == "TRACE":
            service_type = "web"

        return ApmServiceRecord(
            service_name=app_name,
            app_id=str(app.app_id),
            pid=app.pid,
            region=app.region_id,
            language=app.language,
            service_type=service_type,
            trace_enabled=True,  # 存在于列表中即已开启
            labels=labels_dict,
            create_time=create_time,
            update_time=update_time,
        )

    def _query_metric_by_page(
        self,
        metric: str,
        pid: str,
        hours: int = 24,
        measures: Optional[List[str]] = None,
        dimensions: Optional[List[str]] = None,
        interval_in_sec: int = 60000,
    ) -> List[Dict[str, Any]]:
        """通用 QueryMetricByPage 分页查询。"""
        all_items: List[Dict[str, Any]] = []
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        region = self.context.region

        current_page = 1
        max_pages = 2
        while current_page <= max_pages:
            try:
                request = arms_models.QueryMetricByPageRequest(
                    metric=metric,
                    start_time=start_time,
                    end_time=end_time,
                    interval_in_sec=interval_in_sec,
                    current_page=current_page,
                    page_size=100,
                    filters=[
                        arms_models.QueryMetricByPageRequestFilters(key="pid", value=pid),
                        arms_models.QueryMetricByPageRequestFilters(
                            key="regionId", value=region
                        ),
                    ],
                    measures=measures,
                    dimensions=dimensions,
                )

                response = self.client.query_metric_by_page(request)
                if response.status_code != 200 or not response.body.success:
                    msg = response.body.message if response.body else f"{response.status_code}"
                    raise Exception(f"QueryMetricByPage API 调用失败: {msg}")

                data = response.body.data
                if not data or not data.items:
                    break

                all_items.extend(data.items)
                if data.completed:
                    break
                current_page += 1
            except Exception as e:
                logger.warning(f"QueryMetricByPage({metric}) page={current_page} 异常: {e}")
                break

        return all_items

    def _collect_service_incall(
        self, pid: str, pid_to_service: Dict[str, str], hours: int = 24
    ) -> List:
        records = []
        target_service = pid_to_service.get(pid, "unknown")
        items = self._query_metric_by_page(
            metric="appstat.incall",
            pid=pid,
            hours=hours,
            measures=["count", "error", "rt"],
            dimensions=["rpc", "rpcType", "ppid"],
        )

        dependencies = set()
        for item in items:
            date = int(item.get("date", 0) or 0)
            rt = float(item.get("rt", 0) or 0)
            rpc = item.get("rpc", "")
            count = int(item.get("count", 0) or 0)
            error = int(item.get("error", 0) or 0)
            ppid = item.get("ppid", "")
            rpc_type = item.get("rpcType", "")
            source_service = pid_to_service.get(ppid, "unknown")

            records.append(
                ApmTopologyMetricsRecord(
                    source_service=source_service,
                    target_service=target_service,
                    call_type=map_rpc_type(rpc_type),
                    call=rpc,
                    call_count=count,
                    error_count=error,
                    rt=rt,
                    timestamp=datetime.fromtimestamp(date / 1000) if date else None,
                )
            )
            dependencies.add((source_service, target_service, map_rpc_type(rpc_type), rpc))

        for dep_data in dependencies:
            records.append(ApmServiceDependencyRecord(*dep_data))

        return records

    def _collect_traces(
        self, services: List[ApmServiceRecord], hours: int = 24
    ) -> List[ApmTraceRecord]:
        all_traces: List[ApmTraceRecord] = []
        sample_traces: List[ApmTraceRecord] = []

        for svc in services:
            svc_traces = self._search_traces_for_service(pid=svc.pid, hours=hours)
            all_traces.extend(svc_traces)

            # 每个服务取 1 个 trace_id 作为 GetTrace 采样候选
            # TODO: random select?
            if svc_traces and len(sample_traces) < 10:
                sample_traces.append(svc_traces[0])

        # GetTrace 采样丰富 span_count
        if sample_traces:
            self._enrich_trace_details(sample_traces, hours)

        return all_traces

    def _search_traces_for_service(
        self, pid: str, hours: int = 24
    ) -> List[ApmTraceRecord]:
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        end_time = int(end_time.timestamp() * 1000)
        start_time = int(start_time.timestamp() * 1000)
        region = self.context.region

        records: List[ApmTraceRecord] = []
        error_trace_ids: set = set()

        # --- 查询错误链路，收集 trace_id ---
        response = self.client.search_traces_by_page(
            arms_models.SearchTracesByPageRequest(
                start_time=start_time,
                end_time=end_time,
                region_id=region,
                pid=pid,
                is_error=True,
                page_number=1,
                page_size=100,
                reverse=True,
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"SearchTracesByPage API 调用失败: {response.status_code}")

        for info in body.page_bean.trace_infos:
            error_trace_ids.add(info.trace_id)
            records.append(
                ApmTraceRecord(
                    trace_id=info.trace_id,
                    service_name=info.service_name,
                    operation_name=info.operation_name,
                    start_time=datetime.fromtimestamp(info.timestamp / 1000),
                    duration_ms=info.duration,
                    has_error=True,
                    span_count=0,  # 后续通过 GetTrace 丰富
                )
            )

        # --- 查询近期链路（正常 + 错误混合） ---
        response = self.client.search_traces_by_page(
            request=arms_models.SearchTracesByPageRequest(
                start_time=start_time,
                end_time=end_time,
                region_id=region,
                pid=pid,
                page_number=1,
                page_size=100,
                reverse=True,
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"SearchTracesByPage API 调用失败: {response.status_code}")

        for info in body.page_bean.trace_infos:
            tid = info.trace_id
            if tid in error_trace_ids:
                continue  # 已在错误查询中处理过了

            records.append(
                ApmTraceRecord(
                    trace_id=tid,
                    service_name=info.service_name,
                    operation_name=info.operation_name,
                    start_time=datetime.fromtimestamp(info.timestamp / 1000),
                    duration_ms=info.duration,
                    has_error=False,
                    span_count=0,  # 后续通过 GetTrace 丰富
                )
            )

        return records

    def _enrich_trace_details(
        self,
        sample_traces: List[ApmTraceRecord],
        hours: int = 24,
    ) -> None:
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        region = self.context.region

        for rec in sample_traces:
            response = self.client.get_trace(
                arms_models.GetTraceRequest(
                    trace_id=rec.trace_id,
                    region_id=region,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"GetTrace API 调用失败: {response.status_code}")

            spans = body.spans
            rec.span_count = len(spans)

            # 从根 span 提取 status_code 和 tags
            if spans:
                root = spans[0]
                result_code = root.result_code
                if int(result_code) >= 400:
                    rec.has_error = True
                # 提取 tags
                tag_list = root.tag_entry_list
                for tag in tag_list:
                    rec.tags[tag.key] = tag.value

    def _collect_external_messages(
        self, pid: str, service_name: str, hours: int = 24
    ) -> List[ApmExternalMessageRecord]:
        records: List[ApmExternalMessageRecord] = []

        send_items = self._query_metric_by_page(
            metric="appstat.mq.send",
            pid=pid,
            hours=hours,
            measures=["count", "error", "rt"],
            dimensions=["rpc", "rpcType"],
        )
        self._aggregate_mq_items(
            items=send_items,
            operation="send",
            service_name=service_name,
            records_out=records,
        )

        recv_items = self._query_metric_by_page(
            metric="appstat.mq.receive",
            pid=pid,
            hours=hours,
            measures=["count", "error", "rt"],
            dimensions=["rpc", "rpcType"],
        )
        self._aggregate_mq_items(
            items=recv_items,
            operation="consume",
            service_name=service_name,
            records_out=records,
        )

        return records

    def _aggregate_mq_items(
        self,
        items: List[Dict[str, Any]],
        operation: str,
        service_name: str,
        records_out: List[ApmExternalMessageRecord],
    ) -> None:
        for item in items:
            date = item["date"]
            topic = item["rpc"]
            rpc_type = item["rpcType"]
            count = item["count"]
            error = item["error"]
            rt = item["rt"]
            mq_type = map_rpc_type(rpc_type)
            records_out.append(
                ApmExternalMessageRecord(
                    service_name=service_name,
                    mq_type=mq_type,
                    topic_or_queue=topic,
                    operation=operation,
                    call_count=int(count),
                    error_count=int(error),
                    rt=rt,
                    timestamp=datetime.fromtimestamp(date / 1000),
                )
            )

    def _collect_external_databases(
        self, pid: str, service_name: str, hours: int = 24
    ) -> List[ApmExternalDatabaseRecord]:
        records: List[ApmExternalDatabaseRecord] = []

        items = self._query_metric_by_page(
            metric="appstat.database",
            pid=pid,
            hours=hours,
            measures=["count", "error", "rt"],
            dimensions=["pid", "rpcType", "endpoint", "destId"],
        )

        for item in items:
            date = item["date"]
            dest_id = item["destId"]
            endpoint = item["endpoint"]
            rpc_type = item["rpcType"]
            count = item["count"]
            error = item["error"]
            rt = item["rt"]
            db_instance = dest_id or endpoint
            db_type = map_rpc_type(rpc_type)
            records.append(
                ApmExternalDatabaseRecord(
                    service_name=service_name,
                    db_type=db_type,
                    db_instance=db_instance,
                    call_count=int(count),
                    error_count=int(error),
                    rt=rt,
                    timestamp=datetime.fromtimestamp(date / 1000),
                )
            )

        return records

    @staticmethod
    def _derive_service_db_mappings(
        db_records: List[ApmExternalDatabaseRecord],
    ) -> List[ApmServiceDbMappingRecord]:
        # 第一遍：按 db_instance 收集所有访问它的服务
        db_to_services: Dict[str, Dict[str, Any]] = {}

        for rec in db_records:
            key = f"{rec.db_instance}|{rec.db_type}"
            if key not in db_to_services:
                db_to_services[key] = {
                    "db_instance": rec.db_instance,
                    "db_type": rec.db_type,
                    "services": set(),
                }
            db_to_services[key]["services"].add(rec.service_name)

        # 第二遍：生成映射记录
        records: List[ApmServiceDbMappingRecord] = []

        for rec in db_records:
            key = f"{rec.db_instance}|{rec.db_type}"
            info = db_to_services[key]
            all_services = info["services"]

            is_shared = len(all_services) > 1
            if is_shared:
                shared_with = sorted(s for s in all_services if s != rec.service_name)
            else:
                shared_with = []

            # 从 db_instance 提取数据库名（通常是 destId 的最后一段或整个值）
            database_name = rec.db_instance

            records.append(
                ApmServiceDbMappingRecord(
                    service_name=rec.service_name,
                    database_name=database_name,
                    db_type=rec.db_type,
                    db_instance=rec.db_instance,
                    access_type="read_write",  # appstat.database 无法区分读写
                    is_shared=is_shared,
                    shared_with=shared_with,
                )
            )

        return records

    def _collect_app_configs(self, services: List[ApmServiceRecord]) -> List:
        records: List = []

        for svc in services:
            logger.debug(f"采集应用 {svc.service_name} 的配置")
            response = self.client.get_trace_app_config(
                arms_models.GetTraceAppConfigRequest(pid=svc.pid)
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(
                    f"获取应用 {svc.service_name} 配置失败: {response.status_code}"
                )

            try:
                # 解析 JSON
                config = json.loads(body.data)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"解析 JSON 失败 (pid={svc.pid})")
                continue

            # 生成 ApmSamplingConfigRecord
            sampling_rec = self._parse_apm_sampling_config(svc.pid, config)
            if sampling_rec:
                records.append(sampling_rec)

            # 缓存日志配置信息（供 integration 使用）
            self._cache_logging_config(svc.pid, config)

        return records

    def _parse_apm_sampling_config(
        self, pid: str, config: dict
    ) -> Optional[ApmSamplingConfigRecord]:
        profiler = config.get("profiler", {})
        sampling = profiler.get("sampling", {})

        use_v2 = sampling.get("useSamplingStrategyV2", False)
        strategy = "tail-based" if use_v2 else "probabilistic"

        rate_pct = sampling.get("rate", 10)
        sample_rate = round(float(rate_pct) / 100.0, 4)

        # 慢请求阈值: ARMS 有内置的慢调用检测，配置可能在 threshold.rt 中
        threshold = profiler.get("threshold", {})
        slow_threshold_ms = int(threshold.get("rt", 1000))

        # 慢请求采样率: 自适应模式下慢请求会被全量采集
        slow_sample_rate = 1.0 if use_v2 else sample_rate

        v2config = sampling.get("v2config", {})
        custom_rules = self._parse_full_sample_rules(v2config)

        return ApmSamplingConfigRecord(
            app_id=pid,
            strategy=strategy,
            sample_rate=sample_rate,
            error_sample_rate=1.0,
            slow_threshold_ms=slow_threshold_ms,
            slow_sample_rate=slow_sample_rate,
            custom_rules=custom_rules,
        )

    @staticmethod
    def _parse_full_sample_rules(v2config: dict) -> list:
        custom_rules = []
        for key, rule_type in [
            ("spanNames4FullSampleStr", "exact"),
            ("spanNamePrefixes4FullSampleStr", "prefix"),
            ("spanNameSuffixes4FullSampleStr", "suffix"),
        ]:
            raw = v2config.get(key, "") or ""
            for item in raw.split(","):
                item = item.strip()
                if item:
                    custom_rules.append(
                        {"type": rule_type, "pattern": item, "rate": 1.0}
                    )
        return custom_rules

    def _cache_logging_config(self, pid: str, config: dict):
        """缓存应用的日志集成配置，供后续 integration 分析使用"""
        profiler = config.get("profiler", {})
        logging_cfg = profiler.get("logging", {})
        sls_cfg = {}
        # SLS 配置在顶层 key 中
        for k in [
            "SLS.project",
            "SLS.logStore",
            "SLS.bindType",
            "SLS.index",
            "SLS.storeView",
        ]:
            short_key = k.split(".", 1)[-1] if "." in k else k
            # 配置可能在 profiler 下或顶层
            val = profiler.get(k, "") or config.get(k, "") or ""
            if val:
                sls_cfg[short_key] = val
        self._logging_configs[pid] = {
            "logging_enable": logging_cfg.get("enable", True),
            "inject_trace_id": (
                logging_cfg.get("injectTraceId2Log", {}).get("enable", False)
                if isinstance(logging_cfg.get("injectTraceId2Log"), dict)
                else logging_cfg.get("injectTraceId2Log.enable", False)
            ),
            "sls_project": sls_cfg.get("project", ""),
            "sls_logstore": sls_cfg.get("logStore", ""),
        }
