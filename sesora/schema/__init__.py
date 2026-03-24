"""
Schema 模块

定义所有 DataItem 对应的强类型 Record 结构
作为采集层与评分层之间的数据契约
"""

from .k8s import *
from .apm import *
from .cms import *
from .sls import *
from .codeup import *
from .fc import *
from .eventbridge import *
from .rds_oss import *
from .acr import *
from .chaos import *
from .policy import *
from .grafana import *
from .manual import *
from .cloud_storage import *
from .ros import *
from .ecs import *
from .registry import DATAITEM_SCHEMA_REGISTRY, get_record_type, register_record_type

__all__ = [
    # Registry
    "DATAITEM_SCHEMA_REGISTRY",
    "get_record_type",
    "register_record_type",
    
    # ==================== K8s ====================
    "K8sDeploymentRecord",
    "K8sStatefulSetRecord",
    "K8sPodRecord",
    "K8sPodProbesRecord",
    "ContainerProbeConfig",
    "K8sHpaRecord",
    "K8sVpaRecord",
    "K8sNamespaceRecord",
    "K8sNodeRecord",
    "K8sServiceRecord",
    "K8sIngressRecord",
    "K8sCronJobRecord",
    "K8sEventRecord",
    "K8sResourceQuotaRecord",
    "K8sPvRecord",
    "K8sNetworkPolicyRecord",
    "K8sAuditLogRecord",
    "HpaMetric",
    # Istio
    "IstioDestinationRuleRecord",
    "IstioVirtualServiceRecord",
    "IstioGatewayRecord",
    # ArgoCD/GitOps
    "ArgoCdApplicationRecord",
    "ArgoAppRecord",
    "FluxKustomizationRecord",
    # Policy Engines
    "K8sGatekeeperConstraintRecord",
    "K8sKyvernoPolicyRecord",
    
    # ==================== APM ====================
    "ApmServiceRecord",
    "ApmTraceRecord",
    "ApmServiceDependencyRecord",
    "ApmTopologyMetricsRecord",
    "ApmExternalDatabaseRecord",
    "ApmExternalMessageRecord",
    "ApmServiceDbMappingRecord",
    "ApmCoverageAnalysisRecord",
    
    # ==================== CMS ====================
    "CmsAlarmRuleRecord",
    "CmsContactRecord",
    "CmsContactGroupRecord",
    "CmsAlarmSloRecord",
    "CmsAlarmChannelSummaryRecord",
    "CmsEventTriggerRecord",
    "CmsAlarmHistoryRecord",
    
    # ==================== SLS ====================
    "SlsLogstoreRecord",
    "SlsLogSampleRecord",
    "SlsLogStructureAnalysisRecord",
    "SlsIndexConfigRecord",
    "SlsQueryCapabilityRecord",
    "SlsArchiveConfigRecord",
    
    # ==================== Codeup ====================
    "CodeupPipelineRecord",
    "CodeupRepoRecord",
    "CodeupPipelineMetricsRecord",
    "CodeupPipelineRunRecord",
    "CodeupRepoFileTreeRecord",
    "CodeupCommitRecord",
    "CodeupPipelineConfigRecord",
    "CodeupPipelineStageRecord",
    "CodeupRepoTagRecord",
    "CodeupBranchRecord",
    "CodeupFileCommitRecord",
    
    # ==================== FC ====================
    "FcFunctionRecord",
    "FcAliasRecord",
    "FcVersionRecord",
    "FcColdStartMetricRecord",
    "FcProvisionedConcurrencyRecord",
    "FcObservabilityConfigRecord",
    "FcUsageSummaryRecord",
    
    # ==================== EventBridge ====================
    "EventBridgeEventSourceRecord",
    "EventBridgeEventBusRecord",
    "EbEventBusRecord",
    "EbEventRuleRecord",
    "EbEventTargetRecord",
    "EventBridgeSchemaRecord",
    "RocketMqTopicRecord",
    
    # ==================== RDS/OSS ====================
    "RdsInstanceRecord",
    "OssBucketRecord",
    "RdsBackupPolicyRecord",
    "OssBucketLifecycleRecord",
    "RdsDbProxyConfigRecord",
    "RosStackRecord",
    "AlbListenerRecord",
    "GtmAddressPoolRecord",
    
    # ==================== ACR ====================
    "AcrRepositoryRecord",
    "AcrImageRecord",
    "AcrScanResultRecord",
    "AcrImageScanResultRecord",
    
    # ==================== Chaos Engineering ====================
    "ChaosExperimentRecord",
    "ChaosExperimentRunRecord",
    "ChaosScheduleRecord",
    "ChaosWorkflowRecord",
    
    # ==================== Policy as Code ====================
    "KyvernoPolicyRecord",
    "KyvernoPolicyViolationRecord",
    "OpaConstraintTemplateRecord",
    "OpaConstraintRecord",
    "OpaViolationRecord",
    "PolicyEnforcementSummaryRecord",
    
    # ==================== Grafana ====================
    "GrafanaDashboardRecord",
    "GrafanaFolderRecord",
    "GrafanaPanelRecord",
    "GrafanaAlertRuleRecord",
    "GrafanaDashboardAnalysisRecord",
    "MetricIntervalRecord",
    
    # ==================== Manual/Questionnaire ====================
    "ManualQuestionnaireRecord",
    "ManualFallbackConfigRecord",
    "ManualBulkheadConfigRecord",
    "ManualDrPlanRecord",
    "ManualRtoRpoRecord",
    "ManualDrTestingRecord",
    "ManualDataConsistencyRecord",
    "ManualDataOwnershipRecord",
    "ManualDataMigrationRecord",
    "ManualConfigManagementRecord",
    
    # ==================== Cloud Storage ====================
    "CloudStorageProductRecord",
    "CloudStorageSummaryRecord",
    "RdsInstanceModeRecord",
    "TairInstanceModeRecord",
    
    # ==================== ROS ====================
    "RosStackRecord",
    "RosStackDriftRecord",
    
    # ==================== ECS ====================
    "EcsInstanceRecord",
    "EcsSecurityGroupRecord",
    "EcsSecurityGroupRuleRecord",
]
