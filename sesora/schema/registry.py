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
from sesora.schema.apm import (
    ApmServiceRecord,
    ApmServiceDependencyRecord,
    ApmTopologyMetricsRecord,
    ApmExternalDatabaseRecord,
    ApmExternalMessageRecord,
    ApmSamplingConfigRecord,
    ApmServiceDbMappingRecord,
    ApmCoverageAnalysisRecord, ApmTraceRecord,
)
from sesora.schema.cms import (
    CmsAlarmRuleRecord,
    CmsContactRecord,
    CmsContactGroupRecord,
    CmsAlarmSloRecord,
    CmsAlarmChannelSummaryRecord,
    CmsAlarmHistoryRecord,
    CmsEventTriggerRecord,
)
from sesora.schema.sls import (
    SlsLogstoreRecord,
    SlsLogSampleRecord,
    SlsLogStructureAnalysisRecord,
    SlsIndexConfigRecord,
    SlsQueryCapabilityRecord,
    SlsArchiveConfigRecord,
)
from sesora.schema.codeup import (
    CodeupPipelineRunRecord,
    CodeupRepoFileTreeRecord,
    CodeupCommitRecord,
    CodeupPipelineConfigRecord,
    CodeupPipelineStageRecord,
    CodeupRepoTagRecord,
    CodeupBranchRecord,
    CodeupFileCommitRecord, CodeupPipelineRecord, CodeupPipelineMetricsRecord, CodeupRepoRecord,
)
from sesora.schema.fc import (
    FcFunctionRecord,
    FcAliasRecord,
    FcVersionRecord,
    FcColdStartMetricRecord,
    FcProvisionedConcurrencyRecord,
    FcObservabilityConfigRecord,
    FcUsageSummaryRecord,
    FcFunctionStatisticsRecord,
)
from sesora.schema.eventbridge import (
    EventBridgeEventSourceRecord,
    EventBridgeEventBusRecord,
    EventBridgeSchemaRecord,
    EbEventRuleRecord,
    EbEventTargetRecord,
    RocketMqTopicRecord,
)
from sesora.schema.rds_oss import (
    RdsInstanceRecord,
    RdsBackupPolicyRecord,
    RdsProxyRecord,
    OssBucketRecord,
    OssBucketLifecycleRecord,
    AlbListenerRecord,
    GtmAddressPoolRecord,
)
from sesora.schema.acr import (
    AcrRepositoryRecord,
    AcrImageRecord,
    AcrScanResultRecord,
)
from sesora.schema.chaos import (
    ChaosExperimentRecord,
    ChaosExperimentRunRecord,
    ChaosScheduleRecord,
    ChaosWorkflowRecord,
)
from sesora.schema.policy import (
    KyvernoPolicyRecord,
    KyvernoPolicyViolationRecord,
    OpaConstraintTemplateRecord,
    OpaConstraintRecord,
    OpaViolationRecord,
    PolicyEnforcementSummaryRecord,
)
from sesora.schema.grafana import (
    GrafanaDashboardRecord,
    GrafanaFolderRecord,
    GrafanaPanelRecord,
    GrafanaAlertRuleRecord,
    GrafanaDashboardAnalysisRecord,
    MetricIntervalRecord,
)
from sesora.schema.manual import (
    ManualQuestionnaireRecord,
    ManualFallbackConfigRecord,
    ManualBulkheadConfigRecord,
    ManualDrPlanRecord,
    ManualRtoRpoRecord,
    ManualDrTestingRecord,
    ManualDataConsistencyRecord,
    ManualDataOwnershipRecord,
    ManualDataMigrationRecord,
    ManualConfigManagementRecord,
    ManualConsistencyModelRecord,
)
from sesora.schema.cloud_storage import (
    CloudStorageProductRecord,
    CloudStorageSummaryRecord,
    RdsInstanceModeRecord,
    TairInstanceModeRecord,
)
from sesora.schema.ecs import (
    EcsInstanceRecord,
    EcsSecurityGroupRecord,
    EcsSecurityGroupRuleRecord,
)

# DataItem 名称 → Record 类型映射表
DATAITEM_SCHEMA_REGISTRY: dict[str, type] = {
    # ==================== K8s 工作负载 ====================
    "k8s.deployment.list": K8sDeploymentRecord,
    "k8s.statefulset.list": K8sStatefulSetRecord,
    "k8s.pod.list": K8sPodRecord,
    "k8s.pod.probes": K8sPodProbesRecord,
    "k8s.cronjob.list": K8sCronJobRecord,

    # ==================== K8s 自动伸缩 ====================
    "k8s.hpa.list": K8sHpaRecord,
    "k8s.vpa.list": K8sVpaRecord,
    "k8s.ahpa.metrics": K8sAhpaMetricsRecord,

    # ==================== K8s 网络 ====================
    "k8s.service.list": K8sServiceRecord,
    "k8s.ingress.list": K8sIngressRecord,
    "k8s.networkpolicy.list": K8sNetworkPolicyRecord,

    # ==================== K8s 基础资源 ====================
    "k8s.namespace.list": K8sNamespaceRecord,
    "k8s.node.list": K8sNodeRecord,
    "k8s.resourcequota.list": K8sResourceQuotaRecord,
    "k8s.pv.list": K8sPvRecord,

    # ==================== K8s 事件/日志 ====================
    "k8s.event.list": K8sEventRecord,
    "k8s.audit_log.recent": K8sAuditLogRecord,

    # ==================== 服务网格 ====================
    "k8s.istio.destination_rule.list": IstioDestinationRuleRecord,
    "k8s.istio.virtual_service.list": IstioVirtualServiceRecord,
    "k8s.argocd.app.list": ArgoCdApplicationRecord,

    "k8s.istio.gateway.list": IstioGatewayRecord,
    "k8s.argocd.application.list": ArgoCdApplicationRecord,
    "k8s.flux.kustomization.list": FluxKustomizationRecord,

    # ==================== K8s 策略引擎 ====================
    "k8s.gatekeeper.constraint.list": K8sGatekeeperConstraintRecord,
    "k8s.kyverno.policy.native.list": K8sKyvernoPolicyRecord,

    # ==================== APM ====================
    "apm.service.list": ApmServiceRecord,
    "apm.trace.list": ApmTraceRecord,
    "apm.service.dependency": ApmServiceDependencyRecord,
    "apm.topology.metrics": ApmTopologyMetricsRecord,
    "apm.external.database": ApmExternalDatabaseRecord,
    "apm.external.message": ApmExternalMessageRecord,
    "apm.service.db.mapping": ApmServiceDbMappingRecord,
    "apm.sampling.config": ApmSamplingConfigRecord,
    "apm.coverage.analysis": ApmCoverageAnalysisRecord,

    # ==================== CMS ====================
    "cms.alarm_rule.list": CmsAlarmRuleRecord,
    "cms.alarm_contact.list": CmsContactRecord,
    "cms.contact_group.list": CmsContactGroupRecord,
    "cms.alarm_rule.slo_analysis": CmsAlarmSloRecord,
    "cms.alarm_channel.summary": CmsAlarmChannelSummaryRecord,
    "cms.alarm.history": CmsAlarmHistoryRecord,
    "cms.event_trigger.list": CmsEventTriggerRecord,

    # ==================== SLS ====================
    "sls.logstore.list": SlsLogstoreRecord,
    "sls.log_sample.recent": SlsLogSampleRecord,
    "sls.log_structure_analysis": SlsLogStructureAnalysisRecord,
    "sls.index_config.list": SlsIndexConfigRecord,
    "sls.query.capability": SlsQueryCapabilityRecord,
    "sls.archive_config.list": SlsArchiveConfigRecord,

    # ==================== Codeup ====================
    "codeup.pipeline.list": CodeupPipelineRecord,
    "codeup.repo.list": CodeupRepoRecord,
    "codeup.pipeline.runs": CodeupPipelineRunRecord,
    "codeup.pipeline.metrics": CodeupPipelineMetricsRecord,
    "codeup.repo.file_tree": CodeupRepoFileTreeRecord,
    "codeup.commit.list": CodeupCommitRecord,
    "codeup.pipeline.config": CodeupPipelineConfigRecord,
    "codeup.pipeline.stages": CodeupPipelineStageRecord,
    "codeup.repo.tags": CodeupRepoTagRecord,
    "codeup.branch.list": CodeupBranchRecord,
    "codeup.file.commits": CodeupFileCommitRecord,

    # ==================== FC ====================
    "fc.function.list": FcFunctionRecord,
    "fc.alias.list": FcAliasRecord,
    "fc.version.list": FcVersionRecord,
    "fc.cold_start_metrics": FcColdStartMetricRecord,
    "fc.provisioned_concurrency.config": FcProvisionedConcurrencyRecord,
    "fc.function.statistics": FcFunctionStatisticsRecord,
    "fc.observability.config": FcObservabilityConfigRecord,
    "fc.usage.summary": FcUsageSummaryRecord,

    # ==================== EventBridge ====================
    "eventbridge.source.list": EventBridgeEventSourceRecord,
    "eventbridge.bus.list": EventBridgeEventBusRecord,
    "eventbridge.schema.list": EventBridgeSchemaRecord,
    "eventbridge.rule.list": EbEventRuleRecord,
    "eventbridge.target.list": EbEventTargetRecord,
    "rocketmq.topic.list": RocketMqTopicRecord,

    # ==================== RDS/OSS ====================
    "rds.instance.list": RdsInstanceRecord,
    "rds.backup_policy.list": RdsBackupPolicyRecord,
    "rds.proxy.list": RdsProxyRecord,
    "oss.bucket.list": OssBucketRecord,
    "oss.bucket.lifecycle.list": OssBucketLifecycleRecord,
    "oss.bucket.lifecycle": OssBucketLifecycleRecord,
    "ros.stack.list": RosStackRecord,
    "ros.stack.drift": RosStackDriftRecord,
    
    # ==================== ALB/GTM ====================
    "alb.listener.list": AlbListenerRecord,
    "gtm.address_pool.list": GtmAddressPoolRecord,

    # ==================== ACR ====================
    "acr.repository.list": AcrRepositoryRecord,
    "acr.image.list": AcrImageRecord,
    "acr.image_scan.list": AcrScanResultRecord,

    # ==================== Chaos Engineering ====================
    "chaos.experiment.list": ChaosExperimentRecord,
    "chaos.experiment_run.list": ChaosExperimentRunRecord,
    "chaos.schedule.list": ChaosScheduleRecord,
    "chaos.workflow.list": ChaosWorkflowRecord,

    # ==================== Policy as Code ====================
    "policy.enforcement.summary": PolicyEnforcementSummaryRecord,
    "k8s.kyverno.policy.list": KyvernoPolicyRecord,
    "k8s.kyverno.violation.list": KyvernoPolicyViolationRecord,
    "k8s.opa.constraint_template.list": OpaConstraintTemplateRecord,
    "k8s.opa.constraint.list": OpaConstraintRecord,
    "k8s.opa.violation.list": OpaViolationRecord,
    
    # ==================== Grafana ====================
    "grafana.dashboard.list": GrafanaDashboardRecord,
    "grafana.folder.list": GrafanaFolderRecord,
    "grafana.panel.list": GrafanaPanelRecord,
    "grafana.alert_rule.list": GrafanaAlertRuleRecord,
    "grafana.dashboard.analysis": GrafanaDashboardAnalysisRecord,
    "metric.interval.config": MetricIntervalRecord,

    # ==================== Manual/Questionnaire ====================
    "manual.questionnaire": ManualQuestionnaireRecord,
    "manual.fallback.config": ManualFallbackConfigRecord,
    "manual.bulkhead.config": ManualBulkheadConfigRecord,
    "manual.dr_plan": ManualDrPlanRecord,
    "manual.rto_rpo": ManualRtoRpoRecord,
    "manual.dr_testing": ManualDrTestingRecord,
    "manual.data_consistency": ManualDataConsistencyRecord,
    "manual.data_ownership": ManualDataOwnershipRecord,
    "manual.data_migration": ManualDataMigrationRecord,
    "manual.config_management": ManualConfigManagementRecord,
    "manual.consistency_model": ManualConsistencyModelRecord,
    
    # ==================== ECS ====================
    "ecs.instance.list": EcsInstanceRecord,
    "ecs.security_group.list": EcsSecurityGroupRecord,
    "ecs.security_group_rule.list": EcsSecurityGroupRuleRecord,
    
    # ==================== Cloud Storage ====================
    "cloud.storage.product.list": CloudStorageProductRecord,
    "cloud.storage.summary": CloudStorageSummaryRecord,
    "cloud.storage.products": CloudStorageProductRecord,
    "rds.instance.mode.list": RdsInstanceModeRecord,
    "tair.instance.mode.list": TairInstanceModeRecord,
    "rds.instance.mode": RdsInstanceModeRecord,
    "tair.instance.mode": TairInstanceModeRecord,
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
