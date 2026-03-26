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
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.rds_oss import RdsInstanceRecord, OssBucketRecord, OssBucketLifecycleRecord, RdsProxyRecord
from sesora.schema.rds_oss import TairInstanceModeRecord
from sesora.schema.manual import ManualConsistencyModelRecord


class SdStorageTypesAnalyzer(Analyzer):
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
        score = 0.0
        evidence = []
        warnings = []

        serverless_storage_types = set()
        traditional_storage_types = set()

        if store.available("oss.bucket.list"):
            buckets: list[OssBucketRecord] = store.get("oss.bucket.list")
            if buckets:
                if len(buckets) >= 3:
                    serverless_storage_types.add("对象存储(OSS)")
                    evidence.append(f"✓ OSS Bucket: {len(buckets)} 个")
                elif buckets:
                    serverless_storage_types.add("对象存储(OSS)")
                    evidence.append(f"OSS Bucket: {len(buckets)} 个")

        if store.available("rds.instance.list"):
            instances: list[RdsInstanceRecord] = store.get("rds.instance.list")
            if instances:
                serverless_rds = [
                    i for i in instances
                    if i.db_instance_class
                       and "serverless" in i.db_instance_class.lower()
                ]
                traditional_rds = [
                    i for i in instances
                    if i not in serverless_rds
                ]

                if serverless_rds:
                    serverless_storage_types.add("Serverless RDS")
                    evidence.append(f"✓ Serverless RDS: {len(serverless_rds)} 个")

                if traditional_rds:
                    traditional_storage_types.add("RDS")
                    evidence.append(f"ℹ️ 传统 RDS: {len(traditional_rds)} 个（非 Serverless）")

        serverless_count = len(serverless_storage_types)

        if serverless_count == 0 and len(traditional_storage_types) == 0:
            evidence.append("❌ 未使用云存储服务")
            return self._scored(
                0,
                "未使用云存储服务：建议根据业务需求选择合适的存储方案",
                evidence
            )

        if serverless_count == 0:
            warnings.append("未使用 Serverless 形态存储，建议评估 Serverless RDS、表格存储等方案")
            evidence.append(f"传统存储类型: {', '.join(traditional_storage_types)}")
            return self._scored(
                2,
                "使用传统存储：建议向 Serverless 存储演进",
                evidence + [f"⚠️ {w}" for w in warnings]
            )

        if serverless_count >= 4:
            score += 5.0
            evidence.append(f"✓ Serverless 存储类型丰富: {serverless_count} 种")
        elif serverless_count == 3:
            score += 4.0
            evidence.append(f"✓ Serverless 存储类型良好: {serverless_count} 种")
        elif serverless_count == 2:
            score += 3.0
            evidence.append(f"Serverless 存储类型: {serverless_count} 种")
        else:
            score += 1.5
            evidence.append(f"Serverless 存储类型单一: {serverless_count} 种")
            warnings.append("Serverless 存储类型单一，建议增加缓存或 NoSQL 等类型")

        # --- 6. 使用规模评分（最高 2 分）---
        if store.available("oss.bucket.list"):
            buckets: list[OssBucketRecord] = store.get("oss.bucket.list")
            if buckets:
                bucket_count = len(buckets)
                if bucket_count >= 10:
                    score += 2.0
                    evidence.append(f"✓ 存储使用规模大: {bucket_count} 个 Bucket")
                elif bucket_count >= 5:
                    score += 1.5
                    evidence.append(f"✓ 存储使用规模良好: {bucket_count} 个 Bucket")
                elif bucket_count >= 3:
                    score += 1.0
                    evidence.append(f"存储使用规模: {bucket_count} 个 Bucket")
                else:
                    score += 0.5
                    evidence.append(f"存储使用规模较小: {bucket_count} 个 Bucket")

        # --- 7. 存储类型多样性加分（最高 1 分）---
        category_coverage = set()
        for st in serverless_storage_types:
            if "OSS" in st or "对象" in st:
                category_coverage.add("对象存储")
            elif "RDS" in st or "关系" in st:
                category_coverage.add("关系数据库")
            elif "NoSQL" in st or "表格" in st or "MongoDB" in st:
                category_coverage.add("NoSQL")
            elif "缓存" in st or "Redis" in st or "Tair" in st:
                category_coverage.add("缓存")
            elif "搜索" in st or "ES" in st:
                category_coverage.add("搜索")

        category_count = len(category_coverage)
        if category_count >= 4:
            score += 1.0
            evidence.append(f"✓ 存储类别覆盖全面: {', '.join(category_coverage)}")
        elif category_count >= 3:
            score += 0.5
            evidence.append(f"存储类别覆盖: {', '.join(category_coverage)}")
        else:
            evidence.append(f"存储类别: {', '.join(category_coverage) if category_coverage else '单一'}")

        final_score = max(min(round(score, 1), 8), 0)

        if final_score >= 7:
            status_msg = "Serverless 存储成熟：类型丰富、规模大、类别覆盖全面"
        elif final_score >= 5.5:
            status_msg = "Serverless 存储良好：具备多种 Serverless 存储能力"
        elif final_score >= 4:
            status_msg = "Serverless 存储基础：有 Serverless 存储但类型或规模有待提升"
        elif final_score >= 2:
            status_msg = "Serverless 存储薄弱：Serverless 存储类型单一"
        else:
            status_msg = "未使用 Serverless 存储：建议评估 Serverless 存储方案"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


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
        # return ["rds.instance.mode.list"]
        return ["tair.instance.mode.list"]

    def optional_data(self) -> list[str]:
        # return ["tair.instance.mode.list"]
        return []

    def analyze(self, store) -> ScoreResult:
        score = 0.0
        evidence: list[str] = []
        warnings: list[str] = []

        # TODO: use RdsInstanceRecord
        # rds_modes: list[RdsInstanceModeRecord] = store.get("rds.instance.mode.list") or []
        rds_modes: list = []
        if not rds_modes:
            evidence.append("ℹ️ 未获取到 RDS 模式数据")

        rds_total = len(rds_modes)
        rds_serverless = [m for m in rds_modes if m.is_serverless or m.pay_type.lower() == "serverless"]
        rds_serverless_core = [m for m in rds_serverless if "core" in m.instance_name.lower()] if rds_serverless else []

        if rds_total > 0:
            rds_ratio = len(rds_serverless) / rds_total if rds_total else 0
            evidence.append(
                f"RDS 实例总数: {rds_total}, Serverless 实例: {len(rds_serverless)} 个 ({rds_ratio * 100:.1f}%)"
            )

            if rds_ratio >= 0.8:
                score += 3.0
                evidence.append("✓ RDS 大部分为 Serverless 模式")
            elif rds_ratio >= 0.5:
                score += 2.0
                evidence.append("RDS 主要业务已迁移至 Serverless")
            elif rds_ratio > 0:
                score += 1.0
                evidence.append("RDS 部分实例使用 Serverless 模式")
            else:
                warnings.append("RDS 尚未使用 Serverless 模式，建议评估按量付费/自动扩缩容能力")

            if rds_serverless_core:
                score += 1.0
                evidence.append(f"✓ 核心数据库已使用 Serverless: {len(rds_serverless_core)} 个实例")

        tair_modes: list[TairInstanceModeRecord] = []
        if store.available("tair.instance.mode.list"):
            tair_modes = store.get("tair.instance.mode.list") or []

        if tair_modes:
            tair_serverless = [t for t in tair_modes if t.is_serverless or t.pay_type.lower() == "serverless"]
            tair_ratio = len(tair_serverless) / len(tair_modes) if tair_modes else 0
            evidence.append(
                f"Tair/Redis 实例总数: {len(tair_modes)}, Serverless 实例: {len(tair_serverless)} 个 ({tair_ratio * 100:.1f}%)"
            )

            if tair_ratio >= 0.8:
                score += 2.0
                evidence.append("✓ 缓存层大部分为 Serverless 模式")
            elif tair_ratio >= 0.5:
                score += 1.5
                evidence.append("缓存层主要使用 Serverless 实例")
            elif tair_ratio > 0:
                score += 1.0
                evidence.append("缓存层部分实例使用 Serverless 模式")
            else:
                warnings.append("缓存层尚未使用 Serverless 模式")
        else:
            evidence.append("ℹ️ 未检测到 Tair/Redis 模式数据")

        if rds_modes:
            auto_upgrade_instances = [m for m in rds_modes if m.is_serverless and m.category.lower() == "serverless"]
            if auto_upgrade_instances:
                score += 1.0
                evidence.append(f"✓ Serverless RDS 已启用自动化配置: {len(auto_upgrade_instances)} 个")

        if not rds_modes and not tair_modes:
            return self._not_evaluated("未获取到 RDS/Tair 模式数据")

        final_score = max(min(round(score, 1), 7), 0)

        if final_score >= 6:
            status_msg = "Serverless 数据使用程度高：核心数据库和缓存大多为 Serverless 模式"
        elif final_score >= 4.5:
            status_msg = "Serverless 数据使用程度良好：主要业务已使用 Serverless 存储"
        elif final_score >= 3:
            status_msg = "Serverless 数据使用程度一般：部分业务开始尝试 Serverless"
        elif final_score >= 1:
            status_msg = "Serverless 数据使用程度较低：仅少量试点或仅使用传统模式优化"
        else:
            status_msg = "未有效使用 Serverless 数据存储：建议评估迁移路径"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class SdLifecycleMgmtAnalyzer(Analyzer):
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

    def optional_data(self) -> list[str]:
        return ["tair.instance.mode.list"]

    def analyze(self, store) -> ScoreResult:
        lifecycles: list[OssBucketLifecycleRecord] = store.get("oss.bucket.lifecycle") or []

        score = 0.0
        evidence: list[str] = []
        warnings: list[str] = []

        # --- 1. OSS 生命周期规则配置情况（基础 0-2 分）---
        if not lifecycles:
            evidence.append("❌ 未配置 OSS 数据生命周期策略")
        else:
            evidence.append(f"生命周期规则数: {len(lifecycles)}")

            enabled_rules = [l for l in lifecycles if l.status == "Enabled"]
            enabled_ratio = len(enabled_rules) / len(lifecycles) if lifecycles else 0

            if enabled_ratio >= 0.8:
                score += 2.0
                evidence.append(
                    f"✓ 生命周期规则启用率高: {len(enabled_rules)}/{len(lifecycles)}"
                )
            elif enabled_ratio > 0:
                score += 1.0
                evidence.append(
                    f"生命周期规则启用率: {len(enabled_rules)}/{len(lifecycles)}"
                )
            else:
                warnings.append("已配置生命周期规则但均未启用，建议启用关键 Bucket 的策略")

        # --- 2. Transition/Expiration 规则完整度（0-2 分）---
        if lifecycles:
            with_transition = [l for l in lifecycles if l.has_transition]
            with_expiration = [l for l in lifecycles if l.has_expiration]

            if with_transition:
                score += 0.5
                evidence.append(f"✓ 归档转储规则: {len(with_transition)} 个")
            if with_expiration:
                score += 0.5
                evidence.append(f"✓ 过期删除规则: {len(with_expiration)} 个")

            if with_transition and with_expiration:
                score += 0.5
                evidence.append("✓ 同时配置归档与删除策略")

            aggressive_rules = [
                l for l in lifecycles
                if 0 < l.expiration_days < 7
            ]
            if aggressive_rules:
                warnings.append("存在过于激进的删除策略 (过期时间 < 7 天)，请确认不会误删业务数据")

        # --- 3. 覆盖范围评分（0-1 分）---
        if lifecycles:
            buckets = set(l.bucket_name for l in lifecycles)
            bucket_count = len(buckets)

            if bucket_count >= 5:
                score += 1.0
                evidence.append(f"✓ 生命周期策略覆盖 Bucket 较多: {bucket_count} 个")
            elif bucket_count >= 2:
                score += 0.5
                evidence.append(f"生命周期策略覆盖 Bucket: {bucket_count} 个")
            else:
                evidence.append(f"生命周期策略仅覆盖 {bucket_count} 个 Bucket")

        # --- 4. Tair/Redis TTL 使用情况（可选加分 0-1 分）---
        if store.available("tair.instance.mode.list"):
            tair_modes: list[TairInstanceModeRecord] = store.get("tair.instance.mode.list") or []
            if tair_modes:
                with_ttl = [t for t in tair_modes if t.has_ttl_config]
                ttl_ratio = len(with_ttl) / len(tair_modes) if tair_modes else 0

                evidence.append(
                    f"Tair/Redis 实例总数: {len(tair_modes)}, 配置 TTL 的实例: {len(with_ttl)} ({ttl_ratio * 100:.1f}%)"
                )

                if ttl_ratio >= 0.8:
                    score += 1.0
                    evidence.append("✓ 大部分缓存实例配置 TTL，临时数据可自动过期")
                elif ttl_ratio >= 0.5:
                    score += 0.5
                    evidence.append("缓存实例部分配置 TTL")
                elif ttl_ratio == 0:
                    warnings.append("缓存实例均未配置 TTL，可能导致临时数据长期占用内存")

        if not lifecycles and not store.available("tair.instance.mode.list"):
            return self._scored(
                0,
                "未配置数据生命周期/TTL 策略：缺乏自动归档和过期管理能力",
                evidence,
            )

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "数据生命周期管理完善：OSS 生命周期与缓存 TTL 配置合理且覆盖广"
        elif final_score >= 3.5:
            status_msg = "数据生命周期管理良好：已配置关键生命周期与过期策略"
        elif final_score >= 2:
            status_msg = "数据生命周期管理基础：有部分生命周期/TTL 配置，覆盖有限"
        elif final_score >= 1:
            status_msg = "数据生命周期管理薄弱：仅少量策略或配置不完整"
        else:
            status_msg = "数据生命周期管理缺失：建议配置 OSS Lifecycle 和缓存 TTL 策略"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


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
        instances: list[RdsInstanceRecord] = store.get("rds.instance.list") or []

        if not instances:
            return self._not_evaluated("未使用 RDS 服务")

        evidence: list[str] = [f"RDS 实例总数: {len(instances)}"]
        score = 0.0
        warnings: list[str] = []

        optimized_instances: set[str] = set()

        # --- 1. RDS Proxy 使用情况（最高 2 分）---
        if store.available("rds.proxy.list"):
            proxies: list[RdsProxyRecord] = store.get("rds.proxy.list") or []
            active_proxies = [p for p in proxies if (p.status or "").lower() == "running"]
            if active_proxies:
                proxy_count = len(active_proxies)
                evidence.append(f"✓ 发现 {proxy_count} 个运行中的 RDS Proxy")

                proxy_instance_ids = {p.instance_id for p in active_proxies}
                for i in instances:
                    if i.db_instance_id in proxy_instance_ids:
                        optimized_instances.add(i.db_instance_id)

                ratio = len(optimized_instances) / len(instances) if instances else 0
                if ratio >= 0.8:
                    score += 2.0
                    evidence.append("✓ 大部分 RDS 实例通过 Proxy 访问")
                elif ratio >= 0.5:
                    score += 1.5
                    evidence.append("RDS 实例有较大比例通过 Proxy 访问")
                elif ratio > 0:
                    score += 1.0
                    evidence.append("部分 RDS 实例通过 Proxy 访问")
            else:
                evidence.append("ℹ️ 未发现运行中的 RDS Proxy")

        # --- 2. 内置连接池与 Serverless 模式（最高 2 分）---
        builtin_pool_count = 0
        serverless_count = 0

        for i in instances:
            if i.db_instance_id in optimized_instances:
                continue

            db_class = i.db_instance_class or ""

            if i.connection_pool_enabled:
                builtin_pool_count += 1
                optimized_instances.add(i.db_instance_id)
                evidence.append(f"✓ 实例 {i.db_instance_id}: 内置连接池已启用")
            elif "serverless" in db_class.lower():
                serverless_count += 1
                optimized_instances.add(i.db_instance_id)
                evidence.append(f"✓ 实例 {i.db_instance_id}: Serverless 架构 (由平台自动管理连接)")

        total_instances = len(instances)
        optimized_count = len(optimized_instances)

        if total_instances > 0:
            ratio = optimized_count / total_instances
            evidence.append(
                f"已优化实例: {optimized_count}/{total_instances} ({ratio * 100:.1f}%)"
            )

            if ratio >= 0.8:
                score += 2.0
            elif ratio >= 0.5:
                score += 1.5
            elif ratio > 0:
                score += 1.0

        unoptimized = total_instances - optimized_count
        if unoptimized > 0:
            warnings.append(f"有 {unoptimized} 个实例未检测到明显的连接池优化配置")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "所有或绝大部分实例均已完成连接池优化"
        elif final_score >= 3.5:
            status_msg = "大部分实例已优化连接池，连接管理较为成熟"
        elif final_score >= 2:
            status_msg = "部分实例已优化连接池，但整体仍有较多直连风险"
        elif final_score >= 1:
            status_msg = "仅少量实例做了连接池优化，整体风险较高"
        else:
            status_msg = "未发现有效的连接池优化配置，FaaS 高并发直连 DB 可能存在风险"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class SdConsistencyModelAnalyzer(Analyzer):
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
        configs: list[ManualConsistencyModelRecord] = store.get("manual.consistency_model") or []

        if not configs:
            return self._not_evaluated("一致性模型适配需人工填写，暂无数据")

        config = configs[-1]

        evidence: list[str] = []
        warnings: list[str] = []
        score = 0.0

        # --- 1. 是否进行了评估（0 或 1 分）---
        if not config.has_assessment:
            warnings.append("尚未进行一致性模型适配评估")
        else:
            score += 1.0
            evidence.append("✓ 已进行一致性模型适配评估")

        # --- 2. 强一致性场景识别和覆盖情况（0-2 分）---
        strong_scenarios = config.strong_consistency_scenarios or []
        if strong_scenarios:
            count = len(strong_scenarios)
            evidence.append(f"强一致性场景已识别: {count} 个")
            if count >= 3:
                score += 2.0
            elif count >= 1:
                score += 1.0
        else:
            warnings.append("未识别强一致性场景，可能存在漏评风险")

        # --- 3. 最终一致性处理与强一致读取配置（0-1.5 分）---
        if config.eventual_consistency_handled:
            score += 0.75
            evidence.append("✓ 最终一致性场景已正确处理（如重试、幂等、补偿逻辑）")
        else:
            warnings.append("最终一致性场景未明确处理，可能导致读到旧数据或脏读")

        if config.consistent_read_configured:
            score += 0.75
            evidence.append("✓ 在关键路径上已配置强一致性读取")

        # --- 4. 数据风险识别情况（0-0.5 分）---
        if config.data_risk_identified:
            score += 0.5
            evidence.append("✓ 已识别并记录潜在数据一致性风险")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "一致性模型适配完善：强一致与最终一致场景均得到充分识别和处理"
        elif final_score >= 3.5:
            status_msg = "一致性模型适配良好：关键场景已识别并配置了强一致/补偿机制"
        elif final_score >= 2:
            status_msg = "一致性模型适配基础：仅进行了初步评估，部分场景处理不全面"
        elif final_score >= 1:
            status_msg = "一致性模型适配薄弱：评估有限，缺乏系统性的一致性策略"
        else:
            status_msg = "未有效进行一致性模型适配：建议系统性梳理强一致与最终一致场景"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


DATA_ANALYZERS = [
    SdStorageTypesAnalyzer(),
    SdUsageLevelAnalyzer(),
    SdLifecycleMgmtAnalyzer(),
    SdConnectionPoolingAnalyzer(),
    SdConsistencyModelAnalyzer(),
]
