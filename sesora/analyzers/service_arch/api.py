"""
Service Architecture 维度 - API 设计与治理分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                   |
| ------------------------- | ---- | ---------------------------------------------------------- |
| api_gateway_usage         | 8    | API 网关统一入口：所有外部流量必须经过 API 网关            |
| api_style_modernity       | 0-5  | API 风格现代化：混合/先进(5)/标准(3)/陈旧(1)/无(0)         |
| api_documentation_auto    | 6    | 自动化文档：通过代码注解自动生成 API 文档，覆盖率 100%     |
| api_versioning_strategy   | 6    | 版本控制策略：明确的 API 版本管理，支持多版本共存          |
| api_contract_testing      | 5    | 契约测试：CI/CD 中实施消费者驱动契约测试                   |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema import CodeupPipelineStageRecord, CodeupRepoFileTreeRecord
from ...schema.k8s import K8sIngressRecord, IstioGatewayRecord, K8sNetworkPolicyRecord
from ...schema.apm import ApmServiceRecord, ApmTopologyMetricsRecord
import re


class ApiGatewayUsage(Analyzer):
    """
    API 网关统一入口分析器
    
    评估标准：所有外部流量是否必须经过 API 网关进行路由、认证、限流和日志记录，无直连后端服务。
    
    数据来源：
    - K8s Ingress（UModel 已有）
    - NetworkPolicy：检查是否有规则限制后端服务只能被网关访问
    - Istio Gateway（可选）
    """
    
    def key(self) -> str:
        return "api_gateway_usage"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "API设计与治理"
    
    def max_score(self) -> int:
        return 8
    
    def required_data(self) -> list[str]:
        return ["k8s.ingress.list"]
    
    def optional_data(self) -> list[str]:
        return ["k8s.istio.gateway.list", "k8s.networkpolicy.list"]
    
    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")
        
        evidence = []
        score = 0
        
        if not ingresses:
            return self._not_scored("未配置 Ingress 网关", [])
        
        evidence.append(f"Ingress 数量: {len(ingresses)}")
        score += 3  # 有 Ingress 网关入口
        
        # 检查是否启用 HTTPS/TLS
        https_ingresses = [i for i in ingresses if i.tls_enabled]
        if https_ingresses:
            evidence.append(f"启用 HTTPS: {len(https_ingresses)} 个")
            score += 2
        
        # 检查 Istio Gateway（服务网格网关）
        if store.available("k8s.istio.gateway.list"):
            gateways: list[IstioGatewayRecord] = store.get("k8s.istio.gateway.list")
            if gateways:
                evidence.append(f"Istio Gateway: {len(gateways)} 个")
                score += 1
        
        # 检查 NetworkPolicy（限制直连后端）
        if store.available("k8s.networkpolicy.list"):
            policies: list[K8sNetworkPolicyRecord] = store.get("k8s.networkpolicy.list")
            if policies:
                evidence.append(f"NetworkPolicy 规则: {len(policies)} 个")
                score += 2
        
        # 评分判断
        score = min(score, 8)
        if score >= 7:
            return self._scored(8, "API 网关统一入口配置完善，无直连后端", evidence)
        elif score >= 5:
            return self._scored(6, "API 网关基本配置，部分流量管控", evidence)
        elif score >= 3:
            return self._scored(4, "有网关入口但缺少完整流量管控", evidence)
        else:
            return self._scored(score, "API 网关配置有限", evidence)


class ApiStyleModernity(Analyzer):
    """
    API 风格现代化分析器
    
    评估标准：
    - 混合/先进 (5): 根据场景合理使用 gRPC (内部高性能), GraphQL (复杂查询), RESTful (外部标准)
    - 标准 (3): 主要使用 RESTful
    - 陈旧 (1): 仍大量使用 SOAP 或非标准 RPC
    - 无 (0): 无 API
    
    数据来源：
    - APM Service：telemetry_client 字段判断协议类型
    - APM Topology：调用类型分布
    """
    
    def key(self) -> str:
        return "api_style_modernity"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "API设计与治理"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["apm.service.list"]
    
    def optional_data(self) -> list[str]:
        return ["apm.topology.metrics"]

    def analyze(self, store) -> ScoreResult:
        # 1. 安全获取数据
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if not isinstance(services, list) or not services:
            return self._not_evaluated("未获取到有效的 APM 服务列表")

        protocols = set()
        legacy_rpc_services = []

        # 2. 定义安全的匹配函数
        def detect_protocol(type_str: str) -> str | None:
            if not type_str:
                return None
            s = type_str.lower()
            if "grpc" in s:
                return "gRPC"
            if "dubbo" in s:
                return "RPC"
            if "rpc" in s and "grpc" not in s:
                return "RPC"
            if any(x in s for x in ["http", "rest", "web"]):
                return "REST"
            return None

        # 3. 分析服务列表
        for svc in services:
            p = detect_protocol(svc.service_type)
            if p:
                protocols.add(p)
                if p == "RPC":
                    legacy_rpc_services.append(svc.name if hasattr(svc, 'name') else str(svc))

        if store.available("apm.topology.metrics"):
            metrics = store.get("apm.topology.metrics")
            if isinstance(metrics, list):
                for m in metrics:
                    call_type = m.call_type.upper() if m.call_type else ""
                    if "GRPC" in call_type:
                        protocols.add("gRPC")
                    elif "DUBBO" in call_type or ("RPC" in call_type and "GRPC" not in call_type):
                        protocols.add("RPC")
                    elif "HTTP" in call_type:
                        protocols.add("REST")

        evidence = [
            f"服务总数: {len(services)}",
            f"检测到的协议类型: {', '.join(sorted(protocols)) if protocols else '未知'}"
        ]
        if legacy_rpc_services:
            sample = legacy_rpc_services[:5]
            evidence.append(f"检测到使用传统 RPC 的服务示例: {', '.join(sample)}")

        has_grpc = "gRPC" in protocols
        has_rest = "REST" in protocols
        has_legacy_rpc = "RPC" in protocols

        if has_grpc and has_legacy_rpc:
            return self._scored(3, "混合架构：包含 gRPC 但仍有传统 RPC 服务", evidence)
        elif has_grpc and has_rest:
            # 纯现代协议混合
            return self._scored(5, "最佳实践：合理使用 gRPC + RESTful", evidence)
        elif has_grpc:
            return self._scored(4, "优秀：主要使用 gRPC 高性能协议", evidence)
        elif has_rest:
            return self._scored(3, "标准：主要使用 RESTful", evidence)
        elif has_legacy_rpc:
            return self._scored(1, "需重构：检测到传统/非标准 RPC 协议", evidence)
        else:
            return self._not_scored("未检测到明确的 API 风格", evidence)

class ApiDocumentationAuto(Analyzer):
    """
    自动化文档分析器
    
    评估标准：是否通过代码注解或配置自动生成并实时同步 API 文档 (如 Swagger/OpenAPI)，且文档覆盖率 100%。
    
    数据来源：
    - API 网关：检查是否集成 OpenAPI 文档自动同步
    - CI/CD 流水线：是否有文档生成步骤
    """
    
    def key(self) -> str:
        return "api_documentation_auto"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "API设计与治理"
    
    def max_score(self) -> int:
        return 6
    
    def required_data(self) -> list[str]:
        return ["codeup.repo.file_tree"]
    
    def optional_data(self) -> list[str]:
        return ["codeup.pipeline.stages"]

    def analyze(self, store) -> ScoreResult:
        file_tree = store.get("codeup.repo.file_tree")

        if not isinstance(file_tree, list) or not file_tree:
            return self._not_evaluated("未获取到代码库文件树")

        evidence = []
        has_valid_spec = False
        has_generator_lib = False
        has_automation_pipeline = False

        valid_extensions = ['.yaml', '.yml', '.json']
        spec_keywords = ["swagger", "openapi", "api-spec"]

        valid_spec_files = []
        for f in file_tree:
            if not f.name: continue
            name_lower = f.name.lower()
            ext = f.name[f.name.rfind('.'):].lower() if '.' in f.name else ""

            if ext in valid_extensions and any(k in name_lower for k in spec_keywords):
                if not any(x in name_lower for x in ["backup", "old", "test-data", "mock"]):
                    valid_spec_files.append(f.name)

        if valid_spec_files:
            has_valid_spec = True
            evidence.append(f"发现标准 API 定义文件: {', '.join(valid_spec_files[:3])}")

        lib_indicators = ["pom.xml", "build.gradle", "package.json", "requirements.txt"]
        generator_libs = ["springfox", "springdoc", "swagger-ui", "fastapi", "drf-yasg"]

        for f in file_tree:
            if not f.name: continue
            name_lower = f.name.lower()
            # 检查构建文件内容中是否包含相关库 (如果能获取内容最好，这里仅通过文件名推测配置目录)
            # 更准确的做法是扫描构建文件内容，这里假设如果有 swagger-config 类文件存在
            if any(lib in name_lower for lib in generator_libs) and (
                    "config" in name_lower or "dependency" in name_lower or name_lower.endswith(
                    ".xml") or name_lower.endswith(".gradle")):
                has_generator_lib = True
                evidence.append(f"检测到文档生成库配置线索: {f.name}")
                break

        if not has_generator_lib:
            for f in file_tree:
                if f.name and ("springdoc" in f.name.lower() or "springfox" in f.name.lower()):
                    has_generator_lib = True
                    evidence.append(f"检测到文档库引用: {f.name}")
                    break

        if store.available("codeup.pipeline.stages"):
            stages = store.get("codeup.pipeline.stages")
            if isinstance(stages, list):
                automation_keywords = ["generate", "build", "publish", "deploy-swagger", "openapi-gen"]
                doc_keywords = ["swagger", "openapi", "api-doc"]

                for s in stages:
                    if not s.stage_name: continue
                    s_name = s.stage_name.lower()
                    if any(d in s_name for d in doc_keywords) and any(a in s_name for a in automation_keywords):
                        has_automation_pipeline = True
                        evidence.append(f"检测到自动化文档流水线阶段: {s.stage_name}")
                        break
                    if "swagger-cli" in s_name or "redocly" in s_name:
                        has_automation_pipeline = True
                        evidence.append(f"检测到文档工具调用: {s.stage_name}")
                        break

        if has_valid_spec and has_generator_lib and has_automation_pipeline:
            return self._scored(6, "优秀：具备全自动化的 API 文档生成流水线", evidence)
        elif has_valid_spec and has_generator_lib:
            return self._scored(4, "良好：具备自动生成能力，建议接入 CI/CD", evidence)
        elif has_valid_spec:
            return self._scored(2, "一般：存在 API 定义文件，但疑似手动维护", evidence)
        elif has_generator_lib or (store.available("codeup.pipeline.stages") and any(
                "doc" in (s.stage_name or "").lower() for s in store.get("codeup.pipeline.stages", []))):
            return self._scored(1, "起步：检测到文档相关配置，但未发现有效定义文件", evidence)
        else:
            return self._not_scored("未检测到有效的自动化 API 文档体系", evidence)

class ApiVersioningStrategy(Analyzer):
    """
    版本控制策略分析器
    
    评估标准：是否实施了明确的 API 版本管理 (URI 路径、Header 或参数)，支持多版本共存和平滑迁移。
    
    数据来源：
    - K8s Ingress：路由规则中的版本路径 (/v1, /v2)
    - APM：请求路径中的版本号
    """
    
    def key(self) -> str:
        return "api_versioning_strategy"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "API设计与治理"
    
    def max_score(self) -> int:
        return 6
    
    def required_data(self) -> list[str]:
        return ["k8s.ingress.list"]

    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")

        if not ingresses:
            return self._not_evaluated("未配置 Ingress")

        version_regex = re.compile(r'(?:^|/)(?:api/)?v(\d+)(?:/|$)', re.IGNORECASE)

        versioned_ingress_ids = set()  # 2. 使用 set 去重，存储唯一标识
        version_numbers = set()

        for ing in ingresses:
            rules = ing.rules
            is_versioned = False

            for rule in rules:
                paths = rule.get("paths", [])
                for path_config in paths:
                    path = path_config["path"]
                    if not path:
                        continue

                    matches = version_regex.findall(path)
                    if matches:
                        is_versioned = True
                        version_numbers.update(matches)

            if is_versioned:
                unique_id = getattr(ing, 'name', None) or getattr(ing, 'uid', None) or str(ing)
                versioned_ingress_ids.add(unique_id)

        count_versioned = len(versioned_ingress_ids)
        total_count = len(ingresses)

        evidence = [f"Ingress 总数: {total_count}"]

        if count_versioned == 0:
            return self._not_scored("API 路径未包含有效的版本信息 (如 /v1, /api/v2)", evidence)

        evidence.append(f"版本化 Ingress: {count_versioned} 个")
        if version_numbers:
            sorted_versions = sorted(version_numbers, key=int)  # 按数字大小排序而非字符串
            evidence.append(f"检测到的版本: v{', v'.join(sorted_versions)}")

        ratio = count_versioned / total_count
        multi_version = len(version_numbers) >= 2

        if ratio >= 0.8 and multi_version:
            return self._scored(6, "API 版本管理完善，支持多版本共存", evidence)
        elif ratio >= 0.8:
            return self._scored(5, "API 版本管理规范", evidence)
        elif ratio >= 0.5:
            return self._scored(4, "部分 API 有版本管理", evidence)
        else:
            return self._scored(2, "API 版本管理有限", evidence)

class ApiContractTesting(Analyzer):
    """
    契约测试分析器
    
    评估标准：是否在 CI/CD 流水线中实施了消费者驱动契约测试 (CDC, 如 Pact)，防止接口变更导致调用方失败。
    
    数据来源：
    - CI/CD 流水线：检查是否存在 Pact 或类似契约测试工具的执行步骤
    """
    
    def key(self) -> str:
        return "api_contract_testing"
    
    def dimension(self) -> str:
        return "Service Architecture"
    
    def category(self) -> str:
        return "API设计与治理"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["codeup.pipeline.stages"]
    
    def optional_data(self) -> list[str]:
        return ["codeup.repo.file_tree"]

    def analyze(self, store) -> ScoreResult:
        stages: list[CodeupPipelineStageRecord] = store.get("codeup.pipeline.stages")

        if not stages:
            return self._not_evaluated("未获取到流水线阶段信息")

        evidence = []

        # 扩展关键词，包含常见的构建工具任务名
        contract_keywords = [
            "pact", "contract", "契约", "cdc", "spring-cloud-contract",
            "consumer-driven", "provider-verification",
            "pact:verify", "pact-publish", "verify-contracts"  # 新增具体任务名
        ]

        contract_stages = []
        for stage in stages:
            stage_name_lower = (stage.stage_name or "").lower()
            # 确保 commands 是列表且不为空
            commands_list = stage.commands or []
            commands_str = " ".join(commands_list).lower()

            # 增加对命令中调用脚本内容的简单启发式判断（如果命令是执行脚本）
            is_contract_stage = any(kw in stage_name_lower or kw in commands_str for kw in contract_keywords)

            if is_contract_stage:
                contract_stages.append(stage)

        if contract_stages:
            evidence.append(f"检测到契约测试阶段: {len(contract_stages)} 个")
            for s in contract_stages:
                evidence.append(f"  - {s.stage_name}")
            return self._scored(5, "CI/CD 中实施消费者驱动契约测试", evidence)

        # 检查代码库中是否有契约测试相关文件
        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

            contract_files = []
            for f in file_tree:
                name_lower = (f.name or "").lower()
                path_lower = (f.path or "").lower()  # 假设 record 有 path 属性

                # 策略优化：
                # 1. 文件名包含关键词 且 是常见测试文件格式
                # 2. 或者 路径中包含典型的契约测试目录 (pacts, contracts)
                is_match_name = any(kw in name_lower for kw in ["pact", "contract"]) and name_lower.endswith(
                    ('.json', '.yml', '.yaml', '.groovy'))
                is_match_path = "/pacts/" in path_lower or "/contracts/" in path_lower or "/pact/" in path_lower

                if is_match_name or is_match_path:
                    # 排除明显的非代码文件 (可选)
                    if not name_lower.endswith(('.md', '.txt', '.log')):
                        contract_files.append(f)

            if contract_files:
                evidence.append(f"检测到契约测试相关文件: {len(contract_files)} 个 (未在 CI 中发现执行阶段)")
                # 列出前几个文件作为证据，避免证据过长
                for f in contract_files[:5]:
                    evidence.append(f"  - {f.path or f.name}")
                if len(contract_files) > 5:
                    evidence.append(f"  ... 还有 {len(contract_files) - 5} 个文件")

                return self._scored(3, "有契约测试文件，但未集成到 CI/CD", evidence)

        evidence.append("未检测到契约测试配置或相关文件")
        return self._not_scored("未实施契约测试", evidence)

# 导出所有分析器
API_ANALYZERS = [
    ApiGatewayUsage(),
    ApiStyleModernity(),
    ApiDocumentationAuto(),
    ApiVersioningStrategy(),
    ApiContractTesting(),
]
