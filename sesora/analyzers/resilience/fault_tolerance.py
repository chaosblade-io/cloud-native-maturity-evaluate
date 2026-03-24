"""
Resilience 维度 - 容错能力 (Fault Tolerance) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)            | 分值 | 评分标准                                                       |
| ft_circuit_breaker      | 6    | 熔断机制：下游服务失败率/延迟超过阈值时自动切断调用             |
| ft_timeout_handling     | 6    | 超时处理：所有外部调用设置了合理的、非无限的超时时间           |
| ft_retry_policy         | 5    | 智能重试：带退避策略（Exponential Backoff）和抖动的重试机制    |
| ft_fallback             | 5    | 降级机制：非核心依赖失败时有预设的默认值、缓存数据或简化流程   |
| ft_bulkhead             | 5    | 舱壁模式：对资源（线程池、连接池）进行隔离                     |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import IstioDestinationRuleRecord, IstioVirtualServiceRecord
from ...schema.manual import ManualFallbackConfigRecord, ManualBulkheadConfigRecord


def _parse_timeout_to_seconds(timeout_str: str) -> float | None:
    """将 Istio 超时字符串解析为秒数"""
    import re

    pattern = r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?(?:(\d+)ms)?$'
    match = re.match(pattern, timeout_str.lower().strip())

    if not match:
        return None

    hours, minutes, seconds, milliseconds = match.groups()
    total = 0
    if hours:
        total += int(hours) * 3600
    if minutes:
        total += int(minutes) * 60
    if seconds:
        total += int(seconds)
    if milliseconds:
        total += int(milliseconds) / 1000

    return total if total > 0 else None


class FtCircuitBreaker(Analyzer):
    """
    熔断机制分析器
    
    评估标准：是否在下游服务失败率/延迟超过阈值时自动切断调用，防止雪崩
    
    数据来源：
    - ASM API / ACK API：GET /apis/networking.istio.io/v1alpha3/destinationrules
    - 检查是否存在含 outlierDetection（异常点驱逐，即熔断机制）的 DestinationRule
    """

    def key(self) -> str:
        return "ft_circuit_breaker"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "容错能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.istio.destination_rule.list"]

    def analyze(self, store) -> ScoreResult:
        rules: list[IstioDestinationRuleRecord] = store.get("k8s.istio.destination_rule.list")

        if not rules:
            return self._not_scored("未发现 Istio DestinationRule，无熔断配置", [])

        well_configured = []
        basic_configured = []
        risk_configured = []
        invalid_configured = []
        missing_configured = []

        for rule in rules:
            traffic_policy = rule.traffic_policy
            if not traffic_policy:
                missing_configured.append(rule)
                continue

            outlier_config = traffic_policy.get("outlierDetection")
            if not outlier_config:
                missing_configured.append(rule)
                continue

            config_quality = self._evaluate_circuit_breaker_config(outlier_config)

            if config_quality["level"] == "invalid":
                invalid_configured.append((rule, config_quality["issues"]))
            elif config_quality["level"] == "risk":
                risk_configured.append((rule, config_quality["issues"]))
            elif config_quality["level"] == "basic":
                basic_configured.append((rule, config_quality.get("warnings", [])))
            else:
                well_configured.append((rule, config_quality.get("params", {})))

        total_count = len(rules)
        effective_count = len(well_configured) + len(basic_configured)

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 覆盖率评分（最高 3.5 分）---
        coverage = effective_count / total_count if total_count > 0 else 0

        if coverage >= 0.9:
            score += 3.5
            evidence.append(f"✓ 覆盖率优秀: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.7:
            score += 2.5
            evidence.append(f"✓ 覆盖率良好: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.5:
            score += 1.5
            evidence.append(f"ℹ️ 覆盖率中等: {effective_count}/{total_count} ({coverage:.0%})")
            warnings.append("熔断覆盖率不足 70%，部分服务缺乏保护")
        elif coverage >= 0.3:
            score += 0.5
            warnings.append(f"熔断覆盖率偏低 ({coverage:.0%})，多数服务无熔断保护")
            evidence.append(f"⚠️ 覆盖率偏低: {effective_count}/{total_count} ({coverage:.0%})")
        else:
            warnings.append(f"熔断覆盖率严重不足 ({coverage:.0%})，系统缺乏基本容错保护")
            evidence.append(f"⚠️ 覆盖率严重不足: {effective_count}/{total_count} ({coverage:.0%})")

        # --- 2. 配置质量评分（最高 2.5 分）---
        if effective_count > 0:
            well_ratio = len(well_configured) / effective_count

            if well_ratio >= 0.7:
                score += 2.5
                evidence.append(f"✓ 配置质量优秀: {len(well_configured)}/{effective_count} 参数调优良好")
            elif well_ratio >= 0.5:
                score += 1.5
                evidence.append(f"✓ 配置质量良好: {len(well_configured)}/{effective_count} 参数调优")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 配置质量一般: {len(well_configured)}/{effective_count} 参数调优")
                if basic_configured:
                    warnings.append(f"{len(basic_configured)} 个熔断配置使用默认参数，建议调优")

        if risk_configured:
            risk_penalty = min(len(risk_configured) * 0.3, 1.0)
            score -= risk_penalty
            warnings.append(f"发现 {len(risk_configured)} 个风险配置，可能影响熔断效果")
            evidence.append(f"⚠️ 风险配置: {len(risk_configured)} 个")

        if invalid_configured:
            warnings.append(f"发现 {len(invalid_configured)} 个无效配置，熔断机制未生效")
            evidence.append(f"⚠️ 无效配置: {len(invalid_configured)} 个")

        for rule, params in well_configured[:2]:
            evidence.append(f"✅ {rule.namespace}/{rule.name}: errors={params.get('consecutive_errors', 'N/A')}, "
                            f"eject_time={params.get('eject_time', 'N/A')}")

        for rule, issues in risk_configured[:2]:
            evidence.append(f"⚠️ {rule.namespace}/{rule.name}: {', '.join(issues[:2])}")

        for rule, issues in invalid_configured[:2]:
            evidence.append(f"❌ {rule.namespace}/{rule.name}: {', '.join(issues[:2])}")

        if missing_configured:
            evidence.append(f"ℹ️ 未配置熔断: {len(missing_configured)} 个 DestinationRule")

        final_score = max(min(round(score, 1), 6), 0)

        if final_score >= 5:
            status_msg = "熔断机制成熟：覆盖全面、配置合理"
        elif final_score >= 4:
            status_msg = "熔断机制良好：覆盖率合格、配置基本合理"
        elif final_score >= 2.5:
            status_msg = "熔断机制基础：存在覆盖或配置质量问题"
        elif final_score >= 1:
            status_msg = "熔断机制薄弱：覆盖率低或存在风险配置"
        else:
            status_msg = "熔断机制缺失：缺乏有效保护"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)

    def _evaluate_circuit_breaker_config(self, outlier_config: dict) -> dict:
        """评估熔断配置的质量等级"""
        issues = []
        warnings = []
        params = {}

        consec_err = outlier_config.get("consecutive5xxErrors")
        eject_time = outlier_config.get("baseEjectionTime")
        max_eject_pct = outlier_config.get("maxEjectionPercent")
        interval = outlier_config.get("interval")

        if consec_err is not None:
            try:
                val = int(consec_err)
                if val <= 0:
                    issues.append("consecutive_errors<=0（熔断永不触发）")
                    return {"level": "invalid", "issues": issues}
                params["consecutive_errors"] = val
            except (ValueError, TypeError):
                issues.append("consecutive_errors 格式错误")
                return {"level": "invalid", "issues": issues}

        if eject_time:
            if str(eject_time).startswith("0s") or str(eject_time) == "0":
                issues.append("base_ejection_time=0（熔断瞬间恢复）")
                return {"level": "invalid", "issues": issues}
            params["eject_time"] = eject_time

        risk_issues = []

        if consec_err is not None:
            val = int(consec_err) if isinstance(consec_err, str) else consec_err
            if val > 20:
                risk_issues.append(f"consecutive_errors={val}（过大，熔断难以触发）")

        if max_eject_pct is not None:
            try:
                val = int(max_eject_pct) if isinstance(max_eject_pct, str) else max_eject_pct
                if val == 0:
                    risk_issues.append("max_ejection_percent=0（禁止驱逐实例）")
                elif val > 100:
                    risk_issues.append(f"max_ejection_percent={val}（>100%，可能驱逐所有实例）")
            except (ValueError, TypeError):
                pass

        if risk_issues:
            return {"level": "risk", "issues": risk_issues}

        has_warnings = False

        if interval is None:
            warnings.append("未配置 interval（使用默认值）")
            has_warnings = True

        if consec_err is None:
            warnings.append("未配置 consecutive_errors（使用默认值 5）")
            has_warnings = True

        if eject_time is None:
            warnings.append("未配置 base_ejection_time（使用默认值 30s）")
            has_warnings = True

        if has_warnings:
            return {"level": "basic", "warnings": warnings}

        return {"level": "well", "params": params}


class FtTimeoutHandling(Analyzer):
    """
    超时处理分析器
    
    评估标准：所有外部调用（DB, RPC, HTTP）是否设置了合理的、非无限的超时时间
    
    数据来源：
    - ASM API：GET /apis/networking.istio.io/v1alpha3/virtualservices
    - 检查 spec.http[].timeout 字段是否已配置
    """

    def key(self) -> str:
        return "ft_timeout_handling"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "容错能力"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.istio.virtual_service.list"]

    def analyze(self, store) -> ScoreResult:
        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")

        if not vs_list:
            return self._not_scored("未发现 Istio VirtualService，无超时配置", [])

        if not isinstance(vs_list, list):
            return self._not_scored("VirtualService 数据格式异常", [])

        well_configured = []
        risk_configured = []
        invalid_configured = []
        missing_configured = []

        for vs in vs_list:
            http_routes = vs.http_routes
            if not http_routes or not isinstance(http_routes, list):
                missing_configured.append(vs)
                continue

            best_config = None

            for route in http_routes:
                timeout_val = route.get("timeout")
                if not timeout_val:
                    continue

                str_val = str(timeout_val).strip().lower()

                if str_val in ["0s", "0", "0ms", "0m", "0h"]:
                    invalid_configured.append((vs, "timeout=0s"))
                    break

                timeout_seconds = _parse_timeout_to_seconds(str_val)
                if timeout_seconds is not None:
                    config_quality = self._evaluate_timeout_value(timeout_seconds)
                    best_config = {
                        "timeout": str_val,
                        "seconds": timeout_seconds,
                        "quality": config_quality
                    }
                    break
                else:
                    best_config = {
                        "timeout": str_val,
                        "seconds": None,
                        "quality": "unknown"
                    }
                    break

            if best_config:
                if best_config["quality"] == "well":
                    well_configured.append((vs, best_config))
                elif best_config["quality"] == "risk":
                    risk_configured.append((vs, best_config))
                else:
                    well_configured.append((vs, best_config))
            else:
                missing_configured.append(vs)

        total_count = len(vs_list)
        effective_count = len(well_configured)

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 覆盖率评分（最高 4 分）---
        coverage = effective_count / total_count if total_count > 0 else 0

        if coverage >= 0.9:
            score += 4.0
            evidence.append(f"✓ 覆盖率优秀: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.7:
            score += 3.0
            evidence.append(f"✓ 覆盖率良好: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.5:
            score += 2.0
            evidence.append(f"ℹ️ 覆盖率中等: {effective_count}/{total_count} ({coverage:.0%})")
            warnings.append("超时配置覆盖率不足 70%，部分服务缺乏保护")
        elif coverage >= 0.3:
            score += 1.0
            warnings.append(f"超时覆盖率偏低 ({coverage:.0%})，多数服务无超时保护")
            evidence.append(f"⚠️ 覆盖率偏低: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage > 0:
            score += 0.5
            warnings.append(f"超时覆盖率严重不足 ({coverage:.0%})，系统缺乏基本超时保护")
            evidence.append(f"⚠️ 覆盖率严重不足: {effective_count}/{total_count} ({coverage:.0%})")
        else:
            warnings.append("未发现任何有效的超时配置")
            evidence.append("⚠️ 覆盖率为零: 无有效超时配置")

        # --- 2. 配置质量评分（最高 2 分）---
        if well_configured:
            timeout_values = [c["seconds"] for _, c in well_configured if c.get("seconds") is not None]
            if timeout_values:
                min_timeout = min(timeout_values)
                max_timeout = max(timeout_values)

                if min_timeout >= 0.1 and max_timeout <= 600:
                    score += 2.0
                    evidence.append(f"✓ 超时值分布合理: {min_timeout:.1f}s ~ {max_timeout:.1f}s")
                elif min_timeout < 0.1:
                    score += 1.0
                    warnings.append(f"最小超时值仅 {min_timeout * 1000:.0f}ms，可能导致正常请求超时")
                    evidence.append(f"⚠️ 存在过短超时: 最小 {min_timeout * 1000:.0f}ms")
                elif max_timeout > 600:
                    score += 1.0
                    warnings.append(f"最大超时值达 {max_timeout:.0f}s，可能导致资源长时间阻塞")
                    evidence.append(f"⚠️ 存在过长超时: 最大 {max_timeout:.0f}s")
                else:
                    score += 1.5
                    evidence.append(f"ℹ️ 超时值范围: {min_timeout:.1f}s ~ {max_timeout:.1f}s")

        # --- 3. 风险配置检查（扣分项）---
        if risk_configured:
            risk_penalty = min(len(risk_configured) * 0.2, 1.0)
            score -= risk_penalty
            warnings.append(f"发现 {len(risk_configured)} 个风险超时配置")
            evidence.append(f"⚠️ 风险配置: {len(risk_configured)} 个")

        if invalid_configured:
            invalid_penalty = min(len(invalid_configured) * 0.3, 1.5)
            score -= invalid_penalty
            warnings.append(f"发现 {len(invalid_configured)} 个无效超时配置（timeout=0s）")
            evidence.append(f"⚠️ 无效配置: {len(invalid_configured)} 个")

        for vs, config in well_configured[:2]:
            evidence.append(f"✅ {vs.namespace}/{vs.name}: timeout={config['timeout']}")

        for vs, config in risk_configured[:2]:
            evidence.append(f"⚠️ {vs.namespace}/{vs.name}: timeout={config['timeout']} ({config.get('seconds', '?')}s)")

        for vs, reason in invalid_configured[:2]:
            evidence.append(f"❌ {vs.namespace}/{vs.name}: {reason}")

        if missing_configured:
            evidence.append(f"ℹ️ 未配置超时: {len(missing_configured)} 个 VirtualService")

        final_score = max(min(round(score, 1), 6), 0)

        if final_score >= 5:
            status_msg = "超时配置成熟：覆盖全面、值合理"
        elif final_score >= 4:
            status_msg = "超时配置良好：覆盖率合格、配置基本合理"
        elif final_score >= 2.5:
            status_msg = "超时配置基础：存在覆盖或配置质量问题"
        elif final_score >= 1:
            status_msg = "超时配置薄弱：覆盖率低或存在风险配置"
        else:
            status_msg = "超时配置缺失：缺乏有效保护"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)

    def _evaluate_timeout_value(self, seconds: float) -> str:
        """评估超时值是否合理"""
        if seconds < 0.01:
            return "risk"
        elif seconds > 3600:
            return "risk"
        elif seconds < 0.1:
            return "risk"
        elif seconds > 600:
            return "risk"
        else:
            return "well"


class FtRetryPolicy(Analyzer):
    """
    智能重试分析器
    
    评估标准：是否实现了带退避策略（Exponential Backoff）和抖动（Jitter）的重试机制，避免重试风暴
    
    数据来源：
    - ASM API：VirtualService 的 spec.http[].retries 字段
    - 检查是否配置了 attempts（重试次数）、perTryTimeout（每次超时）以及退避策略
    """

    def key(self) -> str:
        return "ft_retry_policy"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "容错能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["k8s.istio.virtual_service.list"]

    def analyze(self, store) -> ScoreResult:
        vs_list: list[IstioVirtualServiceRecord] = store.get("k8s.istio.virtual_service.list")

        if not vs_list:
            return self._not_scored("未发现 Istio VirtualService，无重试配置", [])

        well_configured = []
        basic_configured = []
        risk_configured = []
        missing_configured = []

        for vs in vs_list:
            http_routes = vs.http_routes
            if not http_routes or not isinstance(http_routes, list):
                missing_configured.append(vs)
                continue

            best_retry_config = None

            for route in http_routes:
                retries = route.get("retries")
                if retries:
                    config_quality = self._evaluate_retry_config(retries)
                    best_retry_config = {
                        "retries": retries,
                        "quality": config_quality["level"],
                        "params": config_quality.get("params", {}),
                        "issues": config_quality.get("issues", []),
                        "warnings": config_quality.get("warnings", [])
                    }
                    break

            if best_retry_config:
                if best_retry_config["quality"] == "well":
                    well_configured.append((vs, best_retry_config))
                elif best_retry_config["quality"] == "risk":
                    risk_configured.append((vs, best_retry_config))
                else:
                    basic_configured.append((vs, best_retry_config))
            else:
                missing_configured.append(vs)

        total_count = len(vs_list)
        effective_count = len(well_configured) + len(basic_configured)

        # 如果没有任何有效配置
        if effective_count == 0 and len(risk_configured) == 0:
            return self._not_scored(
                "已有 VirtualService 但未配置重试策略",
                [f"共 {total_count} 个 VirtualService"]
            )

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 覆盖率评分（最高 2.5 分）---
        coverage = effective_count / total_count if total_count > 0 else 0

        if coverage >= 0.8:
            score += 2.5
            evidence.append(f"✓ 覆盖率优秀: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.6:
            score += 2.0
            evidence.append(f"✓ 覆盖率良好: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.4:
            score += 1.5
            evidence.append(f"ℹ️ 覆盖率中等: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.2:
            score += 0.5
            warnings.append(f"重试配置覆盖率偏低 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率偏低: {effective_count}/{total_count} ({coverage:.0%})")
        else:
            warnings.append(f"重试配置覆盖率严重不足 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率严重不足: {effective_count}/{total_count} ({coverage:.0%})")

        # --- 2. 配置质量评分（最高 2.5 分）---
        if effective_count > 0:
            well_ratio = len(well_configured) / effective_count

            if well_ratio >= 0.7:
                score += 2.5
                evidence.append(f"✓ 配置质量优秀: {len(well_configured)}/{effective_count} 参数完整合理")
            elif well_ratio >= 0.5:
                score += 1.5
                evidence.append(f"✓ 配置质量良好: {len(well_configured)}/{effective_count} 参数完整")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 配置质量一般: {len(well_configured)}/{effective_count} 参数完整")
                if basic_configured:
                    warnings.append(f"{len(basic_configured)} 个重试配置参数不完整，建议补充 perTryTimeout")

        # --- 3. 风险配置检查（扣分项）---
        if risk_configured:
            risk_penalty = min(len(risk_configured) * 0.3, 1.5)
            score -= risk_penalty
            warnings.append(f"发现 {len(risk_configured)} 个风险重试配置，可能导致重试风暴")
            evidence.append(f"⚠️ 风险配置: {len(risk_configured)} 个")

        for vs, config in well_configured[:2]:
            params = config.get("params", {})
            evidence.append(
                f"✅ {vs.namespace}/{vs.name}: attempts={params.get('attempts', 'N/A')}, "
                f"perTryTimeout={params.get('per_try_timeout', 'N/A')}"
            )

        for vs, config in basic_configured[:2]:
            issues = config.get("warnings", [])
            evidence.append(f"ℹ️ {vs.namespace}/{vs.name}: {', '.join(issues[:2]) if issues else '参数不完整'}")

        for vs, config in risk_configured[:2]:
            issues = config.get("issues", [])
            evidence.append(f"⚠️ {vs.namespace}/{vs.name}: {', '.join(issues[:2])}")

        if missing_configured:
            evidence.append(f"ℹ️ 未配置重试: {len(missing_configured)} 个 VirtualService")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "重试机制成熟：覆盖全面、配置合理"
        elif final_score >= 3.5:
            status_msg = "重试机制良好：覆盖率合格、配置基本合理"
        elif final_score >= 2:
            status_msg = "重试机制基础：存在覆盖或配置质量问题"
        elif final_score >= 1:
            status_msg = "重试机制薄弱：覆盖率低或存在风险配置"
        else:
            status_msg = "重试机制缺失或存在严重风险"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)

    def _evaluate_retry_config(self, retries: dict) -> dict:
        """评估重试配置的质量等级"""
        issues = []
        warnings = []
        params = {}

        # 提取参数
        attempts = retries.get("attempts")
        per_try_timeout = retries.get("perTryTimeout") or retries.get("per_try_timeout")
        retry_on = retries.get("retryOn") or retries.get("retry_on")

        # --- 检查 attempts ---
        if attempts is not None:
            try:
                attempts_val = int(attempts) if isinstance(attempts, str) else attempts
                params["attempts"] = attempts_val

                if attempts_val <= 0:
                    issues.append("attempts<=0（无效配置）")
                    return {"level": "risk", "issues": issues}
                elif attempts_val > 10:
                    issues.append(f"attempts={attempts_val}（过大，可能导致重试风暴）")
                    return {"level": "risk", "issues": issues, "params": params}
                elif attempts_val > 5:
                    warnings.append(f"attempts={attempts_val} 偏高")
            except (ValueError, TypeError):
                issues.append("attempts 格式错误")
                return {"level": "risk", "issues": issues}
        else:
            warnings.append("未配置 attempts（使用默认值）")

        # --- 检查 perTryTimeout ---
        if per_try_timeout:
            params["per_try_timeout"] = per_try_timeout
            timeout_seconds = _parse_timeout_to_seconds(str(per_try_timeout))

            if timeout_seconds is not None:
                if timeout_seconds < 0.1:  # < 100ms
                    issues.append(f"perTryTimeout={per_try_timeout}（过短，正常请求可能中断）")
                    return {"level": "risk", "issues": issues, "params": params}
                elif timeout_seconds > 300:  # > 5 分钟
                    issues.append(f"perTryTimeout={per_try_timeout}（过长，可能阻塞资源）")
                    return {"level": "risk", "issues": issues, "params": params}
        else:
            warnings.append("未配置 perTryTimeout（可能导致长时间阻塞）")

        # --- 检查 retryOn ---
        if retry_on:
            params["retry_on"] = retry_on
        else:
            warnings.append("未配置 retryOn（默认仅对特定错误重试）")

        # --- 综合判定 ---
        if issues:
            return {"level": "risk", "issues": issues, "params": params}

        if len(warnings) >= 2:
            return {"level": "basic", "warnings": warnings, "params": params}
        elif warnings:
            return {"level": "basic", "warnings": warnings, "params": params}

        return {"level": "well", "params": params}


class FtFallback(Analyzer):
    """
    降级机制分析器
    
    评估标准：在非核心依赖失败时，是否有预设的默认值、缓存数据或简化流程作为兜底
    
    数据来源：
    - 人工填写/源代码分析
    - 无自动化接口，如可获取到源代码，可以通过源代码分析是否有降级策略
    """

    def key(self) -> str:
        return "ft_fallback"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "容错能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.fallback.config"]

    def analyze(self, store) -> ScoreResult:
        configs: list[ManualFallbackConfigRecord] = store.get("manual.fallback.config")

        if not configs:
            return self._not_evaluated("降级机制需人工填写，暂无数据")

        total_count = len(configs)

        well_configured = []
        basic_configured = []
        weak_configured = []

        for config in configs:
            if not config.has_fallback:
                continue

            quality = self._evaluate_fallback_config(config)

            if quality["level"] == "well":
                well_configured.append((config, quality))
            elif quality["level"] == "basic":
                basic_configured.append((config, quality))
            else:
                weak_configured.append((config, quality))

        effective_count = len(well_configured) + len(basic_configured)

        if effective_count == 0:
            return self._not_scored("服务均未配置降级机制", [f"共 {total_count} 个服务"])

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 覆盖率评分（最高 2.5 分）---
        coverage = effective_count / total_count

        if coverage >= 0.8:
            score += 2.5
            evidence.append(f"✓ 覆盖率优秀: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.6:
            score += 2.0
            evidence.append(f"✓ 覆盖率良好: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.4:
            score += 1.5
            evidence.append(f"ℹ️ 覆盖率中等: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.2:
            score += 0.5
            warnings.append(f"降级配置覆盖率偏低 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率偏低: {effective_count}/{total_count} ({coverage:.0%})")
        else:
            warnings.append(f"降级配置覆盖率严重不足 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率严重不足: {effective_count}/{total_count} ({coverage:.0%})")

        # --- 2. 配置质量评分（最高 2.5 分）---
        if effective_count > 0:
            well_ratio = len(well_configured) / effective_count

            if well_ratio >= 0.7:
                score += 2.5
                evidence.append(f"✓ 配置质量优秀: {len(well_configured)}/{effective_count} 降级策略完善")
            elif well_ratio >= 0.5:
                score += 1.5
                evidence.append(f"✓ 配置质量良好: {len(well_configured)}/{effective_count} 降级策略较完善")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 配置质量一般: {len(well_configured)}/{effective_count} 降级策略完善")
                if basic_configured:
                    warnings.append(f"{len(basic_configured)} 个降级配置信息不完整")

        # --- 3. 弱配置检查（扣分项）---
        if weak_configured:
            weak_penalty = min(len(weak_configured) * 0.2, 1.0)
            score -= weak_penalty
            warnings.append(f"发现 {len(weak_configured)} 个降级配置类型不明确")
            evidence.append(f"⚠️ 弱配置: {len(weak_configured)} 个")

        for config, quality in well_configured[:3]:
            dep_count = len(config.dependencies_covered)
            evidence.append(f"✅ {config.service_name}: {config.fallback_type} (覆盖{dep_count}个依赖)")

        for config, quality in basic_configured[:2]:
            evidence.append(f"ℹ️ {config.service_name}: {config.fallback_type or '类型未指定'}")

        for config, quality in weak_configured[:2]:
            issues = quality.get("issues", [])
            evidence.append(f"⚠️ {config.service_name}: {', '.join(issues[:2])}")

        missing_count = total_count - effective_count
        if missing_count > 0:
            evidence.append(f"ℹ️ 未配置降级: {missing_count} 个服务")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "降级机制成熟：覆盖全面、策略完善"
        elif final_score >= 3.5:
            status_msg = "降级机制良好：覆盖率合格、策略较完善"
        elif final_score >= 2:
            status_msg = "降级机制基础：存在覆盖或策略质量不足"
        elif final_score >= 1:
            status_msg = "降级机制薄弱：覆盖率低或策略不完善"
        else:
            status_msg = "降级机制缺失或配置无效"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)

    def _evaluate_fallback_config(self, config: ManualFallbackConfigRecord) -> dict:
        """评估降级配置的质量等级"""
        issues = []
        warnings = []

        # 检查降级类型
        fallback_type = config.fallback_type.lower().strip() if config.fallback_type else ""

        # 高价值降级类型
        high_value_types = ["circuit_breaker", "cache"]
        medium_value_types = ["simplified_flow", "default_value"]

        if not fallback_type:
            issues.append("未指定降级类型")
            return {"level": "weak", "issues": issues}

        if fallback_type not in high_value_types + medium_value_types:
            issues.append(f"降级类型 '{config.fallback_type}' 不明确")
            return {"level": "weak", "issues": issues}

        if not config.fallback_description or len(config.fallback_description) < 10:
            warnings.append("降级描述缺失或过于简单")

        dep_count = len(config.dependencies_covered)
        if dep_count == 0:
            warnings.append("未指定覆盖的依赖")

        if len(issues) > 0:
            return {"level": "weak", "issues": issues}

        if len(warnings) >= 2 or dep_count == 0:
            return {"level": "basic", "warnings": warnings, "fallback_type": fallback_type}

        return {"level": "well", "fallback_type": fallback_type}


class FtBulkhead(Analyzer):
    """
    舱壁模式分析器
    
    评估标准：是否对资源（线程池、连接池）进行隔离，防止单个组件故障耗尽所有系统资源
    
    数据来源：
    - 人工填写/源代码分析
    - 无自动化接口，如可获取到源代码，可以通过源代码分析是否使用了独立的线程池或数据库连接池
    """

    def key(self) -> str:
        return "ft_bulkhead"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "容错能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.bulkhead.config"]

    def analyze(self, store) -> ScoreResult:
        configs: list[ManualBulkheadConfigRecord] = store.get("manual.bulkhead.config")

        if not configs:
            return self._not_evaluated("舱壁模式配置需人工填写，暂无数据")

        total_count = len(configs)

        full_isolation = []
        partial_isolation = []
        basic_isolation = []

        for config in configs:
            if not config.has_bulkhead:
                continue

            isolation_score = self._calculate_isolation_score(config)

            if isolation_score["level"] == "full":
                full_isolation.append((config, isolation_score))
            elif isolation_score["level"] == "partial":
                partial_isolation.append((config, isolation_score))
            else:
                basic_isolation.append((config, isolation_score))

        effective_count = len(full_isolation) + len(partial_isolation) + len(basic_isolation)

        if effective_count == 0:
            return self._not_scored("服务均未实现舱壁模式隔离", [f"共 {total_count} 个服务"])

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. 覆盖率评分（最高 2 分）---
        coverage = effective_count / total_count

        if coverage >= 0.8:
            score += 2.0
            evidence.append(f"✓ 覆盖率优秀: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.6:
            score += 1.5
            evidence.append(f"✓ 覆盖率良好: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.4:
            score += 1.0
            evidence.append(f"ℹ️ 覆盖率中等: {effective_count}/{total_count} ({coverage:.0%})")
        elif coverage >= 0.2:
            score += 0.5
            warnings.append(f"舱壁模式覆盖率偏低 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率偏低: {effective_count}/{total_count} ({coverage:.0%})")
        else:
            warnings.append(f"舱壁模式覆盖率严重不足 ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率严重不足: {effective_count}/{total_count} ({coverage:.0%})")

        # --- 2. 隔离深度评分（最高 3 分）---
        if effective_count > 0:
            full_ratio = len(full_isolation) / effective_count
            partial_ratio = len(partial_isolation) / effective_count

            if full_ratio >= 0.6:
                score += 3.0
                evidence.append(f"✓ 隔离深度优秀: {len(full_isolation)}/{effective_count} 全面隔离")
            elif full_ratio >= 0.3:
                score += 2.0
                evidence.append(f"✓ 隔离深度良好: {len(full_isolation)}/{effective_count} 全面隔离")
            elif full_ratio > 0 or partial_ratio >= 0.5:
                score += 1.0
                evidence.append(f"ℹ️ 隔离深度中等: {len(full_isolation)}/{effective_count} 全面隔离, "
                              f"{len(partial_isolation)}/{effective_count} 部分隔离")
                if full_ratio < 0.3:
                    warnings.append("全面隔离（线程池+连接池）比例偏低")
            else:
                score += 0.5
                warnings.append("多数服务仅配置基础隔离（信号量），建议增加线程池/连接池隔离")
                evidence.append(f"⚠️ 隔离深度不足: 基础隔离占比高")

        # --- 3. 基础隔离检查（扣分项）---
        if basic_isolation:
            basic_penalty = min(len(basic_isolation) * 0.15, 0.5)
            score -= basic_penalty
            warnings.append(f"{len(basic_isolation)} 个服务仅配置信号量隔离，保护能力有限")
            evidence.append(f"⚠️ 基础隔离: {len(basic_isolation)} 个")

        # --- 4. 详细证据 ---
        for config, score_info in full_isolation[:3]:
            evidence.append(
                f"✅ {config.service_name}: 线程池+连接池隔离"
            )

        for config, score_info in partial_isolation[:2]:
            types = score_info.get("isolation_types", [])
            evidence.append(f"ℹ️ {config.service_name}: {', '.join(types)}隔离")

        for config, score_info in basic_isolation[:2]:
            evidence.append(f"⚠️ {config.service_name}: 仅信号量隔离")

        missing_count = total_count - effective_count
        if missing_count > 0:
            evidence.append(f"ℹ️ 未配置隔离: {missing_count} 个服务")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "舱壁模式成熟：覆盖全面、隔离深度充足"
        elif final_score >= 3.5:
            status_msg = "舱壁模式良好：覆盖率合格、隔离较完善"
        elif final_score >= 2:
            status_msg = "舱壁模式基础：存在覆盖或隔离深度不足"
        elif final_score >= 1:
            status_msg = "舱壁模式薄弱：覆盖率低或仅基础隔离"
        else:
            status_msg = "舱壁模式缺失或配置无效"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)

    def _calculate_isolation_score(self, config: ManualBulkheadConfigRecord) -> dict:
        """计算隔离配置的深度等级"""
        isolation_types = []
        score = 0

        if config.thread_pool_isolation:
            isolation_types.append("线程池")
            score += 2

        if config.connection_pool_isolation:
            isolation_types.append("连接池")
            score += 2

        if config.semaphore_isolation:
            isolation_types.append("信号量")
            score += 1

        if score >= 4:
            return {"level": "full", "score": score, "isolation_types": isolation_types}
        elif score >= 2:
            return {"level": "partial", "score": score, "isolation_types": isolation_types}
        else:
            return {"level": "basic", "score": score, "isolation_types": isolation_types}


# 导出所有分析器
FAULT_TOLERANCE_ANALYZERS = [
    FtCircuitBreaker(),
    FtTimeoutHandling(),
    FtRetryPolicy(),
    FtFallback(),
    FtBulkhead(),
]
