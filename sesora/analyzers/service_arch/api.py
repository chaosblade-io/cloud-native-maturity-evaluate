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
from ...schema.k8s import K8sIngressRecord, IstioGatewayRecord, K8sNetworkPolicyRecord, K8sServiceRecord
from ...schema.apm import ApmServiceRecord
import re


class ApiGatewayUsageAnalyzer(Analyzer):
    """
    API 网关统一入口分析器

    评估标准：所有外部流量是否必须经过 API 网关进行路由、认证、限流和日志记录，无直连后端服务。

    数据来源：
    - K8s Ingress（UModel 已有）
    - K8s Service：检查是否存在 LoadBalancer/NodePort 类型（直连后端）
    - NetworkPolicy：检查是否有规则限制后端服务只能被网关访问
    - Istio Gateway（可选）

    评分细则（满分 8 分）：
    - 有 Ingress 网关入口: +3 分
    - HTTPS/TLS 启用: +1 分（基础安全要求）
    - Istio Gateway（服务网格）: +1 分
    - 无直连后端服务（关键）: +3 分
      - 检查 Service 类型无 LoadBalancer/NodePort
      - NetworkPolicy 有效限制入站流量
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
        return ["k8s.istio.gateway.list", "k8s.networkpolicy.list", "k8s.service.list"]

    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")

        evidence = []
        raw_score = 0

        if not ingresses:
            return self._not_scored("未配置 Ingress 网关", [])

        evidence.append(f"Ingress 数量: {len(ingresses)}")
        raw_score += 3

        https_ingresses = [i for i in ingresses if i.tls_enabled]
        if https_ingresses:
            evidence.append(f"启用 HTTPS: {len(https_ingresses)} 个")
            raw_score += 1
        else:
            evidence.append("警告: 未启用 HTTPS/TLS")

        if store.available("k8s.istio.gateway.list"):
            gateways: list[IstioGatewayRecord] = store.get("k8s.istio.gateway.list")
            if gateways:
                evidence.append(f"Istio Gateway: {len(gateways)} 个")
                raw_score += 1

        direct_exposure_score = 0
        direct_exposure_issues = []

        if store.available("k8s.service.list"):
            services: list[K8sServiceRecord] = store.get("k8s.service.list")
            exposed_services = [s for s in services if s.type in ("LoadBalancer", "NodePort")]
            if exposed_services:
                direct_exposure_issues.append(
                    f"存在 {len(exposed_services)} 个直接暴露的 Service ({', '.join(set(s.type for s in exposed_services))})")
            else:
                direct_exposure_score += 2
                evidence.append("所有 Service 均为 ClusterIP，无直接暴露")
        else:
            evidence.append("未获取 Service 列表，无法检查直连后端")

        if store.available("k8s.networkpolicy.list"):
            policies: list[K8sNetworkPolicyRecord] = store.get("k8s.networkpolicy.list")
            if policies:
                ingress_policies = [p for p in policies if "Ingress" in p.policy_types]
                if ingress_policies:
                    direct_exposure_score += 1
                    evidence.append(f"NetworkPolicy 入站限制: {len(ingress_policies)} 个规则")
                else:
                    evidence.append("NetworkPolicy 存在但未配置入站限制")
            else:
                evidence.append("未配置 NetworkPolicy")
        else:
            evidence.append("未获取 NetworkPolicy 数据")

        if direct_exposure_issues:
            evidence.extend(direct_exposure_issues)
        raw_score += direct_exposure_score

        if raw_score >= 8:
            final_score = 8
            conclusion = "API 网关统一入口配置完善，无直连后端"
        elif raw_score >= 6:
            final_score = 7
            conclusion = "API 网关配置良好，基本无直连后端"
        elif raw_score >= 4:
            final_score = 5
            conclusion = "API 网关基本配置，部分流量管控"
        elif raw_score >= 2:
            final_score = 3
            conclusion = "有网关入口但存在直连后端风险"
        else:
            final_score = raw_score
            conclusion = "API 网关配置有限或存在直连后端"

        return self._scored(final_score, conclusion, evidence)


class ApiStyleModernityAnalyzer(Analyzer):
    """
    API 风格现代化分析器

    评估标准：
    - 混合/先进 (5): 根据场景合理使用 gRPC (内部高性能), GraphQL (复杂查询), RESTful (外部标准)
    - 标准 (3): 主要使用 RESTful
    - 陈旧 (1): 仍大量使用 SOAP 或非标准 RPC
    - 无 (0): 无 API

    数据来源：
    - APM Service：telemetry_client/service_type 字段判断协议类型
    - APM Topology：调用类型分布（用于估算协议使用比例）

    评分细则（满分 5 分）：
    - 5分：gRPC + REST + GraphQL 三者场景化合理使用
    - 4分：gRPC + REST 且比例合理（内部:gRPC, 外部:REST）
    - 3分：纯 RESTful 或现代协议混合但不完整
    - 2分：仅有 gRPC（缺少外部标准接口）或 GraphQL 为主
    - 1分：传统 RPC (Dubbo2/Thrift) 为主
    - 0分：SOAP 或未检测到 API
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
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if not isinstance(services, list) or not services:
            return self._not_evaluated("未获取到有效的 APM 服务列表")

        protocol_counts = {
            "gRPC": 0,
            "GraphQL": 0,
            "REST": 0,
            "RPC": 0,
            "SOAP": 0,
            "WebSocket": 0,
        }
        legacy_rpc_services = []
        soap_services = []

        def detect_protocol(type_str: str) -> str | None:
            if not type_str:
                return None
            s = type_str.lower()
            if "grpc" in s or "triple" in s:
                return "gRPC"
            if "graphql" in s or "graph-ql" in s:
                return "GraphQL"
            if "websocket" in s or "ws" in s:
                return "WebSocket"
            if "soap" in s:
                return "SOAP"
            if "dubbo" in s and "triple" not in s:
                return "RPC"
            if any(rpc in s for rpc in ["thrift", "brpc", "srpc"]) or ("rpc" in s and "grpc" not in s):
                return "RPC"
            if any(x in s for x in ["http", "rest", "web"]):
                return "REST"
            return None

        for svc in services:
            svc_name = svc.service_name
            p = detect_protocol(svc.service_type)
            if p:
                protocol_counts[p] += 1
                if p == "RPC":
                    legacy_rpc_services.append(svc_name)
                elif p == "SOAP":
                    soap_services.append(svc_name)

        if store.available("apm.topology.metrics"):
            metrics = store.get("apm.topology.metrics")
            if isinstance(metrics, list):
                for m in metrics:
                    call_type = m.call_type.upper() if m.call_type else ""
                    if "GRPC" in call_type or "TRIPLE" in call_type:
                        protocol_counts["gRPC"] += 1
                    elif "GRAPHQL" in call_type:
                        protocol_counts["GraphQL"] += 1
                    elif "DUBBO" in call_type:
                        protocol_counts["RPC"] += 1
                    elif "THRIFT" in call_type or "BRPC" in call_type:
                        protocol_counts["RPC"] += 1
                    elif "SOAP" in call_type:
                        protocol_counts["SOAP"] += 1
                    elif "HTTP" in call_type:
                        protocol_counts["REST"] += 1
                    elif "WEBSOCKET" in call_type or "WS" in call_type:
                        protocol_counts["WebSocket"] += 1

        detected_protocols = [p for p, c in protocol_counts.items() if c > 0]
        evidence = [
            f"服务总数: {len(services)}",
            f"检测到的协议: {', '.join(f'{p}({protocol_counts[p]})' for p in detected_protocols) if detected_protocols else '无'}"
        ]
        if legacy_rpc_services:
            evidence.append(f"传统 RPC 服务示例: {', '.join(legacy_rpc_services[:3])}")
        if soap_services:
            evidence.append(f"SOAP 服务示例: {', '.join(soap_services[:3])}")

        has_grpc = protocol_counts["gRPC"] > 0
        has_graphql = protocol_counts["GraphQL"] > 0
        has_rest = protocol_counts["REST"] > 0
        has_rpc = protocol_counts["RPC"] > 0
        has_soap = protocol_counts["SOAP"] > 0
        has_websocket = protocol_counts["WebSocket"] > 0

        total_services = sum(protocol_counts.values())
        if total_services == 0:
            return self._not_scored("未检测到明确的 API 风格", evidence)

        grpc_ratio = protocol_counts["gRPC"] / total_services if total_services > 0 else 0
        rest_ratio = protocol_counts["REST"] / total_services if total_services > 0 else 0
        rpc_ratio = protocol_counts["RPC"] / total_services if total_services > 0 else 0

        if has_soap:
            return self._scored(1, "陈旧架构：检测到 SOAP 协议", evidence)

        if rpc_ratio >= 0.5:
            return self._scored(1, "需重构：传统 RPC 占主导", evidence)

        if has_grpc and has_rest and has_graphql:
            min_ratio = min(grpc_ratio, rest_ratio, protocol_counts["GraphQL"] / total_services)
            if min_ratio >= 0.1:
                return self._scored(5, "最佳实践：gRPC + REST + GraphQL 场景化合理使用", evidence)
            else:
                return self._scored(4, "优秀：三种现代协议混合，建议优化比例", evidence)

        if has_grpc and has_rest:
            if grpc_ratio >= 0.3 and rest_ratio >= 0.3:
                return self._scored(5, "最佳实践：gRPC + REST 场景化合理使用", evidence)
            else:
                return self._scored(4, "优秀：gRPC + REST 混合架构", evidence)

        if has_grpc and not has_rest:
            return self._scored(2, "一般：主要使用 gRPC，建议增加 RESTful 对外接口", evidence)

        if has_graphql and not has_grpc and not has_rest:
            return self._scored(2, "一般：主要使用 GraphQL，建议评估是否需要 gRPC 高性能场景", evidence)

        if has_rest and not has_grpc and not has_graphql:
            if has_websocket:
                return self._scored(3, "标准：REST + WebSocket，建议评估 gRPC 流式替代", evidence)
            return self._scored(3, "标准：主要使用 RESTful", evidence)

        if has_graphql and has_rest:
            return self._scored(3, "良好：GraphQL + REST，建议评估 gRPC 高性能场景", evidence)

        if has_rpc:
            return self._scored(2, "过渡中：仍有部分传统 RPC 服务", evidence)

        return self._scored(2, "未明确分类的协议组合", evidence)


class ApiDocumentationAutoAnalyzer(Analyzer):
    """
    自动化文档分析器

    评估标准：是否通过代码注解或配置自动生成并实时同步 API 文档 (如 Swagger/OpenAPI)，且文档覆盖率 100%。

    数据来源：
    - Codeup 文件树：API 定义文件、构建配置、注解文件
    - CI/CD 流水线：文档生成、校验、发布步骤

    评分细则（满分 6 分）：
    - 基础分：API 定义文件存在 (+1)
    - 生成能力：代码注解生成文档 (+2)
    - 自动化：CI/CD 集成 (+2)
    - 发布能力：文档托管/可访问 (+1)
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

        if not file_tree:
            return self._not_evaluated("未获取到代码库文件树")

        evidence = []
        raw_score = 0

        # ========== 1. API 定义文件检测 (+1分) ==========
        valid_extensions = ['.yaml', '.yml', '.json']
        spec_keywords = ["swagger", "openapi", "api-spec"]
        valid_spec_files = []

        for f in file_tree:
            if not f.name:
                continue
            name_lower = f.name.lower()
            ext = f.name[f.name.rfind('.'):].lower() if '.' in f.name else ""

            if ext in valid_extensions and any(k in name_lower for k in spec_keywords):
                if not any(x in name_lower for x in ["backup", "old", "test-data", "mock", "example"]):
                    valid_spec_files.append(f.name)

        if valid_spec_files:
            raw_score += 1
            evidence.append(f"API 定义文件: {len(valid_spec_files)} 个 ({', '.join(valid_spec_files[:2])})")
        else:
            evidence.append("未检测到标准 API 定义文件")

        # ========== 2. 文档生成能力检测 (+2分) ==========
        build_files = ["pom.xml", "build.gradle", "package.json", "requirements.txt", "go.mod", "Cargo.toml"]
        generator_libs = ["springfox", "springdoc", "swagger-ui", "fastapi", "drf-yasg", "swag", "utoipa"]

        has_generator_in_build = False
        has_annotation_in_code = False

        for f in file_tree:
            if not f.name:
                continue
            name_lower = f.name.lower()

            if name_lower in build_files:
                pass

            if any(lib in name_lower for lib in generator_libs):
                has_generator_in_build = True
                evidence.append(f"文档生成库配置: {f.name}")

            if f.name.endswith('.java') or f.name.endswith('.py') or f.name.endswith('.go') or f.name.endswith('.rs'):
                if any(ann in name_lower for ann in ["swagger", "openapi", "doc", "api"]):
                    has_annotation_in_code = True

        doc_config_files = [f for f in file_tree
                            if f.name and any(x in f.name.lower() for x in ["swagger", "openapi", "apidoc", "docs"])
                            and any(f.name.endswith(ext) for ext in ['.java', '.py', '.go', '.ts', '.js', '.rs'])]

        if doc_config_files:
            has_annotation_in_code = True
            evidence.append(f"文档注解/配置类: {len(doc_config_files)} 个")

        if has_generator_in_build:
            raw_score += 1
        if has_annotation_in_code:
            raw_score += 1
        elif has_generator_in_build:
            evidence.append("警告: 有文档库但缺少注解实践")

        # ========== 3. CI/CD 自动化检测 (+2分) ==========
        has_doc_generate_step = False
        has_doc_verify_step = False

        if store.available("codeup.pipeline.stages"):
            stages = store.get("codeup.pipeline.stages")
            if isinstance(stages, list):
                generate_keywords = ["generate", "gen", "build", "swagger", "openapi", "apidoc"]
                verify_keywords = ["verify", "validate", "lint", "check", "diff"]

                for s in stages:
                    if not s.stage_name:
                        continue
                    s_name = s.stage_name.lower()

                    if any(k in s_name for k in generate_keywords) and any(
                            d in s_name for d in ["doc", "api", "swagger", "openapi"]):
                        has_doc_generate_step = True
                        evidence.append(f"文档生成步骤: {s.stage_name}")

                    if any(k in s_name for k in verify_keywords) and any(
                            d in s_name for d in ["doc", "api", "swagger", "openapi"]):
                        has_doc_verify_step = True
                        evidence.append(f"文档校验步骤: {s.stage_name}")

                    if any(t in s_name for t in ["swagger-cli", "redocly", "spectral", "openapi-generator"]):
                        has_doc_generate_step = True
                        evidence.append(f"文档工具: {s.stage_name}")

        if has_doc_generate_step:
            raw_score += 1
        else:
            evidence.append("未检测到文档生成步骤")

        if has_doc_verify_step:
            raw_score += 1
        else:
            evidence.append("未检测到文档校验步骤（建议添加一致性校验）")

        # ========== 4. 文档发布/托管检测 (+1分) ==========
        hosting_indicators = ["index.html", "swagger-ui", "redoc", "rapidoc", "docs.html", "api.html"]
        has_doc_hosting = any(
            f.name and any(h in f.name.lower() for h in hosting_indicators)
            for f in file_tree
        )

        static_site_configs = [".github/workflows", "netlify.toml", "vercel.json"]
        has_static_site = any(
            f.name and any(s in f.name.lower() for s in static_site_configs)
            for f in file_tree
        )

        if has_doc_hosting:
            raw_score += 1
            evidence.append("检测到文档托管配置")
        elif has_static_site:
            evidence.append("有静态站点配置，建议集成 API 文档")
        else:
            evidence.append("未检测到文档托管配置")

        if raw_score >= 6:
            final_score = 6
            conclusion = "优秀：全自动化 API 文档体系（生成+校验+发布）"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "良好：自动化文档生成，建议增加校验步骤"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "较好：具备文档生成能力，建议完善 CI/CD 集成"
        elif raw_score >= 2:
            final_score = 3
            conclusion = "一般：有 API 定义文件和基础生成能力"
        elif raw_score >= 1:
            final_score = 2
            conclusion = "起步：仅有 API 定义文件"
        else:
            final_score = 0
            conclusion = "未建立 API 文档体系"

        if raw_score == 0:
            return self._not_scored("未检测到有效的自动化 API 文档体系", evidence)

        return self._scored(final_score, conclusion, evidence)


class ApiVersioningStrategyAnalyzer(Analyzer):
    """
    API 版本控制策略分析器

    评估标准：是否实施了明确的 API 版本管理 (URI 路径、Header 或参数)，支持多版本共存和平滑迁移。

    数据来源：
    - K8s Ingress：路由规则中的版本路径 (/v1, /v2)、Host 版本 (v1.api.example.com)
    - APM：请求路径中的版本号（验证版本活跃度）
    - 代码库：版本弃用策略文档

    评分细则（满分 6 分）：
    - 基础版本化：URI 路径版本 (+2)
    - 多版本支持：同时存在 2+ 活跃版本 (+2)
    - 版本策略完善：Header/Host 版本支持 (+1)
    - 平滑迁移能力：版本弃用策略/灰度机制 (+1)
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

    def optional_data(self) -> list[str]:
        return ["apm.topology.metrics", "codeup.repo.file_tree"]

    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")

        if not ingresses:
            return self._not_evaluated("未配置 Ingress")

        evidence = []
        raw_score = 0

        path_version_regex = re.compile(r'(?:^|/)(?:api/)?v(\d+(?:\.\d+)?)(?:/|$)', re.IGNORECASE)
        host_version_regex = re.compile(r'(?:^|[-.])v(\d+)(?:[-.]|$)', re.IGNORECASE)

        versioned_ingress_ids = set()
        path_version_numbers = set()
        host_version_numbers = set()
        all_version_numbers = set()

        for ing in ingresses:
            rules = ing.rules
            is_versioned = False
            ing_hosts = []

            for rule in rules:
                host = rule.get("host", "")
                if host:
                    ing_hosts.append(host)
                    host_matches = host_version_regex.findall(host)
                    if host_matches:
                        is_versioned = True
                        host_version_numbers.update(host_matches)
                        all_version_numbers.update(host_matches)

                paths = rule.get("paths", [])
                for path_config in paths:
                    path = path_config.get("path", "")
                    if not path:
                        continue

                    path_matches = path_version_regex.findall(path)
                    if path_matches:
                        is_versioned = True
                        path_version_numbers.update(path_matches)
                        all_version_numbers.update(path_matches)

            if is_versioned:
                versioned_ingress_ids.add(ing.name)

        count_versioned = len(versioned_ingress_ids)
        total_count = len(ingresses)

        evidence.append(f"Ingress 总数: {total_count}")

        if count_versioned == 0:
            return self._not_scored("API 未配置版本管理 (URI 路径或 Host)", evidence)

        evidence.append(f"版本化 Ingress: {count_versioned} 个")

        def version_key(v):
            try:
                if '.' in str(v):
                    parts = str(v).split('.')
                    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                return int(v), 0
            except (ValueError, TypeError):
                return 0, 0

        if all_version_numbers:
            sorted_versions = sorted(all_version_numbers, key=version_key)
            evidence.append(f"检测到的版本: v{', v'.join(str(v) for v in sorted_versions)}")

        versioning_ratio = count_versioned / total_count if total_count > 0 else 0

        if versioning_ratio >= 0.8:
            raw_score += 2
            evidence.append("版本化覆盖率: 优秀 (>=80%)")
        elif versioning_ratio >= 0.5:
            raw_score += 1
            evidence.append("版本化覆盖率: 一般 (50%-80%)")
        else:
            evidence.append(f"版本化覆盖率: 较低 ({versioning_ratio:.0%})")

        if path_version_numbers:
            evidence.append(
                f"URI 路径版本: v{', v'.join(str(v) for v in sorted(path_version_numbers, key=version_key))}")
        if host_version_numbers:
            evidence.append(f"Host 版本: v{', v'.join(str(v) for v in sorted(host_version_numbers, key=version_key))}")

        multi_version = len(all_version_numbers) >= 2

        if multi_version:
            active_versions = set()
            if store.available("apm.topology.metrics"):
                metrics = store.get("apm.topology.metrics")
                if isinstance(metrics, list):
                    for m in metrics:
                        call_path = m.path or m.request_uri
                        if call_path:
                            matches = path_version_regex.findall(call_path)
                            active_versions.update(matches)

                    if active_versions:
                        evidence.append(
                            f"活跃版本 (APM): v{', v'.join(str(v) for v in sorted(active_versions, key=version_key))}")
                        if len(active_versions) >= 2:
                            raw_score += 2
                            evidence.append("多版本共存: 多个版本均有活跃流量")
                        else:
                            raw_score += 1
                            evidence.append("多版本共存: 检测到多版本配置，但仅单版本活跃")
                    else:
                        raw_score += 1
                        evidence.append("多版本共存: 配置存在，无法验证活跃度")
            else:
                raw_score += 1
                evidence.append("多版本共存: 配置存在 (未获取 APM 数据验证)")
        else:
            evidence.append("单版本: 仅支持单一 API 版本")

        has_header_versioning = False
        for ing in ingresses:
            annotations = ing.annotations
            if any(k in str(v).lower() for k, v in annotations.items()
                   if 'version' in k.lower() or 'header' in k.lower()):
                has_header_versioning = True
                break

        if has_header_versioning:
            raw_score += 1
            evidence.append("版本策略: 支持 Header 版本控制")
        elif host_version_numbers:
            raw_score += 1
            evidence.append("版本策略: 支持 Host 版本控制")
        else:
            evidence.append("版本策略: 仅支持 URI 路径版本")

        has_deprecation_policy = False
        if store.available("codeup.repo.file_tree"):
            file_tree = store.get("codeup.repo.file_tree")
            if isinstance(file_tree, list):
                policy_keywords = ["deprecation", "versioning-policy", "api-lifecycle", "migration", "sunset"]
                for f in file_tree:
                    if f.name and any(k in f.name.lower() for k in policy_keywords):
                        has_deprecation_policy = True
                        evidence.append(f"版本策略文档: {f.name}")
                        break

        has_canary = False
        for ing in ingresses:
            annotations = ing.annotations
            if any(k in str(v).lower() for k, v in annotations.items()
                   if any(x in str(v).lower() for x in ['canary', 'gray', 'weight', 'traffic'])):
                has_canary = True
                break

        if has_deprecation_policy:
            raw_score += 1
            evidence.append("平滑迁移: 有版本弃用策略文档")
        elif has_canary:
            raw_score += 1
            evidence.append("平滑迁移: 有灰度发布配置")
        else:
            evidence.append("平滑迁移: 未检测到弃用策略或灰度机制")

        if raw_score >= 6:
            final_score = 6
            conclusion = "API 版本管理完善：多版本共存 + 平滑迁移机制"
        elif raw_score >= 5:
            final_score = 5
            conclusion = "API 版本管理规范：支持多版本，建议完善迁移策略"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "API 版本管理良好：基础版本化 + 多版本支持"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "API 版本管理一般：有基础版本化，建议增加多版本支持"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "API 版本管理起步：基础版本化已配置"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "API 版本管理有限：部分接口有版本控制"
        else:
            final_score = 0
            conclusion = "API 版本管理缺失"

        return self._scored(final_score, conclusion, evidence)


class ApiContractTestingAnalyzer(Analyzer):
    """
    API 契约测试分析器

    评估标准：是否在 CI/CD 流水线中实施了消费者驱动契约测试 (CDC, 如 Pact)，防止接口变更导致调用方失败。

    数据来源：
    - CI/CD 流水线：契约测试执行步骤（Consumer 测试、Provider 验证）
    - 代码库：契约文件、Broker 配置、测试代码

    评分细则（满分 5 分）：
    - 基础能力：有契约测试文件 (+1)
    - CI/CD 集成：流水线中执行契约测试 (+1)
    - 双向验证：Consumer 测试 + Provider 验证 (+2)
    - Broker 集成：契约 Broker 存储与协调 (+1)
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
        raw_score = 0

        # ========== 1. 契约文件检测 (+1分) ==========
        pact_files = []
        spring_contract_files = []

        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

            for f in file_tree:
                name_lower = (f.name or "").lower()
                path_lower = (f.path or "").lower()

                is_pact_file = (
                        name_lower.endswith(('.json', '.yml', '.yaml')) and
                        any(kw in name_lower for kw in ['pact', 'interaction']) and
                        not any(x in name_lower for x in ['package', 'lock', 'node_modules'])
                )
                is_pact_path = '/pacts/' in path_lower or '/pact/' in path_lower

                is_scc_file = name_lower.endswith('.groovy') and 'contract' in name_lower
                is_scc_path = '/contracts/' in path_lower

                if is_pact_file or is_pact_path:
                    pact_files.append(f)
                elif is_scc_file or is_scc_path:
                    spring_contract_files.append(f)

            contract_files = pact_files + spring_contract_files

            if contract_files:
                raw_score += 1
                if pact_files:
                    evidence.append(f"Pact 契约文件: {len(pact_files)} 个")
                if spring_contract_files:
                    evidence.append(f"Spring Cloud Contract: {len(spring_contract_files)} 个")
            else:
                evidence.append("未检测到契约测试文件")

        # ========== 2. CI/CD 集成检测 (+1分) ==========
        consumer_keywords = ['pact:publish', 'pact-verify-consumer', 'consumer-test', 'contract:generate']
        provider_keywords = ['pact:verify', 'provider-verification', 'verify-contracts', 'pact-verify-provider']
        broker_keywords = ['pact-broker', 'broker-publish', 'can-i-deploy']

        consumer_stages = []
        provider_stages = []
        broker_stages = []

        for stage in stages:
            stage_name_lower = (stage.stage_name or "").lower()
            commands_list = stage.commands or []
            commands_str = " ".join(commands_list).lower()
            combined_text = stage_name_lower + " " + commands_str

            if any(kw in combined_text for kw in consumer_keywords):
                consumer_stages.append(stage)
            elif any(kw in combined_text for kw in provider_keywords):
                provider_stages.append(stage)
            elif any(kw in combined_text for kw in broker_keywords):
                broker_stages.append(stage)
            elif any(kw in combined_text for kw in ['pact', 'contract', '契约', 'cdc']):
                consumer_stages.append(stage)

        has_consumer_test = len(consumer_stages) > 0
        has_provider_verify = len(provider_stages) > 0
        has_broker = len(broker_stages) > 0

        if has_consumer_test or has_provider_verify:
            raw_score += 1
            if consumer_stages:
                evidence.append(f"Consumer 契约测试: {len(consumer_stages)} 个阶段")
            if provider_stages:
                evidence.append(f"Provider 验证: {len(provider_stages)} 个阶段")
        else:
            evidence.append("CI/CD 未集成契约测试")

        # ========== 3. 双向验证检测 (+2分) ==========
        if has_consumer_test and has_provider_verify:
            raw_score += 2
            evidence.append("双向验证: Consumer 测试 + Provider 验证")
        elif has_consumer_test:
            raw_score += 1
            evidence.append("单向验证: 仅有 Consumer 测试，建议增加 Provider 验证")
        elif has_provider_verify:
            raw_score += 1
            evidence.append("单向验证: 仅有 Provider 验证，建议增加 Consumer 测试")
        else:
            evidence.append("未检测到契约验证")

        # ========== 4. Broker 集成检测 (+1分) ==========
        if has_broker:
            raw_score += 1
            evidence.append("Broker 集成: 有契约 Broker 配置")
        else:
            if store.available("codeup.repo.file_tree"):
                file_tree = store.get("codeup.repo.file_tree")
                broker_config_found = any(
                    f.name and any(kw in f.name.lower() for kw in ['pact-broker', 'broker.yml', 'broker.yaml'])
                    for f in file_tree
                )
                if broker_config_found:
                    raw_score += 1
                    evidence.append("Broker 集成: 检测到 Broker 配置文件")
                else:
                    evidence.append("Broker: 未检测到契约 Broker 配置")

        if raw_score >= 5:
            final_score = 5
            conclusion = "优秀：完整的 CDC 体系（Consumer+Provider+Broker）"
        elif raw_score >= 4:
            final_score = 4
            conclusion = "良好：双向验证已配置，建议集成 Broker"
        elif raw_score >= 3:
            final_score = 3
            conclusion = "较好：CI/CD 集成契约测试，建议完善双向验证"
        elif raw_score >= 2:
            final_score = 2
            conclusion = "一般：有契约文件和基础 CI/CD 集成"
        elif raw_score >= 1:
            final_score = 1
            conclusion = "起步：有契约测试文件但未集成 CI/CD"
        else:
            final_score = 0
            conclusion = "未实施契约测试"

        if raw_score == 0:
            return self._not_scored("未检测到契约测试配置或相关文件", evidence)

        return self._scored(final_score, conclusion, evidence)


API_ANALYZERS = [
    ApiGatewayUsageAnalyzer(),
    ApiStyleModernityAnalyzer(),
    ApiDocumentationAutoAnalyzer(),
    ApiVersioningStrategyAnalyzer(),
    ApiContractTestingAnalyzer(),
]
