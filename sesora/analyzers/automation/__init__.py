"""
Automation 维度分析器

包含：
- CI/CD 流水线
- 基础设施即代码 (IaC)
- 运维自动化
- GitOps
"""

from .cicd import CICD_ANALYZERS
from .iac import IAC_ANALYZERS
from .ops import OPS_ANALYZERS
from .gitops import GITOPS_ANALYZERS

# 导出所有 Automation 维度的分析器
AUTOMATION_ANALYZERS = (
    CICD_ANALYZERS +
    IAC_ANALYZERS +
    OPS_ANALYZERS +
    GITOPS_ANALYZERS
)

__all__ = [
    "AUTOMATION_ANALYZERS",
    "CICD_ANALYZERS",
    "IAC_ANALYZERS",
    "OPS_ANALYZERS",
    "GITOPS_ANALYZERS",
]
