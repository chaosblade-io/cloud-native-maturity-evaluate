"""
配置服务

封装 .env 文件的读写操作
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

from api.models.schemas import ConfigData, ConfigGroup, ConfigItem


class ConfigService:
    """配置服务类"""
    
    # 项目根目录
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    ENV_FILE = PROJECT_ROOT / ".env"
    ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"
    
    # 配置分组定义
    CONFIG_GROUPS = [
        {
            "name": "阿里云基础凭证",
            "description": "阿里云账号的基础认证信息",
            "items": [
                {"key": "ALIBABA_CLOUD_ACCESS_KEY_ID", "description": "阿里云 AccessKey ID", "required": True},
                {"key": "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "description": "阿里云 AccessKey Secret", "required": True},
                {"key": "ALIBABA_CLOUD_ACCOUNT_ID", "description": "阿里云账号 ID（可选）"},
                {"key": "ALIBABA_CLOUD_SECURITY_TOKEN", "description": "STS 临时凭证 Token（可选）"},
                {"key": "ALIBABA_CLOUD_REGION", "description": "阿里云默认区域", "default": "cn-hongkong"},
            ]
        },
        {
            "name": "ACK 容器服务",
            "description": "ACK Kubernetes 集群配置",
            "items": [
                {"key": "ACK_CLUSTER_ID", "description": "ACK 集群 ID"},
                {"key": "ACK_NAMESPACES", "description": "目标命名空间列表（JSON格式或逗号分隔）"},
                {"key": "KUBECONFIG_PATHS", "description": "多个 kubeconfig 文件路径"},
                {"key": "KUBECONFIG_CONTEXT", "description": "kubeconfig 上下文名称"},
            ]
        },
        {
            "name": "ARMS APM",
            "description": "ARMS 应用性能监控配置",
            "items": [
                {"key": "ARMS_WORKSPACE_ID", "description": "ARMS 工作空间 ID"},
            ]
        },
        {
            "name": "ROS 资源编排",
            "description": "ROS 资源编排服务配置",
            "items": [
                {"key": "ROS_STACK_NAME", "description": "资源栈名称列表（JSON格式）"},
                {"key": "ROS_REGION", "description": "ROS 所在区域"},
            ]
        },
        {
            "name": "SLS 日志服务",
            "description": "SLS 日志服务配置",
            "items": [
                {"key": "SLS_PROJECT", "description": "SLS Project 名称"},
                {"key": "SLS_LOGSTORES", "description": "SLS Logstore 列表"},
                {"key": "SLS_REGION", "description": "SLS 所在区域"},
            ]
        },
        {
            "name": "云效 Codeup",
            "description": "云效代码托管和流水线配置",
            "items": [
                {"key": "YUNXIAO_TOKEN", "description": "云效个人访问令牌"},
                {"key": "CODEUP_ORG_ID", "description": "云效组织 ID"},
                {"key": "CODEUP_REPO_IDS", "description": "仓库 ID 列表"},
                {"key": "CODEUP_PIPELINE_IDS", "description": "流水线 ID 列表"},
                {"key": "CODEUP_PROJECT_NAME", "description": "Codeup 项目名称"},
            ]
        },
        {
            "name": "函数计算 FC",
            "description": "函数计算配置",
            "items": [
                {"key": "FC_FUNCTION_NAMES", "description": "函数名称列表"},
            ]
        },
        {
            "name": "EventBridge",
            "description": "事件总线配置",
            "items": [
                {"key": "EVENTBRIDGE_BUS_NAMES", "description": "EventBridge 总线名称列表"},
            ]
        },
        {
            "name": "RDS 数据库",
            "description": "RDS 数据库配置",
            "items": [
                {"key": "RDS_INSTANCE_IDS", "description": "RDS 实例 ID 列表"},
                {"key": "RDS_REGION", "description": "RDS 所在区域"},
            ]
        },
        {
            "name": "OSS 对象存储",
            "description": "OSS 对象存储配置",
            "items": [
                {"key": "OSS_BUCKET_NAMES", "description": "OSS Bucket 名称列表"},
                {"key": "OSS_REGION", "description": "OSS 所在区域"},
            ]
        },
        {
            "name": "ACR 容器镜像",
            "description": "ACR 容器镜像服务配置",
            "items": [
                {"key": "ACR_INSTANCE_IDS", "description": "ACR 实例 ID 列表"},
                {"key": "ACR_OTEL_ONLY", "description": "仅采集 Otel 相关镜像", "default": "true"},
            ]
        },
        {
            "name": "ALB 负载均衡",
            "description": "ALB 应用负载均衡配置",
            "items": [
                {"key": "ALB_LOAD_BALANCER_IDS", "description": "ALB 负载均衡器 ID 列表"},
            ]
        },
        {
            "name": "ECS 云服务器",
            "description": "ECS 云服务器配置",
            "items": [
                {"key": "ECS_REGION", "description": "ECS 所在区域"},
            ]
        },
        {
            "name": "GTM 全局流量管理",
            "description": "GTM 全局流量管理配置",
            "items": [
                {"key": "GTM_INSTANCE_ID", "description": "GTM 实例 ID"},
            ]
        },
        {
            "name": "Grafana",
            "description": "Grafana 仪表盘配置",
            "items": [
                {"key": "GRAFANA_WORKSPACE_ID", "description": "Grafana 工作空间 ID（阿里云 ARMS）"},
                {"key": "GRAFANA_URL", "description": "Grafana URL（自建/第三方）"},
                {"key": "GRAFANA_API_TOKEN", "description": "Grafana API Token"},
                {"key": "GRAFANA_FOLDER_IDS", "description": "指定采集的文件夹 ID 列表"},
                {"key": "GRAFANA_TAGS", "description": "指定采集的标签列表"},
            ]
        },
        {
            "name": "Tair/Redis",
            "description": "Tair/Redis 缓存配置",
            "items": [
                {"key": "TAIR_INSTANCE_IDS", "description": "Tair/Redis 实例 ID 列表"},
            ]
        },
    ]
    
    @classmethod
    def config_exists(cls) -> bool:
        """检查配置文件是否存在"""
        return cls.ENV_FILE.exists()
    
    @classmethod
    def has_credentials(cls) -> bool:
        """检查是否配置了阿里云凭证"""
        if not cls.config_exists():
            return False
        
        config = cls.load_config()
        return bool(
            config.ALIBABA_CLOUD_ACCESS_KEY_ID and 
            config.ALIBABA_CLOUD_ACCESS_KEY_SECRET
        )
    
    @classmethod
    def load_config(cls) -> ConfigData:
        """
        加载配置文件
        
        Returns:
            ConfigData 对象
        """
        config_dict = {}
        
        # 如果存在 .env 文件，读取配置
        if cls.ENV_FILE.exists():
            config_dict = dotenv_values(cls.ENV_FILE)
        
        # 创建 ConfigData 对象，使用读取到的值或默认值
        config = ConfigData()
        for field_name in ConfigData.model_fields:
            if field_name in config_dict and config_dict[field_name]:
                setattr(config, field_name, config_dict[field_name])
        
        return config
    
    @classmethod
    def save_config(cls, config: ConfigData) -> None:
        """
        保存配置到 .env 文件
        
        Args:
            config: ConfigData 对象
        """
        lines = [
            "# SESORA 环境变量配置",
            "# 由 Web 管理界面自动生成",
            "",
        ]
        
        # 按分组写入配置
        for group in cls.CONFIG_GROUPS:
            lines.append(f"# {'=' * 44}")
            lines.append(f"# {group['name']}")
            lines.append(f"# {'=' * 44}")
            
            for item in group["items"]:
                key = item["key"]
                value = getattr(config, key, "")
                lines.append(f"{key}={value}")
            
            lines.append("")
        
        # 写入文件
        cls.ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
        
        # 重新加载环境变量
        cls._reload_env()
    
    @classmethod
    def _reload_env(cls) -> None:
        """重新加载环境变量到当前进程"""
        if cls.ENV_FILE.exists():
            config_dict = dotenv_values(cls.ENV_FILE)
            for key, value in config_dict.items():
                if value:
                    os.environ[key] = value
    
    @classmethod
    def get_config_groups(cls, config: ConfigData) -> list[ConfigGroup]:
        """
        获取配置分组（带当前值）
        
        Args:
            config: 当前配置
            
        Returns:
            配置分组列表
        """
        groups = []
        
        for group_def in cls.CONFIG_GROUPS:
            items = []
            for item_def in group_def["items"]:
                key = item_def["key"]
                value = getattr(config, key, "")
                items.append(ConfigItem(
                    key=key,
                    value=value,
                    description=item_def.get("description", ""),
                    required=item_def.get("required", False),
                    group=group_def["name"],
                ))
            
            groups.append(ConfigGroup(
                name=group_def["name"],
                description=group_def.get("description", ""),
                items=items,
            ))
        
        return groups
    
    @classmethod
    def parse_env_content(cls, content: str) -> ConfigData:
        """
        解析 .env 文件内容
        
        Args:
            content: .env 文件的文本内容
            
        Returns:
            ConfigData 对象
        """
        config_dict = {}
        
        for line in content.splitlines():
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue
            
            # 解析 key=value 格式
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                
                # 去除引号
                if value and len(value) >= 2:
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                
                config_dict[key] = value
        
        # 创建 ConfigData 对象
        config = ConfigData()
        for field_name in ConfigData.model_fields:
            if field_name in config_dict and config_dict[field_name]:
                setattr(config, field_name, config_dict[field_name])
        
        return config
