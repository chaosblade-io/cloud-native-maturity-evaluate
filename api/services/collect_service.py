"""
采集服务

封装数据采集逻辑，使用 subprocess 调用采集脚本避免 signal 问题
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from api.models.schemas import CollectorInfo, CollectResult

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 采集脚本路径
COLLECTOR_SCRIPT = PROJECT_ROOT / "run_pipeline" / "run_one_collector.py"


class CollectService:
    """采集服务类"""
    
    # 数据库路径
    DB_DIR = PROJECT_ROOT / "data"
    DEFAULT_DB = DB_DIR / "sesora.db"
    
    # 可用采集器定义
    COLLECTORS = [
        {
            "name": "codeup",
            "label": "云效 Codeup",
            "description": "采集云效代码仓库和流水线数据",
            "requires_config": ["YUNXIAO_TOKEN", "CODEUP_ORG_ID"],
        },
        {
            "name": "fc",
            "label": "函数计算 FC",
            "description": "采集函数计算函数和版本数据",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "ack",
            "label": "ACK 容器服务",
            "description": "采集 Kubernetes 集群资源数据",
            "requires_config": ["ACK_CLUSTER_ID"],
        },
        {
            "name": "sls",
            "label": "SLS 日志服务",
            "description": "采集日志服务配置和日志样本",
            "requires_config": ["SLS_PROJECT"],
        },
        {
            "name": "rds",
            "label": "RDS 数据库",
            "description": "采集 RDS 实例和备份策略",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "cms",
            "label": "CMS 云监控",
            "description": "采集云监控告警规则和联系人",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "ros",
            "label": "ROS 资源编排",
            "description": "采集资源编排栈信息",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "oss",
            "label": "OSS 对象存储",
            "description": "采集 OSS Bucket 和生命周期配置",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "arms",
            "label": "ARMS APM",
            "description": "采集应用性能监控数据",
            "requires_config": ["ARMS_WORKSPACE_ID"],
        },
        {
            "name": "acr",
            "label": "ACR 容器镜像",
            "description": "采集容器镜像仓库和扫描结果",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "alb",
            "label": "ALB 负载均衡",
            "description": "采集应用负载均衡监听器配置",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "ecs",
            "label": "ECS 云服务器",
            "description": "采集 ECS 实例和安全组配置",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "eventbridge",
            "label": "EventBridge",
            "description": "采集事件总线和规则配置",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
        {
            "name": "grafana",
            "label": "Grafana",
            "description": "采集 Grafana 仪表盘配置",
            "requires_config": ["GRAFANA_API_TOKEN"],
        },
        {
            "name": "gtm",
            "label": "GTM 流量管理",
            "description": "采集全局流量管理配置",
            "requires_config": ["GTM_INSTANCE_ID"],
        },
        {
            "name": "tair",
            "label": "Tair/Redis",
            "description": "采集 Tair/Redis 实例配置",
            "requires_config": ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
        },
    ]
    
    @classmethod
    def get_available_collectors(cls) -> list[CollectorInfo]:
        """获取所有可用的采集器列表"""
        return [
            CollectorInfo(
                name=c["name"],
                label=c["label"],
                description=c["description"],
                requires_config=c["requires_config"],
            )
            for c in cls.COLLECTORS
        ]
    
    @classmethod
    def run_collection(
        cls,
        collectors: list[str] = None,
    ) -> list[CollectResult]:
        """
        执行数据采集（使用 subprocess 调用独立脚本）
        
        Args:
            collectors: 要执行的采集器名称列表，None 表示全部
            
        Returns:
            采集结果列表
        """
        # 确定要执行的采集器
        all_names = [c["name"] for c in cls.COLLECTORS]
        if not collectors:
            collectors = all_names
        
        results = []
        
        for name in collectors:
            if name not in all_names:
                results.append(CollectResult(
                    collector=name,
                    success=False,
                    message=f"未知的采集器: {name}",
                    elapsed_seconds=0,
                ))
                continue
            
            try:
                # 使用 subprocess 调用采集脚本，继承当前环境变量
                result = subprocess.run(
                    [sys.executable, str(COLLECTOR_SCRIPT), name],
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 分钟超时
                    cwd=str(PROJECT_ROOT),
                    env=os.environ.copy(),  # 继承环境变量
                )
                
                # 解析 JSON 输出
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()
                
                if result.returncode == 0 and stdout:
                    # 尝试从 stdout 的第一行或最后一行找到 JSON
                    json_data = None
                    lines = stdout.split('\n')
                    
                    # 先尝试第一行（JSON 可能在开头）
                    for line in lines:
                        line = line.strip()
                        if line.startswith('{') and line.endswith('}'):
                            try:
                                json_data = json.loads(line)
                                break
                            except json.JSONDecodeError:
                                continue
                    
                    if json_data:
                        results.append(CollectResult(
                            collector=name,
                            success=json_data.get("success", False),
                            message=json_data.get("message", "采集完成"),
                            elapsed_seconds=json_data.get("elapsed_seconds", 0),
                        ))
                    else:
                        # 找不到 JSON，尝试解析整个 stdout
                        try:
                            data = json.loads(stdout)
                            results.append(CollectResult(
                                collector=name,
                                success=data.get("success", False),
                                message=data.get("message", "采集完成"),
                                elapsed_seconds=data.get("elapsed_seconds", 0),
                            ))
                        except json.JSONDecodeError:
                            results.append(CollectResult(
                                collector=name,
                                success=False,
                                message=f"JSON解析失败: {stdout[:200]}",
                                elapsed_seconds=0,
                            ))
                else:
                    # 输出错误信息
                    error_msg = stderr if stderr else (stdout if stdout else "采集返回空")
                    results.append(CollectResult(
                        collector=name,
                        success=False,
                        message=f"采集失败(code={result.returncode}): {error_msg[:300]}",
                        elapsed_seconds=0,
                    ))
                    
            except subprocess.TimeoutExpired:
                results.append(CollectResult(
                    collector=name,
                    success=False,
                    message="采集超时 (>5分钟)",
                    elapsed_seconds=300,
                ))
            except json.JSONDecodeError as e:
                results.append(CollectResult(
                    collector=name,
                    success=False,
                    message=f"结果解析失败: {str(e)}",
                    elapsed_seconds=0,
                ))
            except Exception as e:
                results.append(CollectResult(
                    collector=name,
                    success=False,
                    message=f"采集异常: {str(e)}",
                    elapsed_seconds=0,
                ))
        
        return results
