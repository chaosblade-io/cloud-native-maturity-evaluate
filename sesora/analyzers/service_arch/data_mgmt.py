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
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.apm import ApmServiceDbMappingRecord, ApmExternalDatabaseRecord
from ...schema.manual import ManualDataConsistencyRecord, ManualDataMigrationRecord, ManualDataOwnershipRecord


class DataArchitecturePattern(Analyzer):
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
        
        # 分析数据库隔离情况
        services = set(m.service_name for m in mappings)
        databases = set(m.database_name for m in mappings)
        db_instances = set(m.db_instance for m in mappings if m.db_instance)
        
        evidence = [
            f"服务数: {len(services)}",
            f"数据库数: {len(databases)}",
            f"数据库实例数: {len(db_instances) if db_instances else '未知'}"
        ]
        
        # 检查共享数据库
        shared_mappings = [m for m in mappings if m.is_shared]
        if shared_mappings:
            evidence.append(f"共享数据库: {len(shared_mappings)} 个")
        
        # 计算每个数据库被多少服务使用
        db_to_services = {}
        for m in mappings:
            db_key = m.db_instance or m.database_name
            if db_key not in db_to_services:
                db_to_services[db_key] = set()
            db_to_services[db_key].add(m.service_name)
        
        # 分析共享程度
        shared_dbs = [db for db, svc_set in db_to_services.items() if len(svc_set) > 1]
        isolated_dbs = [db for db, svc_set in db_to_services.items() if len(svc_set) == 1]
        
        evidence.append(f"独立数据库: {len(isolated_dbs)} 个")
        evidence.append(f"共享数据库: {len(shared_dbs)} 个")
        
        # 评分逻辑
        if len(services) == 0:
            return self._not_scored("无服务数据", evidence)
        
        # 理想情况：每个服务有独立数据库
        if len(databases) >= len(services) and len(shared_dbs) == 0:
            return self._scored(8, "数据库每服务：每个微服务拥有独立数据库", evidence)
        elif len(shared_dbs) <= len(db_to_services) * 0.3:
            # 少量共享（<=30%），可能是 CQRS 模式
            return self._scored(5, "混合/CQRS：核心服务独立，部分数据共享", evidence)
        elif len(shared_dbs) <= len(db_to_services) * 0.7:
            # 较多共享（30-70%）
            return self._scored(3, "部分服务共享数据库", evidence)
        else:
            # 严重共享（>70%）
            return self._scored(1, "共享数据库：多个服务连接同一 DB（严重耦合）", evidence)


class DataConsistencyModel(Analyzer):
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
        
        evidence = [f"评估服务数: {len(records)}"]
        
        # 统计一致性模型
        eventual_services = [r for r in records if r.consistency_model == "eventual"]
        mixed_services = [r for r in records if r.consistency_model == "mixed"]
        strong_services = [r for r in records if r.consistency_model == "strong"]
        
        # 统计分布式事务模式
        saga_services = [r for r in records if r.uses_saga]
        tcc_services = [r for r in records if r.uses_tcc]
        distributed_lock_services = [r for r in records if r.uses_distributed_lock]
        
        evidence.append(f"最终一致性服务: {len(eventual_services)} 个")
        evidence.append(f"混合一致性服务: {len(mixed_services)} 个")
        evidence.append(f"强一致性服务: {len(strong_services)} 个")
        
        if saga_services or tcc_services:
            evidence.append(f"使用 Saga/TCC: {len(saga_services) + len(tcc_services)} 个")
        if distributed_lock_services:
            evidence.append(f"使用分布式锁: {len(distributed_lock_services)} 个")
        
        # 评分逻辑
        total = len(records)
        if total == 0:
            return self._not_scored("无一致性模型数据", evidence)
        
        eventual_ratio = len(eventual_services) / total
        mixed_ratio = len(mixed_services) / total
        strong_ratio = len(strong_services) / total
        
        has_compensation = len(saga_services) > 0 or len(tcc_services) > 0
        
        if eventual_ratio >= 0.6 and has_compensation:
            # 最终一致性 + 补偿事务
            return self._scored(6, "最终一致性：正确采用补偿事务 (Saga/TCC)", evidence)
        elif eventual_ratio >= 0.4 or mixed_ratio >= 0.4:
            # 混合模式
            return self._scored(4, "混合：局部强一致，跨服务最终一致", evidence)
        elif strong_ratio >= 0.5 and distributed_lock_services:
            # 强一致性模式
            return self._scored(1, "强一致性：跨服务维持强一致性（性能瓶颈风险）", evidence)
        elif strong_ratio >= 0.3:
            return self._scored(2, "偏向强一致性", evidence)
        else:
            return self._scored(3, "一致性策略不明确", evidence)


class DbPolyglotUsage(Analyzer):
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
        
        # 统计数据库类型
        db_types = set()
        db_categories = set()  # 关系型/文档/键值/时序
        
        for call in db_calls:
            db_type = call.db_type.upper() if call.db_type else ""
            db_types.add(db_type)
            
            # 分类
            if db_type in ("MYSQL", "POSTGRESQL", "SQLSERVER", "ORACLE", "POLARDB"):
                db_categories.add("关系型")
            elif db_type in ("MONGODB", "COUCHDB"):
                db_categories.add("文档")
            elif db_type in ("REDIS", "MEMCACHE", "TAIR"):
                db_categories.add("键值")
            elif db_type in ("INFLUXDB", "PROMETHEUS", "TSDB", "LINDORM"):
                db_categories.add("时序")
            elif db_type in ("ELASTICSEARCH", "OPENSEARCH"):
                db_categories.add("搜索")
            elif db_type in ("HBASE", "TABLESTORE"):
                db_categories.add("宽表")
        
        evidence = [
            f"数据库类型: {', '.join(db_types) if db_types else '未知'}",
            f"数据库类别: {', '.join(db_categories) if db_categories else '未知'}",
            f"类别数量: {len(db_categories)}"
        ]
        
        # 评分逻辑
        if len(db_categories) >= 3:
            # 使用 3 种以上类别的数据库
            return self._scored(6, "按需选型：根据数据特性使用多种数据库", evidence)
        elif len(db_categories) >= 2:
            # 使用 2 种类别的数据库
            return self._scored(4, "部分按需选型：使用两类数据库", evidence)
        elif len(db_types) >= 2:
            # 同类别多种数据库
            return self._scored(3, "使用多种数据库但类别单一", evidence)
        elif len(db_types) == 1:
            return self._scored(2, "单一通用：所有场景使用同一种数据库", evidence)
        else:
            return self._not_scored("未检测到数据库使用", evidence)


class DataMigrationStrategy(Analyzer):
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
        
        # 取最新的配置记录
        record = records[0]
        
        evidence = []
        capabilities = []
        
        if record.has_capability:
            evidence.append("✓ 具备在线数据迁移能力")
            capabilities.append("基础能力")
        
        if record.supports_dual_write:
            evidence.append("✓ 支持双写")
            capabilities.append("双写")
        
        if record.supports_grayscale:
            evidence.append("✓ 支持灰度切换")
            capabilities.append("灰度")
        
        if record.supports_online_ddl:
            evidence.append("✓ 支持在线 DDL")
            capabilities.append("OnlineDDL")
        
        if record.tools_used:
            evidence.append(f"使用工具: {', '.join(record.tools_used)}")
        
        if record.evidence:
            evidence.append(f"证据: {record.evidence}")
        
        # 评分逻辑
        score = 0
        if record.has_capability:
            score += 2
        if record.supports_dual_write:
            score += 1
        if record.supports_grayscale:
            score += 1
        if record.supports_online_ddl:
            score += 1
        
        score = min(score, 5)
        
        if score >= 4:
            return self._scored(5, "在线数据迁移能力完备", evidence)
        elif score >= 2:
            return self._scored(score, "具备部分在线迁移能力", evidence)
        elif score > 0:
            return self._scored(score, "在线迁移能力有限", evidence)
        else:
            return self._not_scored("不具备在线数据迁移能力", evidence)


class DataOwnershipClear(Analyzer):
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
        
        evidence = [f"数据表/集合数: {len(records)}"]
        
        # 统计所有权明确度
        has_owner = [r for r in records if r.owner_service]
        via_api = [r for r in records if r.access_via_api]
        
        evidence.append(f"有明确 Owner: {len(has_owner)} 个")
        evidence.append(f"通过 API 访问: {len(via_api)} 个")
        
        # 从 APM 数据辅助验证
        if store.available("apm.service.db.mapping"):
            mappings: list[ApmServiceDbMappingRecord] = store.get("apm.service.db.mapping")
            
            # 检查是否有多个服务写同一数据库
            write_services = {}
            for m in mappings:
                if m.access_type in ("write_only", "read_write"):
                    db_key = m.database_name
                    if db_key not in write_services:
                        write_services[db_key] = set()
                    write_services[db_key].add(m.service_name)
            
            multi_writer_dbs = [db for db, svcs in write_services.items() if len(svcs) > 1]
            if multi_writer_dbs:
                evidence.append(f"多写入者数据库: {len(multi_writer_dbs)} 个（需关注）")
        
        # 评分逻辑
        total = len(records)
        if total == 0:
            return self._not_scored("无数据所有权配置", evidence)
        
        owner_ratio = len(has_owner) / total
        api_ratio = len(via_api) / total
        
        if owner_ratio >= 0.9 and api_ratio >= 0.8:
            return self._scored(5, "数据所有权明确：每个表有唯一写入者，API 访问", evidence)
        elif owner_ratio >= 0.7 and api_ratio >= 0.5:
            return self._scored(4, "数据所有权较明确", evidence)
        elif owner_ratio >= 0.5:
            return self._scored(3, "部分数据有明确所有权", evidence)
        elif owner_ratio > 0:
            return self._scored(2, "数据所有权不够明确", evidence)
        else:
            return self._not_scored("数据所有权不明确", evidence)


# 导出所有分析器
DATA_MGMT_ANALYZERS = [
    DataArchitecturePattern(),
    DataConsistencyModel(),
    DbPolyglotUsage(),
    DataMigrationStrategy(),
    DataOwnershipClear(),
]
