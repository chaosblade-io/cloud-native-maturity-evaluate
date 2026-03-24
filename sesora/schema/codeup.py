"""
Codeup (云效代码仓库) 相关 DataItem Record 类型定义
数据来源：阿里云云效 Codeup/Flow
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class CodeupPipelineRecord:
    """Codeup 流水线记录"""
    pipeline_id: str
    name: str
    repo_id: str
    create_time: Optional[datetime] = None


@dataclass
class CodeupRepoRecord:
    """Codeup 仓库记录"""
    repo_id: str
    repo_name: str
    namespace: str = ""
    default_branch: str = "main"
    visibility: str = "private"
    create_time: Optional[datetime] = None


@dataclass
class CodeupPipelineMetricsRecord:
    """Codeup 流水线指标记录"""
    pipeline_id: str
    pipeline_name: str
    run_count_30d: int = 0
    success_count_30d: int = 0
    failure_count_30d: int = 0
    avg_duration_ms: int = 0
    success_rate: float = 0.0


@dataclass
class CodeupPipelineRunRecord:
    """Codeup 流水线运行记录"""
    pipeline_id: str
    pipeline_name: str
    run_id: str
    status: str  # SUCCESS/FAIL/RUNNING/CANCELED/TIMEOUT/WAITING etc.
    trigger_type: str = ""  # MANUAL/WEBHOOK/SCHEDULE/PUSH/PIPELINE
    trigger_user: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: int = 0


@dataclass
class CodeupRepoFileTreeRecord:
    """Codeup 仓库文件树记录"""
    repo_id: str
    repo_name: str
    path: str
    type: Literal["file", "directory"]
    name: str


@dataclass
class CodeupCommitRecord:
    """Codeup 提交记录"""
    repo_id: str
    commit_id: str
    message: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    author_time: Optional[datetime] = None
    committer_name: Optional[str] = None
    committer_email: Optional[str] = None
    commit_time: Optional[datetime] = None
    parent_ids: list[str] = field(default_factory=list)
    has_merge_request: bool = False  # 是否通过 MR 流程


@dataclass
class CodeupPipelineConfigRecord:
    """Codeup 流水线配置记录"""
    pipeline_id: str
    pipeline_name: str
    repo_id: str
    trigger_type: str = "manual"  # push/mr/tag/schedule/manual
    trigger_config: dict = field(default_factory=dict)  # push/merge_request/schedule
    auto_trigger_enabled: bool = False  # 是否自动触发
    env_vars: dict[str, str] = field(default_factory=dict)
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


@dataclass
class CodeupFileCommitRecord:
    """Codeup 文件最近提交记录"""
    repo_id: str
    file_path: str
    commit_id: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    commit_message: str = ""
    commit_time: Optional[datetime] = None
    has_merge_request: bool = False  # 是否通过 MR 流程


@dataclass
class CodeupPipelineStageRecord:
    """Codeup 流水线阶段记录"""
    pipeline_id: str
    stage_name: str
    stage_type: list[str]  # build/test/deploy/security_scan/manual_gate
    stage_order: int
    on_failure: str = "block"  # block/continue/manual，阿里云云效默认就是阻断的，只要不包括 allowFailure: true 或 onFailure: continue 就认定为是 block
    commands: list[str] = field(default_factory=list)
    has_test_step: bool = False  # 是否包含测试步骤
    has_deploy_step: bool = False  # 是否包含部署步骤
    has_manual_gate: bool = False  # 是否有人工审批
    has_security_scan: bool = False  # 是否有安全扫描


@dataclass
class CodeupRepoTagRecord:
    """Codeup 仓库标签记录"""
    repo_id: str
    tag_name: str
    commit_id: str
    message: str = ""
    is_semver: bool = False  # 是否符合 SemVer 规范
    create_time: Optional[datetime] = None
    created_by: str = ""


@dataclass
class CodeupBranchRecord:
    """Codeup 分支记录"""
    repo_id: str
    branch_name: str
    is_protected: bool = False
    commit_id: str = ""
    commit_time: Optional[datetime] = None
