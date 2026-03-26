"""
K8s 相关 DataItem Record 类型定义
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal, Optional


# ==================== K8s 工作负载 ====================

@dataclass
class K8sDeploymentRecord:
    """K8s Deployment 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.deployment.list"
    namespace: str
    name: str
    replicas: int
    ready_replicas: int
    labels: dict[str, str] = field(default_factory=dict)
    node_selector: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    strategy: str = ""  # RollingUpdate/Recreate
    max_surge: Optional[str] = None
    max_unavailable: Optional[str] = None


@dataclass
class K8sStatefulSetRecord:
    """K8s StatefulSet 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.statefulset.list"
    namespace: str
    name: str
    replicas: int
    ready_replicas: int
    service_name: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    volume_claim_templates: list[dict] = field(default_factory=list)


@dataclass
class ContainerProbeConfig:
    """容器探针配置"""
    probe_type: str  # httpGet/tcpSocket/exec/grpc
    path: str = ""  # httpGet 路径
    port: str = ""  # 可以是端口号或端口名称（如 'http-port'）
    initial_delay_seconds: int = 0
    period_seconds: int = 10
    timeout_seconds: int = 1
    success_threshold: int = 1
    failure_threshold: int = 3


@dataclass
class K8sPodRecord:
    """K8s Pod 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.pod.list"
    namespace: str
    name: str
    status: str  # Running/Pending/Succeeded/Failed/Unknown
    node_name: str = ""
    restart_count: int = 0
    labels: dict[str, str] = field(default_factory=dict)
    containers: list[dict] = field(default_factory=list)
    creation_timestamp: Optional[datetime] = None
    # QoS 类别
    qos_class: str = ""  # Guaranteed/Burstable/BestEffort
    # 资源配置
    resource_requests: dict = field(default_factory=dict)  # {cpu: "100m", memory: "128Mi"}
    resource_limits: dict = field(default_factory=dict)
    # 调度配置
    node_selector: dict[str, str] = field(default_factory=dict)  # nodeSelector 指定节点
    affinity: dict = field(default_factory=dict)  # 亲和性/反亲和性配置


@dataclass
class K8sPodProbesRecord:
    """K8s Pod 探针配置记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.pod.probes"
    namespace: str
    pod_name: str
    container_name: str
    liveness_probe: Optional[ContainerProbeConfig] = None
    readiness_probe: Optional[ContainerProbeConfig] = None
    startup_probe: Optional[ContainerProbeConfig] = None


@dataclass
class K8sCronJobRecord:
    """K8s CronJob 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.cronjob.list"
    namespace: str
    name: str
    schedule: str
    suspend: bool = False
    concurrency_policy: str = "Allow"  # Allow/Forbid/Replace
    successful_job_history_limit: int = 3
    failed_job_history_limit: int = 1
    last_schedule_time: Optional[datetime] = None
    last_successful_time: Optional[datetime] = None


# ==================== K8s 自动伸缩 ====================

TargetType = Literal["Utilization", "AverageValue", "Value"]


@dataclass
class MetricTarget:
    """指标目标值定义"""
    type: TargetType
    value: Optional[int] = None  # 用于 AverageValue 或 Value (整数或百分比)
    average_value: Optional[float] = None  # 用于 AverageValue (浮点数)

    def __str__(self):
        if self.type == "Utilization":
            return f"{self.value}%"
        elif self.type == "AverageValue":
            return f"avg={self.average_value or self.value}"
        else:
            return f"value={self.value}"


@dataclass
class LabelSelector:
    """标签选择器 (用于 Pods/External 指标过滤)"""
    match_labels: Optional[dict[str, str]] = None
    match_expressions: Optional[list[dict[str, Any]]] = None


@dataclass
class MetricIdentifier:
    """指标标识符 (名称 + 选择器)"""
    name: str
    selector: Optional[LabelSelector] = None


@dataclass
class ObjectReference:
    """被监控的对象引用 (用于 Object 类型指标，如 Ingress QPS)"""
    kind: str
    name: str
    api_version: Optional[str] = None


@dataclass
class HpaMetric:
    """
    HPA 指标定义 (结构化版本)
    根据 type 不同，只有对应的字段会有值，其他为 None
    """
    type: Literal["Resource", "Pods", "Object", "External"]
    target: MetricTarget

    # --- 互斥字段，根据 type 填充 ---

    # 1. Resource 类型 (CPU/Memory)
    resource_name: Optional[str] = None  # e.g., "cpu", "memory"

    # 2. Pods 类型 (每个 Pod 的指标，如 requests_per_second)
    pods_metric: Optional[MetricIdentifier] = None

    # 3. Object 类型 (描述某个对象的指标，如 Ingress 的 qps)
    object_metric: Optional[MetricIdentifier] = None
    object_target: Optional[ObjectReference] = None

    # 4. External 类型 (全局指标，如 SQS Queue Length)
    external_metric: Optional[MetricIdentifier] = None

    # --- 辅助方法：获取统一的指标名称 (用于展示) ---
    @property
    def display_name(self) -> str:
        if self.type == "Resource":
            return self.resource_name or "unknown-resource"
        elif self.type == "Pods" and self.pods_metric:
            return self.pods_metric.name
        elif self.type == "Object" and self.object_metric:
            return self.object_metric.name
        elif self.type == "External" and self.external_metric:
            return self.external_metric.name
        return "unknown"

    # --- 辅助方法：获取选择器 (用于高级分析) ---
    @property
    def selector(self) -> Optional[LabelSelector]:
        if self.type == "Pods" and self.pods_metric:
            return self.pods_metric.selector
        if self.type == "External" and self.external_metric:
            return self.external_metric.selector
        return None


@dataclass
class K8sHpaRecord:
    """K8s HPA 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.hpa.list"
    namespace: str
    name: str
    min_replicas: int
    max_replicas: int
    current_replicas: int
    target_kind: str  # Deployment/StatefulSet
    target_name: str
    metrics: list[HpaMetric] = field(default_factory=list)


@dataclass
class K8sVpaRecord:
    """K8s VPA 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.vpa.list"
    namespace: str
    name: str
    target_kind: str
    target_name: str
    update_mode: str  # Off/Initial/Recreate/Auto
    # 受控资源列表，例如: ["cpu", "memory"]
    # 如果为 None 或空列表，通常表示默认监控所有资源 (cpu + memory)
    controlled_resources: Optional[list[str]] = field(default_factory=list)
    recommendation: dict = field(default_factory=dict)
    # VPA UpdatePolicy 配置
    min_replicas: Optional[int] = None  # 最小副本数保护（Recreate 模式下确保至少保留的副本数）


@dataclass
class K8sAhpaMetricsRecord:
    """K8s AHPA (Advanced Horizontal Pod Autoscaler) 指标记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.ahpa.metrics"
    namespace: str
    name: str
    prediction_enabled: bool = False
    prediction_config: dict = field(default_factory=dict)
    mode: str = "Active" # Active/Observer


# ==================== K8s 网络 ====================

@dataclass
class K8sServiceRecord:
    """K8s Service 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.service.list"
    namespace: str
    name: str
    type: str  # ClusterIP/NodePort/LoadBalancer/ExternalName
    cluster_ip: str = ""
    external_ips: list[str] = field(default_factory=list)
    ports: list[dict] = field(default_factory=list)
    selector: dict[str, str] = field(default_factory=dict)


@dataclass
class K8sIngressRecord:
    """K8s Ingress 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.ingress.list"
    namespace: str
    name: str
    rules: list[dict] = field(default_factory=list)
    tls: list[dict] = field(default_factory=list)
    ingress_class: str = ""
    tls_enabled: bool = False  # 是否启用 TLS
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class K8sNetworkPolicyRecord:
    """K8s NetworkPolicy 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.networkpolicy.list"
    namespace: str
    name: str
    pod_selector: dict = field(default_factory=dict)
    policy_types: list[str] = field(default_factory=list)
    ingress_rules: list[dict] = field(default_factory=list)
    egress_rules: list[dict] = field(default_factory=list)


# ==================== K8s 基础资源 ====================

@dataclass
class K8sNamespaceRecord:
    """K8s Namespace 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.namespace.list"
    name: str
    status: str = "Active"
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    creation_timestamp: Optional[datetime] = None


@dataclass
class K8sNodeRecord:
    """K8s Node 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.node.list"
    name: str
    status: str
    capacity: dict[str, str] = field(default_factory=dict)
    allocatable: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    taints: list[dict] = field(default_factory=list)  # [{key, value, effect}]
    zone: str = ""
    region: str = ""
    instance_type: str = ""


@dataclass
class K8sResourceQuotaRecord:
    """K8s ResourceQuota 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.resourcequota.list"
    namespace: str
    name: str
    hard: dict[str, str] = field(default_factory=dict)
    used: dict[str, str] = field(default_factory=dict)


@dataclass
class K8sPvRecord:
    """K8s PersistentVolume 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.pv.list"
    name: str
    capacity: str
    access_modes: list[str] = field(default_factory=list)
    reclaim_policy: str = ""  # Retain/Recycle/Delete
    status: str = ""
    storage_class: str = ""


# ==================== K8s 事件/日志 ====================

@dataclass
class K8sEventRecord:
    """K8s Event 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.event.list"
    namespace: str
    name: str
    reason: str
    message: str
    type: str  # Normal/Warning
    count: int = 1
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    involved_object: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)


@dataclass
class K8sAuditLogRecord:
    """K8s 审计日志记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.audit_log.recent"
    timestamp: datetime
    verb: str  # create/update/delete/patch/get/list/watch
    resource: str
    namespace: str
    name: str
    user: str
    response_status: int = 200
    request_uri: str = ""
    source_ips: list[str] = field(default_factory=list)


# ==================== 服务网格 ====================

@dataclass
class IstioDestinationRuleRecord:
    """Istio DestinationRule 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.istio.destination_rule.list"
    namespace: str
    name: str
    host: str
    traffic_policy: dict = field(default_factory=dict)
    subsets: list[dict] = field(default_factory=list)


@dataclass
class IstioVirtualServiceRecord:
    """Istio VirtualService 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.istio.virtual_service.list"
    namespace: str
    name: str
    hosts: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    http_routes: list[dict] = field(default_factory=list)
    tcp_routes: list[dict] = field(default_factory=list)


# ==================== GitOps ====================

@dataclass
class ArgoCdApplicationRecord:
    """ArgoCD Application 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.argocd.app.list"
    name: str
    namespace: str = "argocd"
    repo_url: str = ""
    target_revision: str = "HEAD"
    path: str = ""
    destination_server: str = ""
    destination_namespace: str = ""
    sync_status: str = ""  # Synced/OutOfSync/Unknown
    health_status: str = ""  # Healthy/Progressing/Degraded/Suspended/Missing/Unknown
    sync_policy: dict = field(default_factory=dict)
    auto_sync: bool = False
    auto_sync_enabled: bool = False
    auto_prune_enabled: bool = False
    self_heal_enabled: bool = False


# Alias for ArgoAppRecord
ArgoAppRecord = ArgoCdApplicationRecord


@dataclass
class IstioGatewayRecord:
    """Istio Gateway 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.istio.gateway.list"
    namespace: str
    name: str
    servers: list[dict] = field(default_factory=list)
    selector: dict[str, str] = field(default_factory=dict)


@dataclass
class FluxKustomizationRecord:
    """Flux Kustomization 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.flux.kustomization.list"
    namespace: str
    name: str
    source_ref: dict = field(default_factory=dict)
    path: str = "./"
    interval: str = "10m"
    prune: bool = False
    ready: bool = False
    status_conditions: list[dict] = field(default_factory=list)


# ==================== 策略引擎 ====================

# TODO: Remove this, use policy.py instead
@dataclass
class K8sGatekeeperConstraintRecord:
    """OPA Gatekeeper Constraint 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.gatekeeper.constraint.list"
    namespace: str
    name: str
    kind: str  # Constraint 类型
    enforcement_action: str = "deny"  # deny/dryrun/warn
    match: dict = field(default_factory=dict)  # 匹配规则
    parameters: dict = field(default_factory=dict)
    violations_count: int = 0
    status: str = ""  # Synced/NotSynced


# TODO: Remove this, use policy.py instead
@dataclass
class K8sKyvernoPolicyRecord:
    """Kyverno Policy 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.kyverno.policy.native.list"
    namespace: str
    name: str
    policy_type: str = "ClusterPolicy"  # Policy/ClusterPolicy
    validation_failure_action: str = "enforce"  # enforce/audit
    background: bool = True
    rules: list[dict] = field(default_factory=list)
    ready: bool = False
    message: str = ""
