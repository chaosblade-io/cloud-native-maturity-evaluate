"""
Serverless 维度 - 无服务器数据 (Serverless Data) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                       |
| sd_storage_types          | 0-8  | 存储类型多样性：>=4种(8分)/2-3种(5分)/1种(2分)                 |
| sd_usage_level            | 0-7  | 使用程度：全面(7)/高(5)/中(3)/低(0)                            |
| sd_lifecycle_mgmt         | 5    | 数据生命周期管理：S3 Lifecycle, TTL 等自动归档或删除           |
| sd_connection_pooling     | 5    | 连接池优化：RDS Proxy、Data API 或连接池中间件                 |
| sd_consistency_model      | 5    | 一致性模型适配：正确适配最终一致性或使用强一致性读取           |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.rds_oss import RdsInstanceRecord, OssBucketRecord, OssBucketLifecycleRecord, RdsProxyRecord
from ...schema.cloud_storage import CloudStorageProductRecord
from ...schema.manual import ManualConsistencyModelRecord


class SdStorageTypes(Analyzer):
    """
    存储类型多样性分析器
    
    评估标准：
    - 覆盖对象存储、NoSQL、缓存、搜索等 >=4 种无服务器形态得 8 分
    - 覆盖 2-3 种得 5 分
    - 仅 1 种得 2 分
    
    数据来源：
    - 各产品 API：统计用户开通的存储类产品类型（OSS/表格存储/Redis Serverless 等）
    """
    
    def key(self) -> str:
        return "sd_storage_types"
    
    def dimension(self) -> str:
        return "Serverless"
    
    def category(self) -> str:
        return "无服务器数据"
    
    def max_score(self) -> int:
        return 8
    
    def required_data(self) -> list[str]:
        return []
    
    def optional_data(self) -> list[str]:
        return ["oss.bucket.list", "rds.instance.list", "cloud.storage.products"]
    
    def analyze(self, store) -> ScoreResult:
        storage_types = set()
        evidence = []
        
        # 检查 OSS（对象存储）
        if store.available("oss.bucket.list"):
            buckets: list[OssBucketRecord] = store.get("oss.bucket.list")
            if buckets:
                storage_types.add("对象存储(OSS)")
                evidence.append(f"OSS Bucket: {len(buckets)} 个")
        
        # 检查 RDS（关系型数据库）
        if store.available("rds.instance.list"):
            instances: list[RdsInstanceRecord] = store.get("rds.instance.list")
            if instances:
                # 区分 Serverless 和传统模式
                serverless_rds = [i for i in instances if "serverless" in i.db_instance_class.lower()]
                if serverless_rds:
                    storage_types.add("Serverless RDS")
                    evidence.append(f"Serverless RDS: {len(serverless_rds)} 个")
                else:
                    storage_types.add("RDS")
                    evidence.append(f"RDS 实例: {len(instances)} 个")
        
        # 检查其他云存储产品
        if store.available("cloud.storage.products"):
            products: list[CloudStorageProductRecord] = store.get("cloud.storage.products")
            for p in products:
                product_name = p.product_name.lower()
                
                if "tablestore" in product_name or "ots" in product_name:
                    storage_types.add("NoSQL(表格存储)")
                elif "redis" in product_name or "tair" in product_name:
                    storage_types.add("缓存(Redis/Tair)")
                elif "elasticsearch" in product_name or "opensearch" in product_name:
                    storage_types.add("搜索(ES)")
                elif "mongodb" in product_name:
                    storage_types.add("NoSQL(MongoDB)")
                elif p.product_name not in storage_types:
                    storage_types.add(p.product_name)
                
                evidence.append(f"{p.product_name}: 已使用")
        
        if not storage_types:
            return self._not_scored("未使用云存储服务", [])
        
        type_count = len(storage_types)
        evidence.insert(0, f"存储类型数: {type_count}")
        
        if type_count >= 4:
            return self._scored(8, "存储类型多样性高 (>=4种)", evidence)
        elif type_count >= 2:
            return self._scored(5, "存储类型多样性中 (2-3种)", evidence)
        else:
            return self._scored(2, "存储类型单一 (1种)", evidence)


class SdUsageLevelAnalyzer(Analyzer):
    """
    使用程度分析器
    
    评估标准：
    - 全面 (7): 核心数据库和缓存均为 Serverless 模式 (按量付费/自动扩缩容)
    - 高 (5): 主要业务使用 Serverless 存储
    - 中 (3): 仅非核心数据使用
    - 低/无 (0)
    
    数据来源：
    - RDS/PolarDB API：检查实例的 payType 是否为 Serverless 模式
    - Tair API：检查是否使用了 Tair Serverless 模式
    """
    
    def key(self) -> str:
        return "sd_usage_level"
    
    def dimension(self) -> str:
        return "Serverless"
    
    def category(self) -> str:
        return "无服务器数据"
    
    def max_score(self) -> int:
        return 7
    
    def required_data(self) -> list[str]:
        return ["rds.instance.list"]

    def analyze(self, store) -> ScoreResult:
        # 1. 安全获取列表，防止返回 None
        instances: list[RdsInstanceRecord] = store.get("rds.instance.list")

        if not instances:
            return self._not_evaluated("未检测到 RDS 实例")

        # 2. 安全检查并筛选 (增加 None 判断)
        serverless = []
        auto_scale = []

        for i in instances:
            # 检查 Serverless
            db_class = i.db_instance_class or ""  # 防止 None
            if "serverless" in db_class.lower():
                serverless.append(i)

            if i.auto_upgrade_minor_version:
                auto_scale.append(i)

        # 3. 构建详细的证据链
        evidence = [
            f"RDS 实例总数: {len(instances)}",
            f"Serverless 实例: {len(serverless)} 个 ({len(serverless) / len(instances) * 100:.1f}%)",
            f"开启自动小版本升级: {len(auto_scale)} 个"
        ]

        serverless_ratio = len(serverless) / len(instances) if instances else 0

        if serverless_ratio >= 0.8:
            return self._scored(7, "全面使用 Serverless 架构，弹性能力极佳", evidence)
        elif serverless_ratio >= 0.5:
            return self._scored(5, "主要业务已迁移至 Serverless", evidence)
        elif serverless_ratio > 0:
            return self._scored(3, "部分业务尝试使用 Serverless", evidence)
        elif auto_scale:
            return self._scored(2, "未使用 Serverless，但已配置自动小版本升级", evidence)
        else:
            return self._not_scored("未使用 Serverless 且未开启自动升级优化", evidence)

class SdLifecycleMgmt(Analyzer):
    """
    数据生命周期管理分析器
    
    评估标准：是否利用 S3 Lifecycle, TTL 等特性自动归档或删除过期数据，优化成本
    
    数据来源：
    - OSS API：GetBucketLifecycle，确认是否有 Transition (转储) 和 Expiration (删除) 动作
    - Tair API：检查是否对临时数据设置了 TTL 属性
    """
    
    def key(self) -> str:
        return "sd_lifecycle_mgmt"
    
    def dimension(self) -> str:
        return "Serverless"
    
    def category(self) -> str:
        return "无服务器数据"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["oss.bucket.lifecycle"]
    
    def analyze(self, store) -> ScoreResult:
        lifecycles: list[OssBucketLifecycleRecord] = store.get("oss.bucket.lifecycle")
        
        if not lifecycles:
            return self._not_scored("未配置数据生命周期策略", [])
        
        evidence = [f"生命周期规则数: {len(lifecycles)}"]
        score = 2  # 基础分：有生命周期配置
        
        # 检查 Transition（归档转储）规则
        with_transition = [l for l in lifecycles if l.has_transition]
        if with_transition:
            score += 1
            evidence.append(f"✓ 归档转储规则: {len(with_transition)} 个")
        
        # 检查 Expiration（过期删除）规则
        with_expiration = [l for l in lifecycles if l.has_expiration]
        if with_expiration:
            score += 1
            evidence.append(f"✓ 过期删除规则: {len(with_expiration)} 个")
        
        # 检查是否覆盖多个 Bucket
        buckets = set(l.bucket_name for l in lifecycles)
        if len(buckets) >= 3:
            score += 1
            evidence.append(f"覆盖 Bucket: {len(buckets)} 个")
        
        if score >= 4:
            return self._scored(5, "数据生命周期管理完善", evidence)
        elif score >= 2:
            return self._scored(score, "数据生命周期管理基本配置", evidence)
        else:
            return self._scored(score, "数据生命周期管理有待改进", evidence)


class SdConnectionPoolingAnalyzer(Analyzer):
    """
    连接池优化分析器
    
    评估标准：针对 FaaS 访问 DB 的场景
    - 检查是否启用了 RDS Proxy、Data API 或连接池中间件
    - 若 FaaS 直连 DB 且并发数 > 100，视为高风险，不得分
    
    数据来源：
    - RDS API：DescribeDBProxy，检查是否启用了 RDS Proxy
    """
    
    def key(self) -> str:
        return "sd_connection_pooling"
    
    def dimension(self) -> str:
        return "Serverless"
    
    def category(self) -> str:
        return "无服务器数据"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["rds.instance.list"]
    
    def optional_data(self) -> list[str]:
        return ["rds.proxy.list"]

    def analyze(self, store) -> ScoreResult:
        instances: list[RdsInstanceRecord] = store.get("rds.instance.list")

        if not instances:
            return self._not_evaluated("未使用 RDS 服务")

        evidence = [f"RDS 实例总数: {len(instances)}"]

        builtin_pool_count = 0
        serverless_count = 0
        optimized_instances = set()

        if store.available("rds.proxy.list"):
            proxies: list[RdsProxyRecord] = store.get("rds.proxy.list")
            active_proxies = [p for p in proxies if p.status.lower() == "startup"]
            if active_proxies:
                proxy_count = len(active_proxies)
                evidence.append(f"✓ 发现 {proxy_count} 个活跃的 RDS Proxy")

                for i in instances:
                    optimized_instances.add(i.db_instance_id)

        for i in instances:
            if i.db_instance_id in optimized_instances:
                continue

            db_class = i.db_instance_class

            if i.connection_pool_enabled:
                builtin_pool_count += 1
                optimized_instances.add(i.db_instance_id)
                evidence.append(f"✓ 实例 {i.db_instance_id}: 内置连接池已启用")

            elif "serverless" in db_class.lower():
                serverless_count += 1
                optimized_instances.add(i.db_instance_id)
                evidence.append(f"✓ 实例 {i.db_instance_id}: Serverless 架构 (自动管理连接)")

        total_instances = len(instances)
        optimized_count = len(optimized_instances)

        unoptimized = total_instances - optimized_count
        if unoptimized > 0:
            evidence.append(f"⚠ 有 {unoptimized} 个实例未检测到明显的连接池优化配置")

        if optimized_count == total_instances:
            return self._scored(5, "所有实例均已完成连接池优化", evidence)

        if optimized_count > 0:
            ratio = optimized_count / total_instances
            if ratio >= 0.8:
                score = 4
                msg = "大部分实例已优化连接池"
            elif ratio >= 0.5:
                score = 3
                msg = "部分实例已优化连接池"
            else:
                score = 2
                msg = "仅少量实例优化了连接池"

            return self._scored(score, msg, evidence)

        return self._not_scored("未发现任何连接池优化配置", evidence)

class SdConsistencyModel(Analyzer):
    """
    一致性模型适配分析器
    
    评估标准：业务逻辑是否正确适配了 NoSQL/Serverless DB 的最终一致性模型，
    或在需要时强制使用了强一致性读取
    
    数据来源：
    - 人工填写/源代码分析
    - 确认在需要强一致性的场景是否显式指定了 ConsistentRead=true
    """
    
    def key(self) -> str:
        return "sd_consistency_model"
    
    def dimension(self) -> str:
        return "Serverless"
    
    def category(self) -> str:
        return "无服务器数据"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["manual.consistency_model"]
    
    def analyze(self, store) -> ScoreResult:
        configs: list[ManualConsistencyModelRecord] = store.get("manual.consistency_model")
        
        if not configs:
            return self._not_evaluated("一致性模型适配需人工填写，暂无数据")
        
        config = configs[-1]
        
        if not config.has_assessment:
            return self._not_scored("未进行一致性模型适配评估", [])
        
        evidence = []
        score = 2  # 基础分：有评估
        
        if config.strong_consistency_scenarios:
            evidence.append(f"强一致性场景已识别: {len(config.strong_consistency_scenarios)} 个")
            score += 1
        
        if config.eventual_consistency_handled:
            evidence.append("✓ 最终一致性场景已正确处理")
            score += 1
        
        if config.consistent_read_configured:
            evidence.append("✓ 强一致性读取已配置")
            score += 1
        
        if score >= 4:
            return self._scored(5, "一致性模型适配完善", evidence)
        elif score >= 2:
            return self._scored(score, "一致性模型适配基本满足", evidence)
        else:
            return self._scored(score, "一致性模型适配有待改进", evidence)


# 导出所有分析器
DATA_ANALYZERS = [
    SdStorageTypes(),
    SdUsageLevelAnalyzer(),
    SdLifecycleMgmt(),
    SdConnectionPoolingAnalyzer(),
    SdConsistencyModel(),
]
