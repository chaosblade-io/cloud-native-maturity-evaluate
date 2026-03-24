from datetime import datetime
from typing import List

from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_fc20230330 import models as fc_models

from sesora.core.context import AssessmentContext
from sesora.core.dataitem import DataSource
from sesora.schema.fc import (
    FcFunctionRecord,
    FcAliasRecord,
    FcVersionRecord,
    FcUsageSummaryRecord,
)


class FCCollector:
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.client = self._create_client()

    def _create_client(self) -> FCClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            access_key_id=creds.access_key_id,
            access_key_secret=creds.access_key_secret,
            endpoint=f"fcv3.{creds.region}.aliyuncs.com",
            protocol="https",
        )
        return FCClient(config)

    def collect(self) -> DataSource:
        records: List = []
        status = "ok"

        try:
            # 获取服务名称列表（FC 3.0 中服务名作为函数的逻辑分组）
            function_names = self._get_function_names()

            runtime_types = set()
            trigger_types = set()
            functions_with_alias = 0
            functions_with_version = 0
            functions = []

            if function_names:
                for function_name in function_names:
                    print(f"正在采集函数 {function_name} 的信息...")
                    # 采集函数列表
                    function = self._collect_function_detail(function_name)
                    functions.append(function)
            else:
                print("未配置 FC 服务名称，将直接采集所有函数...")
                functions = self._list_all_functions_directly()
                records.extend(functions)
                print(f"  采集到 {len(functions)} 个函数")

            total_functions = len(functions)
            for func in functions:
                if func.runtime:
                    runtime_types.add(func.runtime)

                # 收集触发器类型
                for trigger in func.triggers:
                    trigger_type = trigger.get("triggerType", "")
                    if trigger_type:
                        trigger_types.add(trigger_type)

                # 采集别名
                aliases = self._collect_aliases(func.function_name)
                records.extend(aliases)
                if aliases:
                    functions_with_alias += 1
                    print(
                        f"    函数 {func.function_name}: 采集到 {len(aliases)} 个别名"
                    )

                # 采集版本
                versions = self._collect_versions(func.function_name)
                records.extend(versions)
                if versions:
                    functions_with_version += 1
                    print(
                        f"    函数 {func.function_name}: 采集到 {len(versions)} 个版本"
                    )

            # 创建使用汇总记录
            usage_summary = FcUsageSummaryRecord(
                total_functions=total_functions,
                trigger_types=list(trigger_types),
                trigger_type_count=len(trigger_types),
                runtime_types=list(runtime_types),
                runtime_type_count=len(runtime_types),
                functions_with_alias=functions_with_alias,
                functions_with_version=functions_with_version,
            )
            records.append(usage_summary)
            print(f"\nFC 采集汇总: {total_functions} 个函数")

        except Exception as e:
            status = "error"
            print(f"FC 采集失败: {e}")

        return DataSource(
            collector="fc_collector",
            collected_at=datetime.now(),
            status=status,
            records=records,
        )

    def _get_function_names(self) -> List[str]:
        """
        获取要采集的服务名称列表

        Returns:
            List[str]: 服务名称列表
        """
        function_names = []

        # 从 context 获取
        if self.context.fc_function_names:
            function_names = self.context.fc_function_names

        return function_names

    def _list_all_functions_directly(self) -> List[FcFunctionRecord]:
        records: List[FcFunctionRecord] = []

        next_token = None
        while True:
            response = self.client.list_functions(
                fc_models.ListFunctionsRequest(
                    next_token=next_token,
                    limit=100,
                )
            )
            body = response.body

            for func in body.functions:
                record = self._parse_function(func)
                records.append(record)

            next_token = body.next_token
            if not next_token:
                break

        return records

    def _collect_function_detail(self, function_name: str) -> FcFunctionRecord:
        response = self.client.get_function(
            function_name, fc_models.GetFunctionRequest()
        )
        return self._parse_function(response.body)

    def _parse_function(self, func: fc_models.Function) -> FcFunctionRecord:
        function_name = func.function_name

        # 解析创建时间
        create_time = datetime.fromisoformat(func.created_time.replace("Z", "+00:00"))

        # 解析修改时间
        last_modified_time = datetime.fromisoformat(func.last_modified_time.replace("Z", "+00:00"))

        # 解析环境变量
        environment_variables = func.environment_variables

        # 解析触发器（ListFunctions 可能返回 triggers）
        triggers = []
        list_triggers_request = fc_models.ListTriggersRequest()
        response = self.client.list_triggers(function_name, list_triggers_request)
        resp_triggers = response.body.triggers
        for trigger in resp_triggers:
            trigger_dict = {
                "triggerName": trigger.trigger_name,
                "triggerType": trigger.trigger_type,
                "qualifier": trigger.qualifier,
                "invocationRole": trigger.invocation_role,
                "sourceArn": trigger.source_arn,
            }
            triggers.append(trigger_dict)

        # 解析层
        layers = []
        layers_data = func.layers
        layers = [str(layer) for layer in layers_data]

        # 解析日志配置
        log_config = {}
        log_config_data = func.log_config
        log_config = {
            "logstore": log_config_data.logstore,
            "project": log_config_data.project,
            "enable_instance_metrics": log_config_data.enable_instance_metrics,
            "enable_request_metrics": log_config_data.enable_request_metrics,
        }

        # 解析链路追踪配置
        trace_config = {}
        trace_config_data = func.tracing_config
        trace_config = {
            "type": trace_config_data.type,
            "params": trace_config_data.params,
        }

        # 解析自定义容器配置
        custom_container_config = {}
        if func.custom_container_config:
            container_config = func.custom_container_config
            custom_container_config = {
                "image": container_config.image,
                "command": container_config.command,
                "entrypoint": container_config.entrypoint,
                "port": container_config.port,
            }

        return FcFunctionRecord(
            function_name=function_name,
            runtime=func.runtime,
            handler=func.handler,
            memory_size=func.memory_size,
            timeout=func.timeout,
            disk_size=func.disk_size,
            cpu=func.cpu,
            gpu_memory_size=func.memory_size,
            environment_variables=environment_variables,
            layers=layers,
            instance_concurrency=func.instance_concurrency,
            triggers=triggers,
            reserved_instances=0,  # TODO: 需要通过其他 API 获取
            log_config=log_config,
            trace_config=trace_config,
            custom_container_config=custom_container_config,
            last_modified_time=last_modified_time,
            create_time=create_time,
        )

    def _collect_aliases(self, function_name: str) -> List[FcAliasRecord]:
        records: List[FcAliasRecord] = []

        next_token = None
        while True:
            response = self.client.list_aliases(
                function_name,
                fc_models.ListAliasesRequest(
                    next_token=next_token,
                    limit=100,
                ),
            )
            body = response.body

            for alias in body.aliases:
                record = self._parse_alias(alias)
                records.append(record)

            next_token = body.next_token
            if not next_token:
                break

        return records

    def _parse_alias(self, alias: fc_models.Alias) -> FcAliasRecord:
        alias_name = alias.alias_name
        # 解析创建时间
        created_time = datetime.fromisoformat(alias.created_time.replace("Z", "+00:00"))
        # 解析修改时间
        last_modified_time = datetime.fromisoformat(alias.last_modified_time.replace("Z", "+00:00"))
        # 解析灰度版本权重
        additional_version_weight = alias.additional_version_weight
        return FcAliasRecord(
            alias_name=alias_name,
            version_id=alias.version_id,
            description=alias.description,
            additional_version_weight=additional_version_weight,
            created_time=created_time,
            last_modified_time=last_modified_time,
        )

    def _collect_versions(self, function_name: str) -> List[FcVersionRecord]:
        records: List[FcVersionRecord] = []

        next_token = None
        while True:
            response = self.client.list_function_versions(
                function_name,
                fc_models.ListFunctionVersionsRequest(
                    next_token=next_token,
                    limit=100,
                ),
            )
            body = response.body

            for version in body.versions:
                record = self._parse_version(version, function_name)
                records.append(record)

            next_token = body.next_token
            if not next_token:
                break

        return records

    def _parse_version(
        self, version: fc_models.Version, function_name: str
    ) -> FcVersionRecord:
        version_id = version.version_id
        # 解析创建时间
        created_time = datetime.fromisoformat(version.created_time.replace("Z", "+00:00"))
        return FcVersionRecord(
            function_name=function_name,
            version_id=version_id,
            description=version.description,
            created_time=created_time,
        )
