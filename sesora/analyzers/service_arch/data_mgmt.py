"""
Service Architecture 维度 - 数据管理与解耦分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)               | 分值 | 评分标准                                                     |
| -------------------------- | ---- | ------------------------------------------------------------ |
| data_architecture_pattern  | 0-8  | 数据架构模式：数据库每服务(8)/混合CQRS(5)/共享数据库(1)/无(0)|
| data_consistency_model     | 0-6  | 一致性策略适配：最终一致性(6)/混合(4)/强一致性(1)/无(0)      |
| db_polyglot_usage          | 0-6  | 多模数据库应用：按需选型(6)/单一通用(2)/无(0)                |
| data_migration_strategy    | 5    | 在线数据迁移：不停机情况下进行数据库变更的能力               |
| data_ownership_clear       | 5    | 数据所有权明确：每个数据表有唯一写入者，其他服务通过 API 访问|
"""
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.apm import ApmServiceDbMappingRecord, ApmExternalDatabaseRecord
from sesora.schema.manual import ManualDataConsistencyRecord, ManualDataMigrationRecord, ManualDataOwnershipRecord


class DataArchitecturePatternAnalyzer(Analyzer):
    """
    数据架构模式分析器
    
    评估标准：
    - 数据库每服务 (8): 每个微服务拥有独立数据库，无共享表
    - 混合/CQRS (5): 核心服务独立，部分只读数据通过 CQRS 共享
    - 共享数据库 (1): 多个服务连接同一个 DB 实例甚至共享表（严重耦合）
    - 无 (0): 无数据
    
    数据来源：
    - APM external.database：观察不同服务对数据库的调用关系
    - APM service_db_mapping：服务-数据库映射关系
    """

    def key(self) -> str:
        return "data_architecture_pattern"

    def dimension(self) -> str:
        return "Service Architecture"

    def category(self) -> str:
        return "数据管理与解耦"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["apm.service.db.mapping"]

    def optional_data(self) -> list[str]:
        return ["apm.external.database"]

    def analyze(self, store) -> ScoreResult:
        mappings: list[ApmServiceDbMappingRecord] = store.get("apm.service.db.mapping")

        if not mappings:
            return self._not_evaluated("未获取到服务-数据库映射关系")

        evidence = []
        raw_score = 0

        # ========== 1. 基础统计 ==========
        services = set(m.service_name for m in mappings)
        databases = set(m.database_name for m in mappings)
        db_instances = set(m.db_instance for m in mappings if m.db_instance)

        total_services = len(services)

        evidence.append(f"服务数: {total_services}")
        evidence.append(f"数据库数: {len(databases)}")
        evidence.append(f"数据库实例数: {len(db_instances) if db_instances else '未知'}")

        if total_services == 0:
            return self._not_scored("无服务数据", evidence)

        # ========== 2. 计算数据库共享情况 ==========
        db_to_services = {}
        db_to_write_services = {}

        for m in mappings:
            db_key = m.db_instance or m.database_name

            if db_key not in db_to_services:
                db_to_services[db_key] = set()
                db_to_write_services[db_key] = set()

            db_to_services[db_key].add(m.service_name)

            if m.access_type in ("write_only", "read_write"):
                db_to_write_services[db_key].add(m.service_name)

        shared_dbs = [db for db, svc_set in db_to_services.items() if len(svc_set) > 1]
        isolated_dbs = [db for db, svc_set in db_to_services.items() if len(svc_set) == 1]

        multi_writer_dbs = [db for db, svc_set in db_to_write_services.items() if len(svc_set) > 1]

        evidence.append(f"独立数据库: {len(isolated_dbs)} 个")
        evidence.append(f"共享数据库: {len(shared_dbs)} 个")
        if multi_writer_dbs:
            evidence.append(f"⚠️ 多写入者数据库: {len(multi_writer_dbs)} 个（严重耦合）")

        # ========== 3. 数据库隔离度评分 (+3分) ==========
        service_db_ratio = len(databases) / total_services if total_services > 0 else 0

        total_db_keys = len(db_to_services)
        shared_ratio = len(shared_dbs) / total_db_keys if total_db_keys > 0 else 0
        multi_writer_ratio = len(multi_writer_dbs) / total_db_keys if total_db_keys > 0 else 0

        if service_db_ratio >= 0.8 and shared_ratio == 0:
            raw_score += 3
            evidence.append("数据库隔离度: 优秀 (1:1 服务数据库比，无共享)")
        elif service_db_ratio >= 0.5 and shared_ratio <= 0.3:
            raw_score += 2
            evidence.append("数据库隔离度: 良好 (核心服务独立)")
        elif service_db_ratio >= 0.3 and shared_ratio <= 0.5:
            raw_score += 1
            evidence.append("数据库隔离度: 一般 (部分服务独立)")
        else:
            evidence.append(f"数据库隔离度: 较低 (共享率 {shared_ratio:.0%})")

        # ========== 4. 写入隔离评分 (+2分) ==========
        if multi_writer_ratio == 0:
            raw_score += 2
            evidence.append("写入隔离: 优秀 (无多写入者)")
        elif multi_writer_ratio <= 0.2:
            raw_score += 1
            evidence.append("写入隔离: 良好 (少量多写入者)")
        else:
            evidence.append(f"写入隔离: 较差 (多写入者占比 {multi_writer_ratio:.0%})")

        # ========== 5. Schema/访问类型隔离 (+2分) ==========
        read_write_split = 0

        for db_key, svc_set in db_to_services.items():
            if len(svc_set) > 1:
                access_types = set()
                for m in mappings:
                    if (m.db_instance or m.database_name) == db_key:
                        access_types.add(m.access_type)

                if "read_only" in access_types and "write_only" in access_types:
                    read_write_split += 1

        if read_write_split > 0:
            raw_score += 1
            evidence.append(f"访问隔离: {read_write_split} 个数据库使用读写分离")

        shared_with_isolation = [m for m in mappings if m.is_shared and m.access_type == "read_only"]
        if shared_with_isolation:
            raw_score += 1
            evidence.append(f"共享隔离: {len(shared_with_isolation)} 个只读共享（CQRS 模式）")

        # ========== 6. APM 数据验证（可选） ==========
        if store.available("apm.external.database"):
            db_calls: list[ApmExternalDatabaseRecord] = store.get("apm.external.database")

            actual_db_access = {}
            for call in db_calls:
                db_key = call.db_instance or call.db_type
                if db_key not in actual_db_access:
                    actual_db_access[db_key] = set()
                actual_db_access[db_key].add(call.service_name)

            actual_multi_writer = sum(
                1 for db, svcs in actual_db_access.items() if len(svcs) > 1
            )

            if actual_multi_writer > len(multi_writer_dbs):
                evidence.append(f"⚠️ APM 检测到更多共享: {actual_multi_writer} 个数据库")

        if raw_score >= 7:
            final_score = 8
            conclusion = "数据库每服务：完全独立，无共享耦合"
        elif raw_score >= 6:
            final_score = 7
            conclusion = "数据库架构优秀：核心独立，少量只读共享"
        elif raw_score >= 5:
            final_score = 6
            conclusion = "数据库架构良好：主要服务独立，CQRS 模式"
        elif raw_score >= 4:
            final_score = 5
            conclusion = "混合/CQRS：核心服务独立，部分数据共享"
        elif raw_score >= 3:
            final_score = 4
            conclusion = "数据库架构一般：建议增加服务独立数据库"
        elif raw_score >= 2:
            final_score = 3
            conclusion = "部分服务共享数据库，建议优化"
        elif raw_score >= 1:
            final_score = 2
            conclusion = "数据库共享较多，存在耦合风险"
        else:
            final_score = 1
            conclusion = "共享数据库：多个服务连接同一 DB（严重耦合）"

        return self._scored(final_score, conclusion, evidence)


class DataConsistencyModelAnalyzer(Analyzer):
    """
    一致性策略适配分析器
    
    评估标准：
    - 最终一致性 (6): 分布式场景下正确采用最终一致性 + 补偿事务 (Saga/TCC)
    - 混合 (4): 局部强一致，跨服务最终一致
    - 强一致性 (1): 试图在跨服务调用中维持强一致性（导致性能瓶颈）
    - 无 (0): 无
    
    数据来源：
    - 人工填写：一致性模型配置
    - APM：分析是否有分布式事务相关调用
    """

    def key(self) -> str:
        return "data_consistency_model"

    def dimension(self) -> str:
        return "Service Architecture"

    def category(self) -> str:
        return "数据管理与解耦"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["manual.data_consistency"]

    def analyze(self, store) -> ScoreResult:
        records: list[ManualDataConsistencyRecord] = store.get("manual.data_consistency")

        if not records:
            return self._not_evaluated("未获取到一致性模型配置（需人工填写）")

        evidence = []
        raw_score = 0

        total = len(records)
        evidence.append(f"评估服务数: {total}")

        if total == 0:
            return self._not_scored("无一致性模型数据", evidence)

        # ========== 1. 统计一致性模型 ==========
        eventual_services = [r for r in records if r.consistency_model == "eventual"]
        mixed_services = [r for r in records if r.consistency_model == "mixed"]
        strong_services = [r for r in records if r.consistency_model == "strong"]
        unclear_services = [r for r in records if
                            not r.consistency_model or r.consistency_model not in ("eventual", "mixed", "strong")]

        evidence.append(f"最终一致性: {len(eventual_services)} 个")
        evidence.append(f"混合一致性: {len(mixed_services)} 个")
        evidence.append(f"强一致性: {len(strong_services)} 个")
        if unclear_services:
            evidence.append(f"未明确: {len(unclear_services)} 个")

        # ========== 2. 统计分布式事务模式 ==========
        saga_services = [r for r in records if r.uses_saga]
        tcc_services = [r for r in records if r.uses_tcc]
        distributed_lock_services = [r for r in records if r.uses_distributed_lock]

        has_compensation = len(saga_services) > 0 or len(tcc_services) > 0
        has_distributed_lock = len(distributed_lock_services) > 0

        if saga_services:
            evidence.append(f"Saga 模式: {len(saga_services)} 个")
        if tcc_services:
            evidence.append(f"TCC 模式: {len(tcc_services)} 个")
        if distributed_lock_services:
            evidence.append(f"分布式锁: {len(distributed_lock_services)} 个")

        # ========== 3. 一致性策略适配评分 (+3分) ==========
        eventual_ratio = len(eventual_services) / total
        mixed_ratio = len(mixed_services) / total
        strong_ratio = len(strong_services) / total
        unclear_ratio = len(unclear_services) / total

        if unclear_ratio > 0.5:
            evidence.append("一致性策略: 未明确（大部分服务未配置）")
        elif mixed_ratio >= 0.4:
            raw_score += 3
            evidence.append("一致性策略: 优秀（混合模式，按场景适配）")
        elif eventual_ratio >= 0.6:
            raw_score += 2
            evidence.append("一致性策略: 良好（主要最终一致性）")
        elif strong_ratio >= 0.6:
            raw_score += 2
            evidence.append("一致性策略: 良好（主要强一致性）")
        elif eventual_ratio >= 0.3 or strong_ratio >= 0.3:
            raw_score += 1
            evidence.append("一致性策略: 一般（有策略倾向但不够明确）")
        else:
            evidence.append("一致性策略: 较差（策略分散）")

        # ========== 4. 分布式事务实现评分 (+2分) ==========
        if has_compensation and has_distributed_lock:
            raw_score += 2
            evidence.append("事务实现: 优秀（补偿事务 + 分布式锁）")
        elif has_compensation:
            raw_score += 2
            evidence.append("事务实现: 良好（有补偿事务 Saga/TCC）")
        elif has_distributed_lock:
            raw_score += 1
            evidence.append("事务实现: 一般（有分布式锁，建议增加补偿机制）")
        else:
            evidence.append("事务实现: 较差（无分布式事务机制）")

        # ========== 5. 补偿事务覆盖率评分 (+1分) ==========
        if has_compensation:
            compensation_count = len(saga_services) + len(tcc_services)
            compensation_ratio = compensation_count / total

            if compensation_ratio >= 0.5:
                raw_score += 1
                evidence.append(f"补偿覆盖: 优秀 ({compensation_ratio:.0%} 服务有补偿)")
            elif compensation_ratio >= 0.2:
                evidence.append(f"补偿覆盖: 一般 ({compensation_ratio:.0%} 服务有补偿)")
            else:
                evidence.append(f"补偿覆盖: 较低 ({compensation_ratio:.0%} 服务有补偿)")

        if raw_score >= 6:
            final_score = 6
            conclusion = "一致性策略优秀：混合模式 + 完整事务机制"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "一致性策略良好：策略适配 + 补偿事务"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "一致性策略较好：有明确策略和事务机制"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "一致性策略一般：建议完善事务机制"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "一致性策略起步：有基础能力但需优化"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "一致性策略较差：需要全面规划"
        else:
            final_score = 0
            conclusion = "一致性策略未明确"

        return self._scored(final_score, conclusion, evidence)


class DbPolyglotUsageAnalyzer(Analyzer):
    """
    多模数据库应用分析器
    
    评估标准：
    - 按需选型 (6): 根据数据特性使用关系型、文档、键值、时序等多种数据库
    - 单一通用 (2): 所有场景强行使用同一种数据库（如全用 MySQL）
    - 无 (0): 无
    
    数据来源：
    - APM external.database、external.nosql：从 APM 外部调用记录中统计数据库类型种类
    - 各数据库产品 API：枚举用户开通的数据库产品类型
    """

    def key(self) -> str:
        return "db_polyglot_usage"

    def dimension(self) -> str:
        return "Service Architecture"

    def category(self) -> str:
        return "数据管理与解耦"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["apm.external.database"]

    def analyze(self, store) -> ScoreResult:
        db_calls: list[ApmExternalDatabaseRecord] = store.get("apm.external.database")

        if not db_calls:
            return self._not_evaluated("未获取到数据库调用数据")

        evidence = []
        raw_score = 0

        # ========== 1. 统计数据库类型和调用量 ==========
        db_type_counts = {}
        db_categories = set()

        category_mapping = {
            "关系型": ["MYSQL", "POSTGRESQL", "SQLSERVER", "ORACLE", "POLARDB", "MARIADB"],
            "文档": ["MONGODB", "COUCHDB", "DYNAMODB", "COSMOSDB"],
            "键值": ["REDIS", "MEMCACHE", "TAIR", "KEYDB", "ROCKSDB"],
            "时序": ["INFLUXDB", "PROMETHEUS", "TSDB", "LINDORM", "TIMESCALEDB"],
            "搜索": ["ELASTICSEARCH", "OPENSEARCH", "SOLR", "MEILISEARCH"],
            "宽表": ["HBASE", "TABLESTORE", "BIGTABLE", "CASSANDRA", "SCYLLADB"],
            "图": ["NEO4J", "TIGERGRAPH", "NEBULA"],
            "向量": ["MILVUS", "PINECONE", "WEAVIATE", "QDRANT"]
        }

        for call in db_calls:
            db_type = call.db_type.upper() if call.db_type else ""
            call_count = call.call_count or 1

            if db_type:
                db_type_counts[db_type] = db_type_counts.get(db_type, 0) + call_count

                for category, types in category_mapping.items():
                    if db_type in types:
                        db_categories.add(category)
                        break

        total_calls = sum(db_type_counts.values())
        db_types = set(db_type_counts.keys())

        evidence.append(f"数据库类型: {', '.join(sorted(db_types)) if db_types else '未知'}")
        evidence.append(f"数据模型类别: {', '.join(sorted(db_categories)) if db_categories else '未知'}")
        evidence.append(f"类别数量: {len(db_categories)}")

        # ========== 2. 核心数据模型多样性评分 (+3分) ==========
        core_categories = db_categories - {"键值"}

        if len(core_categories) >= 3:
            raw_score += 3
            evidence.append(f"核心模型多样性: 优秀 ({', '.join(sorted(core_categories))})")
        elif len(core_categories) == 2:
            raw_score += 2
            evidence.append(f"核心模型多样性: 良好 ({', '.join(sorted(core_categories))})")
        elif len(core_categories) == 1:
            raw_score += 1
            evidence.append(f"核心模型多样性: 一般 (仅使用 {list(core_categories)[0]})")
        else:
            evidence.append("核心模型多样性: 未检测到核心数据模型")

        # ========== 3. 场景适配评分 (+2分) ==========
        special_purpose_dbs = db_categories & {"搜索", "时序", "图", "向量"}

        if len(special_purpose_dbs) >= 2:
            raw_score += 2
            evidence.append(f"场景适配: 优秀 (使用 {', '.join(sorted(special_purpose_dbs))} 等专用数据库)")
        elif len(special_purpose_dbs) == 1:
            raw_score += 1
            evidence.append(f"场景适配: 良好 (使用 {list(special_purpose_dbs)[0]} 专用数据库)")
        else:
            evidence.append("场景适配: 未使用专用场景数据库")

        # ========== 4. 缓存策略评分 (+1分) ==========
        cache_dbs = {"REDIS", "MEMCACHE", "TAIR"}
        cache_calls = sum(count for db, count in db_type_counts.items() if db in cache_dbs)

        if cache_calls > 0:
            cache_ratio = cache_calls / total_calls if total_calls > 0 else 0
            if 0.1 <= cache_ratio <= 0.5:
                raw_score += 1
                evidence.append(f"缓存策略: 合理 (缓存占比 {cache_ratio:.0%})")
            elif cache_ratio > 0.5:
                evidence.append(f"缓存策略: 缓存占比过高 ({cache_ratio:.0%})，可能存在过度依赖")
            else:
                evidence.append(f"缓存策略: 缓存占比较低 ({cache_ratio:.0%})")
        else:
            evidence.append("缓存策略: 未检测到缓存层")

        # ========== 5. 反模式检测（扣分项）==========
        antipatterns = []

        relational_dbs = {"MYSQL", "POSTGRESQL", "SQLSERVER", "ORACLE"}
        relational_calls = sum(count for db, count in db_type_counts.items() if db in relational_dbs)

        if relational_calls / total_calls > 0.9 and len(db_types) == 1:
            antipatterns.append("单一关系型数据库处理所有数据")

        if antipatterns:
            evidence.append(f"⚠️ 潜在反模式: {', '.join(antipatterns)}")

        if raw_score >= 6:
            final_score = 6
            conclusion = "多模数据库应用优秀：核心模型多样 + 场景适配 + 合理缓存"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "多模数据库应用良好：核心模型多样 + 场景适配"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "多模数据库应用较好：有核心模型多样性"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "数据库选型一般：建议增加核心模型多样性"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "数据库选型起步：有基础多样性但需优化"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "数据库选型单一：建议根据场景选择专用数据库"
        else:
            final_score = 0
            conclusion = "未检测到多模数据库应用"

        if raw_score == 0:
            return self._not_scored("未检测到数据库使用", evidence)

        return self._scored(final_score, conclusion, evidence)


class DataMigrationStrategyAnalyzer(Analyzer):
    """
    在线数据迁移分析器
    
    评估标准：是否具备在不停机情况下进行数据库 Schema 变更或数据迁移的能力 (如双写、灰度切换)。
    
    数据来源：
    - 人工填写：在线数据迁移能力配置
    """

    def key(self) -> str:
        return "data_migration_strategy"

    def dimension(self) -> str:
        return "Service Architecture"

    def category(self) -> str:
        return "数据管理与解耦"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.data_migration"]

    def analyze(self, store) -> ScoreResult:
        records: list[ManualDataMigrationRecord] = store.get("manual.data_migration")

        if not records:
            return self._not_evaluated("未获取到数据迁移能力配置（需人工填写）")

        evidence = []
        raw_score = 0

        total_records = len(records)
        evidence.append(f"评估记录数: {total_records}")

        # ========== 1. 聚合所有记录的能力 ==========
        has_capability_count = sum(1 for r in records if r.has_capability)
        dual_write_count = sum(1 for r in records if r.supports_dual_write)
        grayscale_count = sum(1 for r in records if r.supports_grayscale)
        online_ddl_count = sum(1 for r in records if r.supports_online_ddl)

        all_tools = set()
        for r in records:
            if r.tools_used:
                all_tools.update(r.tools_used)

        capability_ratio = has_capability_count / total_records if total_records > 0 else 0
        dual_write_ratio = dual_write_count / total_records if total_records > 0 else 0
        grayscale_ratio = grayscale_count / total_records if total_records > 0 else 0
        online_ddl_ratio = online_ddl_count / total_records if total_records > 0 else 0

        evidence.append(f"具备迁移能力: {has_capability_count}/{total_records} ({capability_ratio:.0%})")
        evidence.append(f"支持双写: {dual_write_count}/{total_records} ({dual_write_ratio:.0%})")
        evidence.append(f"支持灰度: {grayscale_count}/{total_records} ({grayscale_ratio:.0%})")
        evidence.append(f"支持在线DDL: {online_ddl_count}/{total_records} ({online_ddl_ratio:.0%})")

        if all_tools:
            evidence.append(f"使用工具: {', '.join(sorted(all_tools))}")

        # ========== 2. 基础能力评分 (+2分) ==========
        if capability_ratio >= 0.8:
            raw_score += 2
            evidence.append("基础能力: 优秀 (80%+ 服务具备迁移能力)")
        elif capability_ratio >= 0.5:
            raw_score += 1
            evidence.append("基础能力: 良好 (50%+ 服务具备迁移能力)")
        elif capability_ratio > 0:
            evidence.append(f"基础能力: 一般 ({capability_ratio:.0%} 服务具备迁移能力)")
        else:
            evidence.append("基础能力: 无")
            return self._not_scored("不具备在线数据迁移能力", evidence)

        # ========== 3. 技术能力深度评分 (+2分) ==========
        advanced_features = 0
        if dual_write_ratio >= 0.5:
            advanced_features += 1
            evidence.append("双写能力: 覆盖良好")
        elif dual_write_ratio > 0:
            evidence.append(f"双写能力: 部分覆盖 ({dual_write_ratio:.0%})")

        if grayscale_ratio >= 0.5:
            advanced_features += 1
            evidence.append("灰度切换: 覆盖良好")
        elif grayscale_ratio > 0:
            evidence.append(f"灰度切换: 部分覆盖 ({grayscale_ratio:.0%})")

        if online_ddl_ratio >= 0.5:
            advanced_features += 1
            evidence.append("在线DDL: 覆盖良好")
        elif online_ddl_ratio > 0:
            evidence.append(f"在线DDL: 部分覆盖 ({online_ddl_ratio:.0%})")

        raw_score += min(advanced_features, 2)

        # ========== 4. 工具链成熟度评分 (+1分) ==========
        professional_tools = {
            "pt-online-schema-change", "gh-ost", "flyway", "liquibase",
            "pt-archiver", "debezium", "canal", "maxwell"
        }

        if all_tools:
            professional_used = all_tools & professional_tools
            if len(professional_used) >= 2:
                raw_score += 1
                evidence.append(f"工具链: 专业 ({', '.join(professional_used)})")
            elif len(professional_used) == 1:
                evidence.append(f"工具链: 有专业工具 ({list(professional_used)[0]})")
            else:
                evidence.append("工具链: 自研或通用工具")
        else:
            evidence.append("工具链: 未记录工具使用情况")

        # ========== 5. 证据质量评分 (+1分) ==========
        has_evidence_count = sum(1 for r in records if r.evidence and len(r.evidence) > 10)
        evidence_ratio = has_evidence_count / total_records if total_records > 0 else 0

        if evidence_ratio >= 0.3:
            raw_score += 1
            evidence.append(f"实践证据: 有 ({evidence_ratio:.0%} 记录提供详细证据)")
        else:
            evidence.append("实践证据: 较少 (建议提供实际迁移案例)")

        if raw_score >= 6:
            final_score = 5
            conclusion = "在线数据迁移能力完备：全服务覆盖 + 专业工具链 + 实践验证"
        elif raw_score >= 5:
            final_score = 4
            conclusion = "在线数据迁移能力良好：大部分服务具备完整能力"
        elif raw_score >= 4:
            final_score = 3
            conclusion = "在线数据迁移能力较好：核心能力具备，建议扩大覆盖"
        elif raw_score >= 3:
            final_score = 2
            conclusion = "在线数据迁移能力起步：基础能力具备，需完善技术栈"
        elif raw_score >= 2:
            final_score = 1
            conclusion = "在线数据迁移能力有限：仅基础能力"
        else:
            final_score = 0
            conclusion = "在线数据迁移能力缺失"

        return self._scored(final_score, conclusion, evidence)


class DataOwnershipClearAnalyzer(Analyzer):
    """
    数据所有权明确分析器
    
    评估标准：是否明确规定了每个数据表/集合的"唯一写入者"，其他服务只能通过 API 访问。
    
    数据来源：
    - 人工填写：数据所有权配置
    - APM service_db_mapping：分析访问类型
    """

    def key(self) -> str:
        return "data_ownership_clear"

    def dimension(self) -> str:
        return "Service Architecture"

    def category(self) -> str:
        return "数据管理与解耦"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.data_ownership"]

    def optional_data(self) -> list[str]:
        return ["apm.service.db.mapping"]

    def analyze(self, store) -> ScoreResult:
        records: list[ManualDataOwnershipRecord] = store.get("manual.data_ownership")

        if not records:
            return self._not_evaluated("未获取到数据所有权配置（需人工填写）")

        evidence = []
        raw_score = 0

        total = len(records)
        evidence.append(f"数据表/集合数: {total}")

        if total == 0:
            return self._not_scored("无数据所有权配置", evidence)

        # ========== 1. 统计所有权明确度 ==========
        has_owner = [r for r in records if r.owner_service]
        via_api = [r for r in records if r.access_via_api]

        owner_ratio = len(has_owner) / total
        api_ratio = len(via_api) / total

        evidence.append(f"有明确 Owner: {len(has_owner)}/{total} ({owner_ratio:.0%})")
        evidence.append(f"通过 API 访问: {len(via_api)}/{total} ({api_ratio:.0%})")

        # ========== 2. 写入所有权评分 (+3分) ==========
        if owner_ratio >= 0.9:
            raw_score += 3
            evidence.append("写入所有权: 优秀 (90%+ 表有明确 Owner)")
        elif owner_ratio >= 0.7:
            raw_score += 2
            evidence.append("写入所有权: 良好 (70%+ 表有明确 Owner)")
        elif owner_ratio >= 0.5:
            raw_score += 1
            evidence.append("写入所有权: 一般 (50%+ 表有明确 Owner)")
        else:
            evidence.append(f"写入所有权: 较差 (仅 {owner_ratio:.0%} 表有明确 Owner)")

        # ========== 3. API 访问规范评分 (+2分) ==========
        if api_ratio >= 0.8:
            raw_score += 2
            evidence.append("访问规范: 优秀 (80%+ 通过 API 访问)")
        elif api_ratio >= 0.5:
            raw_score += 1
            evidence.append("访问规范: 良好 (50%+ 通过 API 访问)")
        else:
            evidence.append(f"访问规范: 一般 (仅 {api_ratio:.0%} 通过 API 访问)")

        # ========== 4. APM 数据验证（关键反模式检测）==========
        apm_violations = 0
        if store.available("apm.service.db.mapping"):
            mappings: list[ApmServiceDbMappingRecord] = store.get("apm.service.db.mapping")

            write_services = {}
            for m in mappings:
                if m.access_type in ("write_only", "read_write"):
                    db_key = m.database_name
                    if db_key not in write_services:
                        write_services[db_key] = set()
                    write_services[db_key].add(m.service_name)

            multi_writer_dbs = {db: svcs for db, svcs in write_services.items() if len(svcs) > 1}

            if multi_writer_dbs:
                apm_violations += len(multi_writer_dbs)
                evidence.append(f"⚠️ APM 检测到多写入者: {len(multi_writer_dbs)} 个数据库")
                for db, svcs in list(multi_writer_dbs.items())[:3]:  # 最多显示3个
                    evidence.append(f"  - {db}: {', '.join(svcs)}")

        # ========== 5. 反模式扣分 ==========
        if apm_violations == 0:
            evidence.append("数据写入: 规范 (无多写入者)")
        elif apm_violations <= 2:
            raw_score -= 1
            evidence.append(f"数据写入: 有违规 ({apm_violations} 个多写入者数据库)")
        else:
            raw_score -= 2
            evidence.append(f"数据写入: 严重违规 ({apm_violations} 个多写入者数据库)")

        # ========== 6. 共享数据合理性评估 ==========
        shared_tables = [r for r in records if not r.owner_service]

        legitimate_shared = [r for r in shared_tables if r.table_or_collection and (
                r.table_or_collection.startswith(("dim_", "config_", "common_", "sys_")) or
                "_config" in r.table_or_collection or
                "_dict" in r.table_or_collection
        )]

        if shared_tables:
            legitimate_ratio = len(legitimate_shared) / len(shared_tables) if shared_tables else 0
            if legitimate_ratio >= 0.7:
                evidence.append(f"共享数据: 合理 ({legitimate_ratio:.0%} 为维度/配置表)")
            else:
                evidence.append(
                    f"⚠️ 共享数据: 较多业务表无明确 Owner ({len(shared_tables) - len(legitimate_shared)} 个)")

        # ========== 评分映射（平滑梯度） ==========
        raw_score = max(0, min(raw_score, 5))

        if raw_score >= 5:
            final_score = 5
            conclusion = "数据所有权明确：全量表有 Owner，API 访问规范，无多写入者"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "数据所有权较明确：大部分表规范，建议完善剩余部分"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "数据所有权一般：核心表已规范，需扩大覆盖"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "数据所有权起步：有基础规范，存在多写入者风险"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "数据所有权较差：规范覆盖不足，需全面整改"
        else:
            final_score = 0
            conclusion = "数据所有权严重违规：存在大量多写入者"

        return self._scored(final_score, conclusion, evidence)


DATA_MGMT_ANALYZERS = [
    DataArchitecturePatternAnalyzer(),
    DataConsistencyModelAnalyzer(),
    DbPolyglotUsageAnalyzer(),
    DataMigrationStrategyAnalyzer(),
    DataOwnershipClearAnalyzer(),
]
