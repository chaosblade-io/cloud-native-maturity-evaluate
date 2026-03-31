import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import json

from alibabacloud_credentials.client import Client as CredentialClient

from sesora.collectors.ack_collector import ACKCollector, ACKCollectorConfig
from sesora.collectors.acr_collector import ACRCollector, ACRCollectorConfig
from sesora.collectors.alb_collector import ALBCollector, ALBCollectorConfig
from sesora.collectors.arms_collector import ARMSCollector, ARMSCollectorConfig
from sesora.collectors.cms_collector import CMSCollector, CMSCollectorConfig
from sesora.collectors.codeup_collector import CodeupCollector, CodeupCollectorConfig
from sesora.collectors.ecs_collector import ECSCollector, ECSCollectorConfig
from sesora.collectors.eventbridge_collector import EventBridgeCollector, EventBridgeCollectorConfig
from sesora.collectors.fc_collector import FCCollector, FCCollectorConfig
from sesora.collectors.grafana_collector import GrafanaCollector, GrafanaCollectorConfig
from sesora.collectors.gtm_collector import GTMCollector, GTMCollectorConfig
from sesora.collectors.rds_collector import RDSCollector, RDSCollectorConfig
from sesora.collectors.oss_collector import OSSCollector, OSSCollectorConfig
from sesora.collectors.ros_collector import ROSCollector, ROSCollectorConfig
from sesora.collectors.sls_collector import SLSCollector, SLSCollectorConfig
from sesora.collectors.tair_collector import TairCollector, TairCollectorConfig

PROJECT_ROOT = Path(__file__).parent.parent
env_path = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=env_path, override=True)

sys.path.insert(0, str(PROJECT_ROOT))

from sesora.core.context import AssessmentContext
from sesora.core.dataitem import DataSource, SourceStatus
from sesora.store.sqlite_store import SQLiteDataStore
from sesora.schema import CodeupFileCommitRecord


def parse_env_list(env_value: str) -> list:
    """从环境变量解析列表（JSON格式）"""
    if not env_value:
        return []
    try:
        return json.loads(env_value)
    except json.JSONDecodeError:
        # 如果不是JSON格式，尝试按逗号分割
        return [item.strip() for item in env_value.split(',') if item.strip()]


def validate_config() -> dict:
    """
    验证必需的配置项
    
    Returns:
        配置字典
    """
    config = {
        # 基础信息
        'region': os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong'),
        'ak': os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID', ''),
        'sk': os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET', ''),

        # 阿里云凭证
        'aliyun_credentials': {
            'access_key_id': os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID', ''),
            'access_key_secret': os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET', ''),
            'account_id': os.getenv('ALIBABA_CLOUD_ACCOUNT_ID', ''),
            'security_token': os.getenv('ALIBABA_CLOUD_SECURITY_TOKEN', ''),
            'region': os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong'),
        },

        # ACK 配置
        'cluster_id': os.getenv('ACK_CLUSTER_ID', ''),
        'namespaces': parse_env_list(os.getenv('ACK_NAMESPACES', '')),
        'kubeconfig_path': os.getenv('KUBECONFIG_PATH', ''),
        'kubeconfig_paths': parse_env_list(os.getenv('KUBECONFIG_PATHS', '')),
        'kubeconfig_context': os.getenv('KUBECONFIG_CONTEXT', ''),

        # ARMS 配置
        'arms_workspace_id': os.getenv('ARMS_WORKSPACE_ID', ''),

        # ROS 配置
        'ros_stack_name': parse_env_list(os.getenv('ROS_STACK_NAME', '')),
        'ros_region': os.getenv('ROS_REGION', os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong')),

        # SLS 配置
        'sls_project': os.getenv('SLS_PROJECT', ''),
        'sls_logstores': parse_env_list(os.getenv('SLS_LOGSTORES', '')),
        'sls_region': os.getenv('SLS_REGION', os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong')),

        # Codeup 配置
        'yunxiao_token': os.getenv('YUNXIAO_TOKEN', ''),
        'codeup_org_id': os.getenv('CODEUP_ORG_ID', ''),
        'codeup_repo_ids': parse_env_list(os.getenv('CODEUP_REPO_IDS', '')),
        'codeup_pipeline_ids': parse_env_list(os.getenv('CODEUP_PIPELINE_IDS', '')),
        'codeup_project_name': os.getenv('CODEUP_PROJECT_NAME', ''),

        # FC 配置
        'fc_function_names': parse_env_list(os.getenv('FC_FUNCTION_NAMES', '')),

        # EventBridge 配置
        'eventbridge_bus_names': parse_env_list(os.getenv('EVENTBRIDGE_BUS_NAMES', '')),

        # RDS 配置
        'rds_instance_ids': parse_env_list(os.getenv('RDS_INSTANCE_IDS', '')),
        'rds_region': os.getenv('RDS_REGION', os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong')),

        # OSS 配置
        'oss_bucket_names': parse_env_list(os.getenv('OSS_BUCKET_NAMES', '')),
        'oss_region': os.getenv('OSS_REGION', os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong')),

        # ACR 配置
        'acr_instance_ids': parse_env_list(os.getenv('ACR_INSTANCE_IDS', '')),
        'otel_only': os.getenv('ACR_OTEL_ONLY', 'true').lower() == 'true',

        # ALB 配置
        'alb_load_balancer_ids': parse_env_list(os.getenv('ALB_LOAD_BALANCER_IDS', '')),

        # GTM 配置
        'gtm_instance_id': os.getenv('GTM_INSTANCE_ID', ''),
        # ECS 配置
        'ecs_region': os.getenv('ECS_REGION', os.getenv('ALIBABA_CLOUD_REGION', 'cn-hongkong')),

        # Grafana 配置
        'grafana_workspace_id': os.getenv('GRAFANA_WORKSPACE_ID', ''),
        'grafana_url': os.getenv('GRAFANA_URL', ''),
        'grafana_api_token': os.getenv('GRAFANA_API_TOKEN', ''),
        'grafana_folder_ids': parse_env_list(os.getenv('GRAFANA_FOLDER_IDS', '')),
        'grafana_tags': parse_env_list(os.getenv('GRAFANA_TAGS', '')),

        # Tair/Redis 配置
        'tair_instance_ids': parse_env_list(os.getenv('TAIR_INSTANCE_IDS', '')),
    }

    return config


def create_context(config: dict) -> AssessmentContext:
    """
    创建评估上下文
    """
    # 创建阿里云凭证
    aliyun_credentials = CredentialClient()

    return AssessmentContext(
        # 基础信息
        region=config['region'],
        cluster_id=config.get('cluster_id', ''),
        namespaces=config.get('namespaces', []),

        # ARMS
        arms_workspace_id=config.get('arms_workspace_id', ''),

        # ROS
        ros_stack_name=config.get('ros_stack_name') or None,
        ros_region=config.get('ros_region', ''),

        # SLS
        sls_project=config.get('sls_project', ''),
        sls_logstores=config.get('sls_logstores', []),
        sls_region=config.get('sls_region', ''),

        # Codeup
        codeup_org_id=config.get('codeup_org_id', ''),
        codeup_repo_ids=config.get('codeup_repo_ids', []),
        codeup_pipeline_ids=config.get('codeup_pipeline_ids', []),
        yunxiao_token=config.get('yunxiao_token', ''),
        codeup_project_name=config.get('codeup_project_name', ''),

        # FC
        fc_function_names=config.get('fc_function_names', []),

        # EventBridge
        eventbridge_bus_names=config.get('eventbridge_bus_names', []),

        # RDS
        rds_instance_ids=config.get('rds_instance_ids', []),
        rds_region=config.get('rds_region', ''),

        # OSS
        oss_bucket_names=config.get('oss_bucket_names', []),
        oss_region=config.get('oss_region', ''),

        # ACR
        acr_instance_ids=config.get('acr_instance_ids', []),
        otel_only=config.get('otel_only', True),

        # ALB
        alb_load_balancer_ids=config.get('alb_load_balancer_ids', []),

        # GTM
        gtm_instance_id=config.get('gtm_instance_id', ''),

        # Grafana
        grafana_workspace_id=config.get('grafana_workspace_id', ''),
        grafana_url=config.get('grafana_url', ''),
        grafana_api_token=config.get('grafana_api_token', ''),
        grafana_folder_ids=config.get('grafana_folder_ids', []),
        grafana_tags=config.get('grafana_tags', []),

        # 凭证
        aliyun_credentials=aliyun_credentials,

        # K8s 配置
        kubeconfig_paths=config.get('kubeconfig_paths', []),
        kubeconfig_context=config.get('kubeconfig_context', ''),

        # ECS
        ecs_region=config.get('ecs_region', ''),

        # Tair/Redis
        tair_instance_ids=config.get('tair_instance_ids', []),
    )


def save_to_database(data_source: DataSource, db_path: Path, source_type: str) -> None:
    """
    将采集结果保存到数据库
    
    Args:
        data_source: 采集到的数据源
        db_path: 数据库文件路径
        source_type: 数据源类型 ('codeup' 或 'fc')
    """
    type_mapping = {}

    if source_type == 'codeup':
        from sesora.schema.codeup import (
            CodeupPipelineRecord,
            CodeupPipelineMetricsRecord,
            CodeupPipelineConfigRecord,
            CodeupPipelineStageRecord,
            CodeupPipelineRunRecord,
            CodeupRepoRecord,
            CodeupRepoFileTreeRecord,
            CodeupRepoTagRecord,
            CodeupBranchRecord,
            CodeupCommitRecord,
        )
        type_mapping = {
            CodeupRepoRecord: "codeup.repo.list",
            CodeupRepoFileTreeRecord: "codeup.repo.file_tree",
            CodeupRepoTagRecord: "codeup.repo.tags",
            CodeupBranchRecord: "codeup.branch.list",
            CodeupCommitRecord: "codeup.commit.list",
            CodeupPipelineRecord: "codeup.pipeline.list",
            CodeupPipelineConfigRecord: "codeup.pipeline.config",
            CodeupPipelineStageRecord: "codeup.pipeline.stages",
            CodeupPipelineRunRecord: "codeup.pipeline.runs",
            CodeupPipelineMetricsRecord: "codeup.pipeline.metrics",
            CodeupFileCommitRecord: "codeup.file.commits",
        }
    elif source_type == 'fc':
        from sesora.schema.fc import (
            FcFunctionRecord,
            FcAliasRecord,
            FcVersionRecord,
            FcUsageSummaryRecord,
        )
        type_mapping = {
            FcFunctionRecord: "fc.function.list",
            FcAliasRecord: "fc.alias.list",
            FcVersionRecord: "fc.version.list",
            FcUsageSummaryRecord: "fc.usage.summary",
        }
    elif source_type == 'ack':
        from sesora.schema.k8s import (
            K8sNodeRecord, K8sNamespaceRecord,
            K8sDeploymentRecord, K8sStatefulSetRecord,
            K8sPodRecord, K8sPodProbesRecord, K8sCronJobRecord,
            K8sServiceRecord, K8sIngressRecord, K8sNetworkPolicyRecord,
            K8sEventRecord, K8sHpaRecord, K8sVpaRecord, K8sAhpaMetricsRecord,
            K8sResourceQuotaRecord, K8sPvRecord,
        )
        type_mapping = {
            K8sNodeRecord: "k8s.node.list",
            K8sNamespaceRecord: "k8s.namespace.list",
            K8sDeploymentRecord: "k8s.deployment.list",
            K8sStatefulSetRecord: "k8s.statefulset.list",
            K8sPodRecord: "k8s.pod.list",
            K8sPodProbesRecord: "k8s.pod.probes",
            K8sCronJobRecord: "k8s.cronjob.list",
            K8sServiceRecord: "k8s.service.list",
            K8sIngressRecord: "k8s.ingress.list",
            K8sNetworkPolicyRecord: "k8s.networkpolicy.list",
            K8sEventRecord: "k8s.event.list",
            K8sHpaRecord: "k8s.hpa.list",
            K8sVpaRecord: "k8s.vpa.list",
            K8sAhpaMetricsRecord: "k8s.ahpa.metrics",
            K8sResourceQuotaRecord: "k8s.resourcequota.list",
            K8sPvRecord: "k8s.pv.list",
        }
    elif source_type == 'sls':
        from sesora.schema.sls import (
            SlsLogstoreRecord,
            SlsLogSampleRecord,
            SlsLogStructureAnalysisRecord,
            SlsIndexConfigRecord,
            SlsQueryCapabilityRecord,
            SlsArchiveConfigRecord,
        )
        type_mapping = {
            SlsLogstoreRecord: "sls.logstore.list",
            SlsLogSampleRecord: "sls.log_sample.recent",
            SlsLogStructureAnalysisRecord: "sls.log_structure_analysis",
            SlsIndexConfigRecord: "sls.index_config.list",
            SlsQueryCapabilityRecord: "sls.query.capability",
            SlsArchiveConfigRecord: "sls.archive_config.list",
        }
    elif source_type == 'rds':
        from sesora.schema.rds_oss import (
            RdsInstanceRecord,
            RdsBackupPolicyRecord,
            RdsProxyRecord,
        )
        type_mapping = {
            RdsInstanceRecord: "rds.instance.list",
            RdsBackupPolicyRecord: "rds.backup_policy.list",
            RdsProxyRecord: "rds.proxy.list",
        }
    elif source_type == 'cms':
        from sesora.schema.cms import (
            CmsContactRecord,
            CmsAlarmChannelSummaryRecord,
            CmsAlarmRuleRecord,
            CmsContactGroupRecord,
            CmsAlarmHistoryRecord,
            CmsEventTriggerRecord,
        )
        type_mapping = {
            CmsContactRecord: "cms.alarm_contact.list",
            CmsAlarmChannelSummaryRecord: "cms.alarm_channel.summary",
            CmsAlarmRuleRecord: "cms.alarm_rule.list",
            CmsContactGroupRecord: "cms.contact_group.list",
            CmsAlarmHistoryRecord: "cms.alarm.history",
            CmsEventTriggerRecord: "cms.event_trigger.list",
        }
    elif source_type == 'ros':
        from sesora.schema.ros import (
            RosStackRecord,
            RosStackDriftRecord,
        )
        type_mapping = {
            RosStackRecord: "ros.stack.list",
            RosStackDriftRecord: "ros.stack.drift",
        }
    elif source_type == 'oss':
        from sesora.schema.rds_oss import (
            OssBucketRecord,
            OssBucketLifecycleRecord,
        )
        type_mapping = {
            OssBucketRecord: "oss.bucket.list",
            OssBucketLifecycleRecord: "oss.bucket.lifecycle",
        }
    elif source_type == 'arms':
        from sesora.schema.apm import (
            ApmServiceRecord,
            ApmTraceRecord,
            ApmServiceDependencyRecord,
            ApmTopologyMetricsRecord,
            ApmExternalDatabaseRecord,
            ApmExternalMessageRecord,
            ApmServiceDbMappingRecord,
            ApmCoverageAnalysisRecord,
            ApmSamplingConfigRecord,
        )
        type_mapping = {
            ApmServiceRecord: "apm.service.list",
            ApmTraceRecord: "apm.trace.list",
            ApmServiceDependencyRecord: "apm.service.dependency",
            ApmTopologyMetricsRecord: "apm.topology.metrics",
            ApmExternalDatabaseRecord: "apm.external.database",
            ApmExternalMessageRecord: "apm.external.message",
            ApmServiceDbMappingRecord: "apm.service.db.mapping",
            ApmCoverageAnalysisRecord: "apm.coverage.analysis",
            ApmSamplingConfigRecord: "apm.sampling.config",
        }
    elif source_type == 'acr':
        from sesora.schema.acr import (
            AcrRepositoryRecord,
            AcrImageRecord,
            AcrScanResultRecord,
        )
        type_mapping = {
            AcrRepositoryRecord: "acr.repository.list",
            AcrImageRecord: "acr.image.list",
            AcrScanResultRecord: "acr.image_scan.list",
        }
    elif source_type == 'alb':
        from sesora.schema.rds_oss import (
            AlbListenerRecord,
        )
        type_mapping = {
            AlbListenerRecord: "alb.listener.list",
        }
    elif source_type == 'istio':
        from sesora.schema.k8s import (
            IstioDestinationRuleRecord,
            IstioVirtualServiceRecord,
        )
        type_mapping = {
            IstioDestinationRuleRecord: "istio.destinationrule.list",
            IstioVirtualServiceRecord: "istio.virtualservice.list",
        }
    elif source_type == 'ecs':
        from sesora.schema.ecs import (
            EcsInstanceRecord,
            EcsSecurityGroupRecord,
            EcsSecurityGroupRuleRecord,
        )
        type_mapping = {
            EcsInstanceRecord: "ecs.instance.list",
            EcsSecurityGroupRecord: "ecs.security_group.list",
            EcsSecurityGroupRuleRecord: "ecs.security_group_rule.list",
        }
    elif source_type == 'eventbridge':
        from sesora.schema.eventbridge import (
            EventBridgeEventSourceRecord,
            EventBridgeEventBusRecord,
            EbEventRuleRecord,
            EbEventTargetRecord,
        )
        type_mapping = {
            EventBridgeEventSourceRecord: "eventbridge.event_source.list",
            EventBridgeEventBusRecord: "eventbridge.event_bus.list",
            EbEventRuleRecord: "eventbridge.rule.list",
            EbEventTargetRecord: "eventbridge.target.list",
        }
    elif source_type == 'grafana':
        from sesora.schema.grafana import (
            GrafanaDashboardRecord,
            GrafanaFolderRecord,
            GrafanaDashboardAnalysisRecord,
        )
        type_mapping = {
            GrafanaDashboardRecord: "grafana.dashboard.list",
            GrafanaFolderRecord: "grafana.folder.list",
            GrafanaDashboardAnalysisRecord: "grafana.dashboard.analysis",
        }
    elif source_type == 'gtm':
        from sesora.schema.rds_oss import GtmAddressPoolRecord
        type_mapping = {
            GtmAddressPoolRecord: "gtm.address_pool.list",
        }
    elif source_type == 'tair':
        from sesora.schema.rds_oss import TairInstanceModeRecord
        type_mapping = {
            TairInstanceModeRecord: "tair.instance.list",
        }

    grouped_records: dict[str, list] = data_source.records_dict

    # 保存到数据库
    with SQLiteDataStore(db_path) as store:
        saved_count = 0

        for item_name, records in grouped_records.items():
            if records:
                source = DataSource(
                    collector=data_source.collector,
                    collected_at=data_source.collected_at,
                    status=SourceStatus.OK,
                    records=records,
                )
                store.put(item_name, source)
                saved_count += len(records)
                print(f"  保存 {item_name}: {len(records)} 条记录")

        print(f"  {source_type} 总计保存 {saved_count} 条记录")


def print_summary(data_source: DataSource, source_type: str) -> None:
    """打印采集结果摘要"""
    print(f"\n{source_type} 采集结果摘要:")
    print("-" * 40)
    print(f"  记录总数: {len(data_source.records)} 条")


def collect_codeup(context: AssessmentContext, db_path: Path) -> bool:
    """采集 Codeup 数据"""
    print("\n" + "=" * 60)
    print("开始采集 Codeup 数据...")
    print("=" * 60)

    # 创建 CodeupCollectorConfig
    config = CodeupCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        yunxiao_token=context.yunxiao_token,
        codeup_org_id=context.codeup_org_id,
        codeup_project_name=context.codeup_project_name,
    )
    collector = CodeupCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'codeup')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'codeup')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_fc(context: AssessmentContext, db_path: Path) -> bool:
    """采集 FC 数据"""
    print("\n" + "=" * 60)
    print("开始采集 FC 数据...")
    print("=" * 60)

    # 创建 FCCollectorConfig
    config = FCCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        fc_function_names=context.fc_function_names,
    )
    collector = FCCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'fc')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'fc')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_ack(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ACK 数据"""
    print("\n" + "=" * 60)
    print("开始采集 ACK 数据...")
    print("=" * 60)

    # 创建 ACKCollectorConfig
    config = ACKCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        cluster_id=context.cluster_id if context.cluster_id else None,
        kubeconfig_paths=context.kubeconfig_paths,
        namespaces=context.namespaces,
    )
    collector = ACKCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'ack')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'ack')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_sls(context: AssessmentContext, db_path: Path) -> bool:
    """采集 SLS 数据"""
    print("\n" + "=" * 60)
    print("开始采集 SLS 数据...")
    print("=" * 60)

    # 创建 SLSCollectorConfig
    config = SLSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        sls_project=context.sls_project,
        sls_region=context.sls_region or context.region,
    )
    collector = SLSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'sls')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'sls')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_rds(context: AssessmentContext, db_path: Path) -> bool:
    """采集 RDS 数据"""
    print("\n" + "=" * 60)
    print("开始采集 RDS 数据...")
    print("=" * 60)

    # 创建 RDSCollectorConfig
    config = RDSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        rds_region=context.rds_region,
        rds_instance_ids=context.rds_instance_ids,
    )
    collector = RDSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'rds')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'rds')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_cms(context: AssessmentContext, db_path: Path) -> bool:
    """采集 CMS 数据"""
    print("\n" + "=" * 60)
    print("开始采集 CMS 数据...")
    print("=" * 60)

    # 创建 CMSCollectorConfig
    config = CMSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
    )
    collector = CMSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'cms')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'cms')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_ros(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ROS 数据"""
    print("\n" + "=" * 60)
    print("开始采集 ROS 数据...")
    print("=" * 60)

    # 创建 ROSCollectorConfig
    config = ROSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        ros_region=context.ros_region,
        ros_stack_name=context.ros_stack_name,
    )
    collector = ROSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'ros')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'ros')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_oss(context: AssessmentContext, db_path: Path) -> bool:
    """采集 OSS 数据"""
    print("\n" + "=" * 60)
    print("开始采集 OSS 数据...")
    print("=" * 60)

    # 创建 OSSCollectorConfig
    config = OSSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.oss_region or context.region,
        oss_bucket_names=context.oss_bucket_names,
    )
    collector = OSSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'oss')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'oss')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_arms(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ARMS APM 数据"""
    print("\n" + "=" * 60)
    print("开始采集 ARMS APM 数据...")
    print("=" * 60)

    # 创建 ARMSCollectorConfig
    config = ARMSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
    )
    collector = ARMSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'arms')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'arms')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_acr(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ACR 容器镜像服务数据"""
    print("\n" + "=" * 60)
    print("开始采集 ACR 容器镜像服务数据...")
    print("=" * 60)

    # 创建 ACRCollectorConfig
    config = ACRCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        instance_ids=context.acr_instance_ids,
        otel_only=context.otel_only,
    )
    collector = ACRCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'acr')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'acr')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_alb(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ALB 应用负载均衡数据"""
    print("\n" + "=" * 60)
    print("开始采集 ALB 应用负载均衡数据...")
    print("=" * 60)

    # 创建 ALBCollectorConfig
    config = ALBCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        load_balancer_ids=context.alb_load_balancer_ids,
    )
    collector = ALBCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'alb')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'alb')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_istio(context: AssessmentContext, db_path: Path) -> bool:
    """采集 Istio 服务网格数据"""
    # TODO: remove this function
    return False


def collect_ecs(context: AssessmentContext, db_path: Path) -> bool:
    """采集 ECS 云服务器数据"""
    print("\n" + "=" * 60)
    print("开始采集 ECS 云服务器数据...")
    print("=" * 60)

    # 创建 ECSCollectorConfig
    config = ECSCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.ecs_region or context.region,
    )
    collector = ECSCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'ecs')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'ecs')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_eventbridge(context: AssessmentContext, db_path: Path) -> bool:
    """采集 EventBridge 事件总线数据"""
    print("\n" + "=" * 60)
    print("开始采集 EventBridge 事件总线数据...")
    print("=" * 60)

    # 创建 EventBridgeCollectorConfig
    config = EventBridgeCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        eventbridge_bus_names=context.eventbridge_bus_names,
    )
    collector = EventBridgeCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'eventbridge')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'eventbridge')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_grafana(context: AssessmentContext, db_path: Path) -> bool:
    """采集 Grafana 仪表盘数据"""
    print("\n" + "=" * 60)
    print("开始采集 Grafana 仪表盘数据...")
    print("=" * 60)

    # 检查必要的配置
    if not context.grafana_url and not context.grafana_workspace_id:
        print("跳过 Grafana 采集: 未配置 GRAFANA_URL 或 GRAFANA_WORKSPACE_ID")
        return False
    if not context.grafana_api_token:
        print("跳过 Grafana 采集: 未配置 GRAFANA_API_TOKEN")
        return False

    # 创建 GrafanaCollectorConfig
    config = GrafanaCollectorConfig(
        grafana_url=context.grafana_url,
        grafana_api_token=context.grafana_api_token,
        grafana_workspace_id=context.grafana_workspace_id,
        grafana_folder_ids=context.grafana_folder_ids,
        grafana_tags=context.grafana_tags,
    )
    collector = GrafanaCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'grafana')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'grafana')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_gtm(context: AssessmentContext, db_path: Path) -> bool:
    """采集 GTM 全局流量管理数据"""
    print("\n" + "=" * 60)
    print("开始采集 GTM 全局流量管理数据...")
    print("=" * 60)

    # 创建 GTMCollectorConfig
    config = GTMCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
    )
    collector = GTMCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'gtm')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'gtm')
        return True
    else:
        print("采集失败或无数据")
        return False


def collect_tair(context: AssessmentContext, db_path: Path) -> bool:
    """采集 Tair/Redis 数据"""
    print("\n" + "=" * 60)
    print("开始采集 Tair/Redis 数据...")
    print("=" * 60)

    # 创建 TairCollectorConfig
    config = TairCollectorConfig(
        aliyun_credentials=context.aliyun_credentials,
        region=context.region,
        tair_instance_ids=context.tair_instance_ids,
    )
    collector = TairCollector(config)

    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n采集完成! 耗时: {elapsed:.1f} 秒")
    print(f"状态: {data_source.status}")

    print_summary(data_source, 'tair')

    if data_source.status == SourceStatus.OK and data_source.records:
        save_to_database(data_source, db_path, 'tair')
        return True
    else:
        print("采集失败或无数据")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="SESORA 数据采集器（支持 Codeup、FC、ACK、SLS、RDS、CMS、ROS、EventBridge、Grafana、GTM、Tair）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--codeup", action="store_true", help="采集云效 Codeup 数据")
    parser.add_argument("--fc", action="store_true", help="采集函数计算 FC 数据")
    parser.add_argument("--ack", action="store_true", help="采集 ACK 容器服务 K8s 数据")
    parser.add_argument("--sls", action="store_true", help="采集 SLS 日志服务数据")
    parser.add_argument("--rds", action="store_true", help="采集 RDS 数据库数据")
    parser.add_argument("--cms", action="store_true", help="采集 CMS 云监控数据")
    parser.add_argument("--ros", action="store_true", help="采集 ROS 资源编排数据")
    parser.add_argument("--oss", action="store_true", help="采集 OSS 对象存储数据")
    parser.add_argument("--arms", action="store_true", help="采集 ARMS APM 数据")
    parser.add_argument("--acr", action="store_true", help="采集 ACR 容器镜像服务数据")
    parser.add_argument("--alb", action="store_true", help="采集 ALB 应用负载均衡数据")
    parser.add_argument("--istio", action="store_true", help="采集 Istio 服务网格数据")
    parser.add_argument("--ecs", action="store_true", help="采集 ECS 云服务器数据")
    parser.add_argument("--eventbridge", action="store_true", help="采集 EventBridge 事件总线数据")
    parser.add_argument("--grafana", action="store_true", help="采集 Grafana 仪表盘数据")
    parser.add_argument("--gtm", action="store_true", help="采集 GTM 全局流量管理数据")
    parser.add_argument("--tair", action="store_true", help="采集 Tair/Redis 数据")
    parser.add_argument("--db", type=str, default="sesora.db", help="数据库文件名")

    args = parser.parse_args()

    # 如果没有指定采集类型，默认采集全部
    collect_codeup_flag = args.codeup
    collect_fc_flag = args.fc
    collect_ack_flag = args.ack
    collect_sls_flag = args.sls
    collect_rds_flag = args.rds
    collect_cms_flag = args.cms
    collect_ros_flag = args.ros
    collect_oss_flag = args.oss
    collect_arms_flag = args.arms
    collect_acr_flag = args.acr
    collect_alb_flag = args.alb
    collect_istio_flag = args.istio
    collect_ecs_flag = args.ecs
    collect_eventbridge_flag = args.eventbridge
    collect_grafana_flag = args.grafana
    collect_gtm_flag = args.gtm
    collect_tair_flag = args.tair
    if not collect_codeup_flag and not collect_fc_flag and not collect_ack_flag and not collect_sls_flag and not collect_rds_flag and not collect_cms_flag and not collect_ros_flag and not collect_oss_flag and not collect_arms_flag and not collect_acr_flag and not collect_alb_flag and not collect_istio_flag and not collect_ecs_flag and not collect_eventbridge_flag and not collect_grafana_flag and not collect_gtm_flag and not collect_tair_flag:
        collect_codeup_flag = True
        collect_fc_flag = True
        collect_ack_flag = True
        collect_sls_flag = True
        collect_rds_flag = True
        collect_cms_flag = True
        collect_ros_flag = True
        collect_oss_flag = True
        collect_arms_flag = True
        collect_acr_flag = True
        collect_alb_flag = True
        collect_istio_flag = True
        collect_ecs_flag = True
        collect_eventbridge_flag = True
        collect_grafana_flag = True
        collect_gtm_flag = True
        collect_tair_flag = True

    print("=" * 60)
    print("SESORA 数据采集器")
    print("=" * 60)

    # 验证配置
    config = validate_config()

    context = create_context(config)

    # 数据库路径
    db_dir = PROJECT_ROOT / "data"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / args.db

    print(f"\n数据库: {db_path}")

    success_count = 0

    # 采集 Codeup
    if collect_codeup_flag:
        if collect_codeup(context, db_path):
            success_count += 1

    # 采集 FC
    if collect_fc_flag:
        if collect_fc(context, db_path):
            success_count += 1

    # 采集 ACK
    if collect_ack_flag:
        if collect_ack(context, db_path):
            success_count += 1

    # 采集 SLS
    if collect_sls_flag:
        if collect_sls(context, db_path):
            success_count += 1

    # 采集 RDS
    if collect_rds_flag:
        if collect_rds(context, db_path):
            success_count += 1

    # 采集 CMS
    if collect_cms_flag:
        if collect_cms(context, db_path):
            success_count += 1

    # 采集 ROS
    if collect_ros_flag:
        if collect_ros(context, db_path):
            success_count += 1

    # 采集 OSS
    if collect_oss_flag:
        if collect_oss(context, db_path):
            success_count += 1

    # 采集 ARMS
    if collect_arms_flag:
        if collect_arms(context, db_path):
            success_count += 1

    # 采集 ACR
    if collect_acr_flag:
        if collect_acr(context, db_path):
            success_count += 1

    # 采集 ALB
    if collect_alb_flag:
        if collect_alb(context, db_path):
            success_count += 1

    # 采集 Istio
    if collect_istio_flag:
        if collect_istio(context, db_path):
            success_count += 1

    # 采集 ECS
    if collect_ecs_flag:
        if collect_ecs(context, db_path):
            success_count += 1

    # 采集 EventBridge
    if collect_eventbridge_flag:
        if collect_eventbridge(context, db_path):
            success_count += 1

    # 采集 Grafana
    if collect_grafana_flag:
        if collect_grafana(context, db_path):
            success_count += 1

    # 采集 GTM
    if collect_gtm_flag:
        if collect_gtm(context, db_path):
            success_count += 1

    # 采集 Tair/Redis
    if collect_tair_flag:
        if collect_tair(context, db_path):
            success_count += 1

    print("\n" + "=" * 60)
    print(f"全部完成! 成功采集: {success_count} 个数据源")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    import logging

    logging.getLogger('apscheduler').setLevel(logging.CRITICAL)
    sys.exit(main())
