#!/usr/bin/env python3
"""
Mock 数据采集器

从 JSON 文件读取 mock 数据，使用 MockCollector 转换为强类型 Record 对象，
并保存到 SQLite 数据库。

用于测试、演示或离线数据导入场景。

使用方式:
    # 使用默认 mock 数据文件
    python run_pipeline/collect_mock_data.py
    
    # 指定 mock 数据文件
    python run_pipeline/collect_mock_data.py --data mock_data.json
    
    # 指定输出数据库
    python run_pipeline/collect_mock_data.py --db test.db
    
    # 指定采集器名称
    python run_pipeline/collect_mock_data.py --name my_collector

Mock 数据文件格式:
    {
        "k8s.deployment.list": [
            {"namespace": "default", "name": "app-1", "replicas": 3},
            {"namespace": "default", "name": "app-2", "replicas": 2}
        ],
        "k8s.service.list": [
            {"namespace": "default", "name": "web-service", "type": "ClusterIP"}
        ],
        "codeup.pipeline.list": [
            {"pipeline_id": "1", "pipeline_name": "build-pipeline", "status": "RUNNING"}
        ]
    }
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sesora.collectors.generic_collector import GenericCollector
from sesora.core.dataitem import DataSource
from sesora.store.sqlite_store import SQLiteDataStore


# 定义 DataItem 类型映射（用于保存到数据库）
DATAITEM_TYPE_MAPPINGS = {
    # Codeup
    "codeup.repo.list": "codeup",
    "codeup.repo.file_tree": "codeup",
    "codeup.repo.tags": "codeup",
    "codeup.branch.list": "codeup",
    "codeup.commit.list": "codeup",
    "codeup.pipeline.list": "codeup",
    "codeup.pipeline.config": "codeup",
    "codeup.pipeline.stages": "codeup",
    "codeup.pipeline.runs": "codeup",
    "codeup.pipeline.metrics": "codeup",
    "codeup.file.commits": "codeup",
    # FC
    "fc.function.list": "fc",
    "fc.trigger.list": "fc",
    "fc.alias.list": "fc",
    "fc.version.list": "fc",
    "fc.usage.summary": "fc",
    "fc.cold_start_metrics": "fc",
    "fc.function.statistics": "fc",
    # K8s/ACK
    "k8s.node.list": "k8s",
    "k8s.namespace.list": "k8s",
    "k8s.deployment.list": "k8s",
    "k8s.statefulset.list": "k8s",
    "k8s.pod.list": "k8s",
    "k8s.pod.probes": "k8s",
    "k8s.cronjob.list": "k8s",
    "k8s.service.list": "k8s",
    "k8s.ingress.list": "k8s",
    "k8s.networkpolicy.list": "k8s",
    "k8s.event.list": "k8s",
    "k8s.hpa.list": "k8s",
    "k8s.vpa.list": "k8s",
    "k8s.ahpa.metrics": "k8s",
    "k8s.resourcequota.list": "k8s",
    "k8s.pv.list": "k8s",
    # K8s Istio/Service Mesh
    "k8s.istio.destination_rule.list": "k8s",
    "k8s.istio.virtual_service.list": "k8s",
    "k8s.istio.gateway.list": "k8s",
    # K8s GitOps
    "k8s.argocd.app.list": "k8s",
    # K8s Policy
    "k8s.gatekeeper.constraint.list": "k8s",
    "k8s.kyverno.policy.list": "k8s",
    # SLS
    "sls.logstore.list": "sls",
    "sls.log_sample.recent": "sls",
    "sls.log_structure_analysis": "sls",
    "sls.index_config.list": "sls",
    "sls.query.capability": "sls",
    "sls.archive_config.list": "sls",
    # RDS
    "rds.instance.list": "rds",
    "rds.backup_policy.list": "rds",
    "rds.proxy.list": "rds",
    "rds.db_proxy.config": "rds",
    # CMS
    "cms.alarm_contact.list": "cms",
    "cms.alarm_channel.summary": "cms",
    "cms.alarm_rule.list": "cms",
    "cms.contact_group.list": "cms",
    "cms.alarm.history": "cms",
    "cms.event_trigger.list": "cms",
    "cms.alarm_rule.slo_analysis": "cms",
    # ROS
    "ros.stack.list": "ros",
    "ros.stack.drift": "ros",
    # OSS
    "oss.bucket.list": "oss",
    "oss.bucket.lifecycle": "oss",
    # Cloud Storage
    "cloud.storage.products": "cloud_storage",
    # ARMS/APM
    "apm.service.list": "apm",
    "apm.trace.list": "apm",
    "apm.service.dependency": "apm",
    "apm.topology.metrics": "apm",
    "apm.external.database": "apm",
    "apm.external.message": "apm",
    "apm.trace.sampling.config": "apm",
    "apm.service.db.mapping": "apm",
    "apm.integration.config": "apm",
    "apm.coverage.analysis": "apm",
    "apm.sampling.config": "apm",
    # ACR
    "acr.repository.list": "acr",
    "acr.image.list": "acr",
    "acr.scan.result": "acr",
    # EventBridge
    "eventbridge.bus.list": "eventbridge",
    "eventbridge.source.list": "eventbridge",
    "eventbridge.schema.list": "eventbridge",
    "eventbridge.rule.list": "eventbridge",
    "eventbridge.target.list": "eventbridge",
    # Grafana
    "grafana.dashboard.list": "grafana",
    "grafana.folder.list": "grafana",
    "grafana.dashboard.analysis": "grafana",
    # GTM
    "gtm.address_pool.list": "gtm",
    # Chaos
    "chaos.experiment.list": "chaos",
    "chaos.experiment_run.list": "chaos",
    # Manual
    "manual.fallback.config": "manual",
    "manual.bulkhead.config": "manual",
    "manual.dr_plan": "manual",
    "manual.rto_rpo": "manual",
    "manual.dr_testing": "manual",
    "manual.data_consistency": "manual",
    "manual.data_ownership": "manual",
    "manual.data_migration": "manual",
    "manual.consistency_model": "manual",
}


def load_mock_data(data_path: Path) -> dict:
    """
    从 JSON 文件加载 mock 数据
    
    Args:
        data_path: JSON 文件路径
        
    Returns:
        Mock 数据字典
    """
    if not data_path.exists():
        print(f"错误: 数据文件不存在: {data_path}")
        sys.exit(1)
    
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not isinstance(data, dict):
        print("错误: 数据文件格式不正确，应为 JSON 对象")
        sys.exit(1)
    
    return data


def save_to_database(data_source: DataSource, db_path: Path) -> None:
    """
    将采集结果保存到数据库
    
    Args:
        data_source: 采集到的数据源
        db_path: 数据库文件路径
    """
    # 按 DataItem 名称分组记录
    grouped_records: dict[str, list] = {}
    
    for record in data_source.records:
        # 从 record 获取 DataItem 名称
        record_type = type(record).__name__
        # 反向查找 DataItem 名称
        dataitem_name = None
        for name, source_type in DATAITEM_TYPE_MAPPINGS.items():
            # 通过类型匹配确定 DataItem 名称
            if record.__class__.__name__ == name.split('.')[-1].replace('_', '').replace('.', '').title():
                # 简化匹配：直接使用记录类型名
                pass
        
        # 更简单的方法：直接从记录对象推断
        # 遍历所有已知的 DataItem 名称，找到匹配的
        from sesora.schema.registry import DATAITEM_SCHEMA_REGISTRY
        
        for item_name, record_class in DATAITEM_SCHEMA_REGISTRY.items():
            if isinstance(record, record_class):
                if item_name not in grouped_records:
                    grouped_records[item_name] = []
                grouped_records[item_name].append(record)
                break
    
    # 保存到数据库
    with SQLiteDataStore(db_path) as store:
        saved_count = 0
        
        for item_name, records in grouped_records.items():
            # 无论是否有记录，都保存 DataSource
            source = DataSource(
                collector=data_source.collector,
                collected_at=data_source.collected_at,
                status="ok",
                records=records,
            )
            store.put(item_name, source)
            if records:
                saved_count += len(records)
                print(f"  保存 {item_name}: {len(records)} 条记录")
            else:
                print(f"  保存 {item_name}: 0 条记录 (已标记采集)")
        
        print(f"\n总计保存 {saved_count} 条记录")


def create_sample_mock_data() -> dict:
    """
    创建示例 mock 数据
    
    Returns:
        示例 mock 数据字典
    """
    return {
        "k8s.deployment.list": [
            {
                "namespace": "default",
                "name": "otel-collector",
                "replicas": 3,
                "ready_replicas": 3,
                "strategy": "RollingUpdate",
                "max_surge": "25%",
                "max_unavailable": "1"
            },
            {
                "namespace": "default",
                "name": "otel-demo-frontend",
                "replicas": 2,
                "ready_replicas": 2,
                "strategy": "RollingUpdate"
            },
            {
                "namespace": "monitoring",
                "name": "prometheus-server",
                "replicas": 1,
                "ready_replicas": 1,
                "strategy": "Recreate"
            }
        ],
        "k8s.service.list": [
            {
                "namespace": "default",
                "name": "otel-collector",
                "type": "ClusterIP",
                "cluster_ip": "10.96.100.1"
            },
            {
                "namespace": "default",
                "name": "otel-demo-frontend",
                "type": "LoadBalancer",
                "cluster_ip": "10.96.100.2",
                "external_ip": "192.168.1.100"
            }
        ],
        "k8s.pod.list": [
            {
                "namespace": "default",
                "name": "otel-collector-abc123",
                "status": "Running",
                "node_name": "node-1",
                "restart_count": 0,
                "ready": True
            },
            {
                "namespace": "default",
                "name": "otel-demo-frontend-xyz789",
                "status": "Running",
                "node_name": "node-2",
                "restart_count": 1,
                "ready": True
            }
        ],
        "k8s.hpa.list": [
            {
                "namespace": "default",
                "name": "otel-collector-hpa",
                "target_kind": "Deployment",
                "target_name": "otel-collector",
                "min_replicas": 2,
                "max_replicas": 10,
                "current_replicas": 3,
                "target_cpu_utilization": 70
            }
        ],
        "codeup.pipeline.list": [
            {
                "pipeline_id": "pipeline-001",
                "name": "otel-demo-build",
                "repo_id": "repo-001",
                "enabled": True
            },
            {
                "pipeline_id": "pipeline-002",
                "name": "otel-demo-deploy",
                "repo_id": "repo-001",
                "enabled": True
            }
        ],
        "codeup.repo.list": [
            {
                "repo_id": "repo-001",
                "repo_name": "opentelemetry-demo",
                "visibility": "PRIVATE",
                "default_branch": "main"
            }
        ],
        "acr.repository.list": [
            {
                "instance_id": "acr-instance-001",
                "repo_id": "repo-001",
                "repo_name": "otel/opentelemetry-collector",
                "repo_namespace": "otel",
                "repo_type": "PUBLIC"
            },
            {
                "instance_id": "acr-instance-001",
                "repo_id": "repo-002",
                "repo_name": "otel/opentelemetry-demo",
                "repo_namespace": "otel",
                "repo_type": "PUBLIC"
            }
        ],
        "acr.image.list": [
            {
                "instance_id": "acr-instance-001",
                "repo_id": "repo-001",
                "image_id": "sha256:abc123",
                "digest": "sha256:abc123def456",
                "tag": "v0.85.0",
                "size": 150000000
            }
        ]
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Mock 数据采集器 - 从 JSON 文件导入数据到数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data", "-d",
        type=str,
        default=None,
        help="Mock 数据 JSON 文件路径 (不指定则使用内置示例数据)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="sesora.db",
        help="数据库文件名 (默认: sesora.db)"
    )
    parser.add_argument(
        "--name", "-n",
        type=str,
        default="mock_collector",
        help="采集器名称 (默认: mock_collector)"
    )
    parser.add_argument(
        "--output-sample",
        action="store_true",
        help="输出示例数据文件并退出"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Mock 数据采集器")
    print("=" * 60)
    
    # 输出示例数据文件
    if args.output_sample:
        sample_path = PROJECT_ROOT / "run_pipeline" / "mock_data_sample.json"
        sample_data = create_sample_mock_data()
        with open(sample_path, 'w', encoding='utf-8') as f:
            json.dump(sample_data, f, indent=2, ensure_ascii=False)
        print(f"\n示例数据已输出到: {sample_path}")
        return 0
    
    # 加载数据
    if args.data:
        data_path = Path(args.data)
        if not data_path.is_absolute():
            data_path = PROJECT_ROOT / data_path
        print(f"\n数据文件: {data_path}")
        mock_data = load_mock_data(data_path)
    else:
        print("\n使用内置示例数据")
        mock_data = create_sample_mock_data()
    
    # 统计数据
    print(f"\nMock 数据统计:")
    total_records = sum(len(records) for records in mock_data.values())
    for item_name, records in sorted(mock_data.items()):
        print(f"  {item_name}: {len(records)} 条")
    print(f"  总计: {total_records} 条")
    
    # 数据库路径
    db_dir = PROJECT_ROOT / "data"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / args.db
    
    print(f"\n数据库: {db_path}")
    print(f"采集器名称: {args.name}")
    
    # 创建采集器并执行
    print("\n开始采集...")
    collector = GenericCollector(mock_data, collector_name=args.name)
    
    start_time = datetime.now()
    data_source = collector.collect()
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"\n采集完成! 耗时: {elapsed:.2f} 秒")
    print(f"状态: {data_source.status}")
    print(f"总记录数: {len(data_source.records)}")
    
    # 保存到数据库
    if data_source.status in ("ok", "partial"):
        save_to_database(data_source, db_path)
    else:
        print("\n采集失败，不保存数据")
        return 1
    
    print("\n" + "=" * 60)
    print("Mock 数据采集完成!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
