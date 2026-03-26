"""
DataItem Schema 注册表

DataItem 名称 → Record 类型的映射
用于 DataStore 反序列化时还原为对应的强类型对象
"""

from typing import Optional

from sesora.schema import RosStackRecord, RosStackDriftRecord
from sesora.schema.k8s import (
    K8sDeploymentRecord,
    K8sStatefulSetRecord,
    K8sPodRecord,
    K8sPodProbesRecord,
    K8sHpaRecord,
    K8sVpaRecord,
    K8sAhpaMetricsRecord,
    K8sNamespaceRecord,
    K8sNodeRecord,
    K8sServiceRecord,
    K8sIngressRecord,
    K8sCronJobRecord,
    K8sEventRecord,
    K8sResourceQuotaRecord,
    K8sPvRecord,
    K8sNetworkPolicyRecord,
    K8sAuditLogRecord,
    K8sGatekeeperConstraintRecord,
    K8sKyvernoPolicyRecord,
    IstioDestinationRuleRecord,
    IstioVirtualServiceRecord,
    IstioGatewayRecord,
    ArgoCdApplicationRecord,
    FluxKustomizationRecord,
)
from .apm import (
    ApmServiceRecord,
    ApmServiceDependencyRecord,
    ApmTopologyMetricsRecord,
    ApmExternalDatabaseRecord,
    ApmExternalMessageRecord,
    ApmSamplingConfigRecord,
    ApmServiceDbMappingRecord,
    ApmCoverageAnalysisRecord,
    ApmTraceRecord,
)
from .cms import (
    CmsAlarmRuleRecord,
    CmsContactRecord,
    CmsContactGroupRecord,
    CmsAlarmSloRecord,
    CmsAlarmChannelSummaryRecord,
    CmsAlarmHistoryRecord,
    CmsEventTriggerRecord,
)
from .sls import (
    SlsLogstoreRecord,
    SlsLogSampleRecord,
    SlsLogStructureAnalysisRecord,
    SlsIndexConfigRecord,
    SlsQueryCapabilityRecord,
    SlsArchiveConfigRecord,
)
from .codeup import (
    CodeupPipelineRecord,
    CodeupRepoRecord,
    CodeupPipelineRunRecord,
    CodeupRepoFileTreeRecord,
    CodeupCommitRecord,
    CodeupPipelineConfigRecord,
    CodeupPipelineStageRecord,
    CodeupRepoTagRecord,
    CodeupBranchRecord,
    CodeupFileCommitRecord,
    CodeupPipelineRecord,
    CodeupPipelineMetricsRecord,
    CodeupRepoRecord,
)
from .fc import (
    FcFunctionRecord,
    FcAliasRecord,
    FcVersionRecord,
    FcColdStartMetricRecord,
    FcProvisionedConcurrencyRecord,
    FcObservabilityConfigRecord,
    FcUsageSummaryRecord,
    FcFunctionStatisticsRecord,
)
from .eventbridge import (
    EventBridgeEventSourceRecord,
    EventBridgeEventBusRecord,
    EventBridgeSchemaRecord,
    EbEventRuleRecord,
    EbEventTargetRecord,
)
from .rds_oss import (
    RdsInstanceRecord,
    RdsBackupPolicyRecord,
    RdsProxyRecord,
    OssBucketRecord,
    OssBucketLifecycleRecord,
    AlbListenerRecord,
    GtmAddressPoolRecord,
    TairInstanceModeRecord,
)
from .acr import (
    AcrRepositoryRecord,
    AcrImageRecord,
    AcrScanResultRecord,
)
from .chaos import (
    ChaosExperimentRecord,
    ChaosExperimentRunRecord,
    ChaosScheduleRecord,
    ChaosWorkflowRecord,
)
from .policy import (
    KyvernoPolicyRecord,
    KyvernoPolicyViolationRecord,
    OpaConstraintTemplateRecord,
    OpaConstraintRecord,
    OpaViolationRecord,
)
from .grafana import (
    GrafanaDashboardRecord,
    GrafanaFolderRecord,
    GrafanaDashboardAnalysisRecord,
)
from .manual import (
    ManualFallbackConfigRecord,
    ManualBulkheadConfigRecord,
    ManualDrPlanRecord,
    ManualRtoRpoRecord,
    ManualDrTestingRecord,
    ManualDataConsistencyRecord,
    ManualDataOwnershipRecord,
    ManualDataMigrationRecord,
    ManualConsistencyModelRecord,
)
from .ecs import (
    EcsInstanceRecord,
    EcsSecurityGroupRecord,
    EcsSecurityGroupRuleRecord,
)

DATAITEM_SCHEMA_LIST: list[type] = [
    # ==================== K8s 工作负载 ====================
    K8sDeploymentRecord,
    K8sStatefulSetRecord,
    K8sPodRecord,
    K8sPodProbesRecord,
    K8sCronJobRecord,
    # ==================== K8s 自动伸缩 ====================
    K8sHpaRecord,
    K8sVpaRecord,
    K8sAhpaMetricsRecord,
    # ==================== K8s 网络 ====================
    K8sServiceRecord,
    K8sIngressRecord,
    K8sNetworkPolicyRecord,
    # ==================== K8s 基础资源 ====================
    K8sNamespaceRecord,
    K8sNodeRecord,
    K8sResourceQuotaRecord,
    K8sPvRecord,
    # ==================== K8s 事件/日志 ====================
    K8sEventRecord,
    K8sAuditLogRecord,
    # ==================== 服务网格 ====================
    IstioDestinationRuleRecord,
    IstioVirtualServiceRecord,
    ArgoCdApplicationRecord,
    IstioGatewayRecord,
    FluxKustomizationRecord,
    # ==================== K8s 策略引擎 ====================
    K8sGatekeeperConstraintRecord,
    K8sKyvernoPolicyRecord,
    # ==================== APM ====================
    ApmServiceRecord,
    ApmTraceRecord,
    ApmServiceDependencyRecord,
    ApmTopologyMetricsRecord,
    ApmExternalDatabaseRecord,
    ApmExternalMessageRecord,
    ApmServiceDbMappingRecord,
    ApmSamplingConfigRecord,
    ApmCoverageAnalysisRecord,
    # ==================== CMS ====================
    CmsAlarmRuleRecord,
    CmsContactRecord,
    CmsContactGroupRecord,
    CmsAlarmSloRecord,
    CmsAlarmChannelSummaryRecord,
    CmsAlarmHistoryRecord,
    CmsEventTriggerRecord,
    # ==================== SLS ====================
    SlsLogstoreRecord,
    SlsLogSampleRecord,
    SlsLogStructureAnalysisRecord,
    SlsIndexConfigRecord,
    SlsQueryCapabilityRecord,
    SlsArchiveConfigRecord,
    # ==================== Codeup ====================
    CodeupPipelineRecord,
    CodeupRepoRecord,
    CodeupPipelineRunRecord,
    CodeupPipelineMetricsRecord,
    CodeupRepoFileTreeRecord,
    CodeupCommitRecord,
    CodeupPipelineConfigRecord,
    CodeupPipelineStageRecord,
    CodeupRepoTagRecord,
    CodeupBranchRecord,
    CodeupFileCommitRecord,
    # ==================== FC ====================
    FcFunctionRecord,
    FcAliasRecord,
    FcVersionRecord,
    FcColdStartMetricRecord,
    FcProvisionedConcurrencyRecord,
    FcFunctionStatisticsRecord,
    FcObservabilityConfigRecord,
    FcUsageSummaryRecord,
    # ==================== EventBridge ====================
    EventBridgeEventSourceRecord,
    EventBridgeEventBusRecord,
    EventBridgeSchemaRecord,
    EbEventRuleRecord,
    EbEventTargetRecord,
    # ==================== RDS/OSS ====================
    RdsInstanceRecord,
    RdsBackupPolicyRecord,
    RdsProxyRecord,
    OssBucketRecord,
    OssBucketLifecycleRecord,
    RosStackRecord,
    RosStackDriftRecord,
    TairInstanceModeRecord,
    # ==================== ALB/GTM ====================
    AlbListenerRecord,
    GtmAddressPoolRecord,
    # ==================== ACR ====================
    AcrRepositoryRecord,
    AcrImageRecord,
    AcrScanResultRecord,
    # ==================== Chaos Engineering ====================
    ChaosExperimentRecord,
    ChaosExperimentRunRecord,
    ChaosScheduleRecord,
    ChaosWorkflowRecord,
    # ==================== Policy as Code ====================
    KyvernoPolicyRecord,
    KyvernoPolicyViolationRecord,
    OpaConstraintTemplateRecord,
    OpaConstraintRecord,
    OpaViolationRecord,
    # ==================== Grafana ====================
    GrafanaDashboardRecord,
    GrafanaFolderRecord,
    GrafanaDashboardAnalysisRecord,
    # ==================== Manual/Questionnaire ====================
    ManualFallbackConfigRecord,
    ManualBulkheadConfigRecord,
    ManualDrPlanRecord,
    ManualRtoRpoRecord,
    ManualDrTestingRecord,
    ManualDataConsistencyRecord,
    ManualDataOwnershipRecord,
    ManualDataMigrationRecord,
    ManualConsistencyModelRecord,
    # ==================== ECS ====================
    EcsInstanceRecord,
    EcsSecurityGroupRecord,
    EcsSecurityGroupRuleRecord,
]

DATAITEM_SCHEMA_REGISTRY = {
    record.DATAITEM_NAME: record for record in DATAITEM_SCHEMA_LIST
}


def get_record_type(dataitem_name: str) -> Optional[type]:
    """
    根据 DataItem 名称获取对应的 Record 类型

    Args:
        dataitem_name: DataItem 名称，如 "k8s.deployment.list"

    Returns:
        Record 类型，如果未找到则返回 None
    """
    return DATAITEM_SCHEMA_REGISTRY.get(dataitem_name)


def register_record_type(dataitem_name: str, record_type: type) -> None:
    """
    注册新的 DataItem Record 类型

    Args:
        dataitem_name: DataItem 名称
        record_type: 对应的 Record 类型
    """
    DATAITEM_SCHEMA_REGISTRY[dataitem_name] = record_type


def list_all_dataitems() -> list[str]:
    """
    列出所有已注册的 DataItem 名称

    Returns:
        DataItem 名称列表
    """
    return list(DATAITEM_SCHEMA_REGISTRY.keys())


def get_dataitems_by_prefix(prefix: str) -> list[str]:
    """
    根据前缀获取 DataItem 名称列表

    Args:
        prefix: 前缀，如 "k8s." 或 "apm."

    Returns:
        匹配的 DataItem 名称列表
    """
    return [name for name in DATAITEM_SCHEMA_REGISTRY.keys() if name.startswith(prefix)]
