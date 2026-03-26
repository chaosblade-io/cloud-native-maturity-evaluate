"""
Policy as Code (策略即代码) 相关 DataItem Record 类型定义
数据来源：ACK (Kyverno / OPA Gatekeeper)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal, Optional


@dataclass
class KyvernoPolicyRecord:
    """Kyverno 策略记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.kyverno.policy.list"
    name: str
    policy_type: str = "ClusterPolicy"  # ClusterPolicy/Policy
    namespace: str = ""  # 为空表示 ClusterPolicy
    background: bool = True  # 是否对已有资源生效
    validation_failure_action: str = "Audit"  # Audit/Enforce
    rules: list[dict] = field(default_factory=list)
    status: str = ""  # Ready/Not Ready
    violations_count: int = 0
    create_time: Optional[datetime] = None


@dataclass
class KyvernoPolicyViolationRecord:
    """Kyverno 策略违规记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.kyverno.violation.list"
    policy_name: str
    rule_name: str
    resource_kind: str
    resource_namespace: str
    resource_name: str
    message: str = ""
    action: str = ""  # Blocked/Warning
    timestamp: Optional[datetime] = None


@dataclass
class OpaConstraintTemplateRecord:
    """OPA Gatekeeper ConstraintTemplate 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.opa.constraint_template.list"
    name: str
    crd_kind: str  # 生成的 CRD 类型名称
    rego_code: str = ""  # Rego 策略代码
    targets: list[dict] = field(default_factory=list)
    status: str = ""
    create_time: Optional[datetime] = None


@dataclass
class OpaConstraintRecord:
    """OPA Gatekeeper Constraint 记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.opa.constraint.list"
    name: str
    constraint_kind: str  # 对应的 ConstraintTemplate kind
    enforcement_action: str = "deny"  # deny/dryrun/warn
    match: dict = field(default_factory=dict)  # 匹配规则
    parameters: dict = field(default_factory=dict)  # 策略参数
    violations_count: int = 0
    status: str = ""
    create_time: Optional[datetime] = None


@dataclass
class OpaViolationRecord:
    """OPA Gatekeeper 违规记录"""
    DATAITEM_NAME: ClassVar[str] = "k8s.opa.violation.list"
    constraint_name: str
    constraint_kind: str
    resource_kind: str
    resource_namespace: str
    resource_name: str
    message: str = ""
    enforcement_action: str = ""
    timestamp: Optional[datetime] = None
