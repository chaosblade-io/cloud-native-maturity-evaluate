"""
AssessmentContext 定义：评估上下文
包含目标环境的连接信息和配置
"""
from dataclasses import dataclass, field
from typing import Optional
from alibabacloud_credentials.client import Client as CredentialClient

@dataclass
class AssessmentContext:
    """
    评估上下文
    
    用户指定目标环境上下文，系统依次执行三层流程。
    
    Attributes:
        region: 地域
        cluster_id: ACK 集群 ID
        namespaces: 目标命名空间列表，为空表示全部
        arms_workspace_id: ARMS 工作空间 ID
        sls_project: SLS 项目名称
        aliyun_credentials: 阿里云凭证
        codeup_org_id: 云效组织 ID
        codeup_repo_ids: 云效仓库 ID 列表
        sls_region: SLS 所在地域
    """
    # 基础信息
    region: str = ""
    cluster_id: str = ""
    namespaces: list[str] = field(default_factory=list)
    
    # ARMS/APM
    arms_workspace_id: str = ""

    # ROS
    ros_stack_name: list[str] = None  # 资源栈名称（可选）
    ros_region: str = ""  # 资源栈所在地域（可选）
    
    # SLS
    sls_project: str = ""
    sls_logstores: list[str] = field(default_factory=list)
    sls_region: str = ""
    
    # 云效 Codeup
    codeup_org_id: str = ""
    codeup_repo_ids: list[str] = field(default_factory=list)
    codeup_pipeline_ids: list[str] = field(default_factory=list)
    yunxiao_token: str = ""  # 云效个人访问令牌
    codeup_project_name: str = ""
    
    # 函数计算
    fc_function_names: list[str] = field(default_factory=list)
    
    # EventBridge
    eventbridge_bus_names: list[str] = field(default_factory=list)
    
    # RDS
    rds_instance_ids: list[str] = field(default_factory=list)
    rds_region: str = ""

    # OSS
    oss_bucket_names: list[str] = field(default_factory=list)
    oss_region: str = ""
    
    # ACR
    acr_instance_ids: list[str] = field(default_factory=list)  # 多个实例 ID 列表
    # Todo: 后续需要改成允许的镜像仓库列表
    otel_only: bool = True
    
    # ALB
    alb_load_balancer_ids: list[str] = field(default_factory=list)
    
    # GTM
    gtm_instance_id: str = ""
    
    # Grafana
    grafana_workspace_id: str = ""  # ARMS Grafana 工作空间 ID（阿里云）
    grafana_url: str = ""  # Grafana URL（自建/第三方）
    grafana_api_token: str = ""  # Grafana API Token
    grafana_folder_ids: list[int] = field(default_factory=list)  # 指定采集的文件夹 ID
    grafana_tags: list[str] = field(default_factory=list)  # 指定采集的标签
    
    # 凭证
    aliyun_credentials: Optional[CredentialClient] = None
    
    # K8s 配置
    kubeconfig_paths: list[str] = field(default_factory=list)  # 多 kubeconfig 路径
    kubeconfig_context: str = ""
    
    # ECS
    ecs_region: str = ""

    # Tair/Redis
    tair_instance_ids: list[str] = field(default_factory=list)
    
    def get_namespace_filter(self) -> list[str]:
        """获取命名空间过滤器，空列表表示不过滤"""
        return self.namespaces if self.namespaces else []
