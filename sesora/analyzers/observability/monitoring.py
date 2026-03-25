"""
Observability 维度 - 监控能力 (Monitoring) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)             | 分值 | 评分标准                                                       |
| mon_metrics_depth        | 0-5  | 指标收集深度：全面(5)/高级(4)/标准(3)/基础(2)/无(0)            |
| mon_metrics_std          | 3    | 指标标准化：是否采用 Prometheus/OpenTelemetry 等标准命名规范   |
| mon_alert_rules          | 5    | 告警规则定义：是否基于 SLO/SLI 而非简单阈值                    |
| mon_alert_severity       | 4    | 告警分级：是否定义了 P0-P4 等不同严重等级                      |
| mon_alert_channels       | 0-5  | 告警通道多样性：>=4种渠道(5分)/2-3种(3分)/1种(1分)             |
| mon_tool_integration     | 5    | 工具链集成：指标、告警、可视化是否无缝集成                     |
| mon_coverage_gap         | 8    | 核心服务拓扑覆盖率(4分) + 黄金信号完整性(4分)                  |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema import SlsLogstoreRecord
from ...schema.sls import SlsIndexConfigRecord
from ...schema.cms import CmsAlarmRuleRecord, CmsContactRecord
from ...schema.apm import ApmServiceRecord, ApmCoverageAnalysisRecord


class MonMetricsDepthAnalyzer(Analyzer):
    """
    指标收集深度分析器
    
    评估标准：
    - 全面 (5): 覆盖系统、应用、业务、用户体验及自定义指标
    - 高级 (4): 覆盖系统、应用、业务指标
    - 标准 (3): 仅覆盖系统和基础应用指标
    - 基础 (2): 仅有基础系统指标 (CPU/Mem)
    - 无 (0)
    
    数据来源：
    - UModel：K8s high-level 指标集（系统层），APM service 指标集（应用层）
    - ARMS Prometheus：查询 count({__name__=~"business_.*"}) 判断是否有业务指标
    """

    def key(self) -> str:
        return "mon_metrics_depth"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def optional_data(self) -> list[str]:
        return ["apm.service.list"]

    def analyze(self, store) -> ScoreResult:
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")

        if not rules:
            return self._not_scored("未配置监控告警规则：系统处于无监控状态", [])

        evidence = []
        score = 0.0

        # --- 1. 预过滤：启用且有通知渠道的规则才是有效告警 ---
        active_rules = []
        no_notify_count = 0

        for rule in rules:
            has_notification = rule.contact_groups or rule.webhook_url or rule.action_types
            if rule.enable_state and has_notification:
                active_rules.append(rule)
            elif rule.enable_state and not has_notification:
                no_notify_count += 1

        total_active = len(active_rules)
        evidence.append(f"告警规则总数: {len(rules)}")
        evidence.append(f"✅ 有效告警 (启用 + 有通知): {total_active}")

        if no_notify_count > 0:
            evidence.append(f"⚠️ {no_notify_count} 个规则已启用但未配置通知渠道，告警将失效")

        if total_active == 0:
            return self._not_scored("虽有告警规则配置，但均未启用或缺少通知渠道，实际无监控能力", evidence)

        # --- 2. 层级覆盖度评估 (最高 3 分) ---
        system_keywords = ["cpu", "memory", "disk", "network", "node", "host", "load", "inode"]
        app_keywords = ["latency", "response_time", "error_rate", "error_count", "qps",
                        "tps", "throughput", "http_status", "exception", "p99", "p95"]
        business_keywords = ["order_", "payment_", "transaction_", "trade_",
                             "success_rate", "biz_", "business_"]
        ux_keywords = ["lcp", "fid", "cls", "page_load", "first_paint",
                       "ux_", "frontend_", "apdex"]

        layers = {"system": False, "application": False, "business": False, "ux": False}
        layer_hits = {k: [] for k in layers}

        for rule in active_rules:
            metric = rule.metric_name
            if not metric:
                continue
            m = metric.lower()
            if any(kw in m for kw in system_keywords):
                layers["system"] = True
                layer_hits["system"].append(metric)
            if any(kw in m for kw in app_keywords):
                layers["application"] = True
                layer_hits["application"].append(metric)
            if any(kw in m for kw in business_keywords):
                layers["business"] = True
                layer_hits["business"].append(metric)
            if any(kw in m for kw in ux_keywords):
                layers["ux"] = True
                layer_hits["ux"].append(metric)

        covered_count = sum(1 for v in layers.values() if v)
        layer_score = covered_count / 4 * 3
        score += layer_score

        covered_names = [k for k, v in layers.items() if v]
        if covered_count == 4:
            evidence.append("✓ 全维度覆盖：系统 + 应用 + 业务 + 体验")
        elif covered_count >= 2:
            evidence.append(f"ℹ️ 覆盖层级: {', '.join(covered_names)} ({covered_count}/4)")
        elif covered_count == 1:
            evidence.append(f"⚠️ 仅覆盖层级: {covered_names[0]}，监控视角严重不足")
        else:
            evidence.append("✗ 未识别到任何已知层级的指标")

        # --- 3. 应用层核心指标完整性 (最高 1 分) ---
        has_error_alert = any("error" in m.lower() for m in layer_hits["application"])
        has_latency_alert = any(
            kw in m.lower() for m in layer_hits["application"]
            for kw in ["latency", "response_time", "p99", "p95"]
        )

        if layers["application"]:
            if has_error_alert and has_latency_alert:
                score += 1
                evidence.append("✓ 应用层黄金信号完备：错误率 + 延迟告警均已配置")
            elif has_error_alert or has_latency_alert:
                score += 0.5
                missing = "延迟" if not has_latency_alert else "错误率"
                evidence.append(f"⚠️ 应用层缺少核心指标: 未配置{missing}告警")
            else:
                evidence.append("✗ 应用层告警缺少核心指标 (错误率和延迟)，监控存在盲区")

        # --- 4. APM 集成评估 (最高 1 分) ---
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if services:
            apm_hits = [m for m in layer_hits["application"]
                        if any(kw in m.lower() for kw in ["apm", "trace", "span", "arms"])]
            if apm_hits:
                score += 1.0
                evidence.append(f"✓ 深度集成 APM 监控告警 ({len(apm_hits)} 个指标)")
            else:
                score += 0.3
                evidence.append(f"ℹ️ 已部署 APM 服务 ({len(services)} 个)，但未配置针对性 APM 指标告警")
        else:
            evidence.append("ℹ️ 未检测到 APM 服务")

        # --- 5. 通知失效惩罚 ---
        if no_notify_count > 0:
            total_enabled = total_active + no_notify_count
            bad_ratio = no_notify_count / total_enabled
            if bad_ratio > 0.3:
                penalty = bad_ratio * 1.0
                score -= penalty
                evidence.append(f"❌ 失效告警超过30%，扰分 {penalty:.1f} 分")

        # --- 确保分数不超过满分 ---
        final_score = max(min(round(score), 5), 0)

        if final_score >= 5:
            conclusion = "监控体系卓越：全维度覆盖、核心指标完备、APM 深度集成"
        elif final_score >= 4:
            conclusion = "监控体系良好：覆盖主要层级，建议补充业务/体验指标或完善 APM 集成"
        elif final_score >= 3:
            conclusion = "监控体系基础：仅有系统和基础应用告警，缺乏业务视角"
        elif final_score >= 2:
            conclusion = "监控体系薄弱：覆盖不全或缺少核心指标，存在运维风险"
        else:
            return self._not_scored("监控告警无效：规则未启用或无通知渠道", evidence)

        return self._scored(final_score, conclusion, evidence)


class MonMetricsStdAnalyzer(Analyzer):
    """
    指标标准化分析器
    
    评估标准：是否采用 Prometheus/OpenTelemetry 等标准指标命名规范，便于跨团队聚合
    
    数据来源：
    - ARMS Prometheus：抽样查询指标名称，判断是否符合 <namespace>_<subsystem>_<name>_<unit> 命名规范
    """

    def key(self) -> str:
        return "mon_metrics_std"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 3

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def analyze(self, store) -> ScoreResult:
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")

        if not rules:
            return self._not_scored("未获取到监控规则", [])

        evidence = []
        score = 0.0
        total = len(rules)
        enabled_rules = [r for r in rules if r.enable_state]

        evidence.append(f"告警规则总数: {total}，已启用: {len(enabled_rules)}")

        # --- 1. 自定义指标覆盖率 (最高 1.5 分) ---
        custom_indicators = [
            "custom_", "biz_", "app_", "svc_", "user_",
            "business_", "service_", "api_"
        ]
        custom_rules = []
        for r in enabled_rules:
            m = (r.metric_name or "").lower()
            if any(m.startswith(prefix) for prefix in custom_indicators):
                custom_rules.append(r.metric_name)

        custom_ratio = len(custom_rules) / len(enabled_rules) if enabled_rules else 0

        if custom_rules:
            custom_score = min(custom_ratio * 1.5, 1.5)
            score += custom_score
            evidence.append(f"✓ 自定义指标告警: {len(custom_rules)}/{len(enabled_rules)} ({custom_ratio * 100:.0f}%)")
            if len(custom_rules) <= 3:
                evidence.append(f"  示例: {', '.join(custom_rules[:3])}")
        else:
            evidence.append("ℹ️ 未检测到自定义指标告警，均为阿里云内置指标")

        # --- 2. 命名规范性评估 (最高 1 分) ---
        if custom_rules:
            def is_snake_case(name: str) -> bool:
                import re
                return bool(re.match(r'^[a-z][a-z0-9]*(_[a-z0-9]+)+$', name))

            snake_case_count = sum(1 for m in custom_rules if is_snake_case(m))
            snake_ratio = snake_case_count / len(custom_rules)

            naming_score = snake_ratio * 1.0
            score += naming_score

            if snake_ratio >= 0.8:
                evidence.append(f"✓ 自定义指标命名规范性好: {snake_case_count}/{len(custom_rules)} 符合 snake_case")
            elif snake_ratio >= 0.5:
                evidence.append(f"ℹ️ 自定义指标命名规范性中等: {snake_case_count}/{len(custom_rules)} 符合 snake_case")
            else:
                evidence.append(f"⚠️ 自定义指标命名规范性差: 仅 {snake_case_count}/{len(custom_rules)} 符合 snake_case")
        else:
            evidence.append("ℹ️ 无自定义指标可验证命名规范")

        # --- 3. APM 标准化集成 (最高 0.5 分) ---
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if services:
            score += 0.5
            evidence.append(f"✓ 已集成 APM 服务 ({len(services)} 个)，天然具备 OpenTelemetry 标准指标")
        else:
            evidence.append("ℹ️ 未检测到 APM 服务，建议集成 ARMS 以获得标准化指标")

        # --- 确保分数不超过满分 ---
        final_score = max(min(round(score), 3), 0)

        if final_score == 0:
            return self._not_scored("未检测到自定义指标也无 APM 集成，无法评估指标标准化水平", evidence)

        if final_score >= 3:
            conclusion = "指标标准化程度高：自定义指标丰富且命名规范，具备 APM 标准体系"
        elif final_score >= 2:
            conclusion = "指标标准化程度中等，建议提升自定义指标覆盖率或命名规范性"
        else:
            conclusion = "指标标准化程度低，建议引入自定义指标并遵循 snake_case 命名规范"

        return self._scored(final_score, conclusion, evidence)


class MonAlertRulesAnalyzer(Analyzer):
    """
    告警规则定义分析器
    
    评估标准：检查规则是否基于 SLO/SLI（如多窗口燃烧率）而非简单静态阈值
    
    数据来源：
    - 云监控 CMS：DescribeAlarmRuleList API，分析规则表达式
    """

    def key(self) -> str:
        return "mon_alert_rules"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def analyze(self, store) -> ScoreResult:
        raw_rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")
        if not raw_rules:
            return self._not_scored("未配置任何告警规则", [])

        evidence = []

        valid_rules = [
            r for r in raw_rules
            if r.enable_state and (r.contact_groups or r.webhook_url or r.action_types)
        ]
        invalid_count = len(raw_rules) - len(valid_rules)
        total_valid = len(valid_rules)

        evidence.append(f"告警规则总数: {len(raw_rules)}")
        evidence.append(f"✅ 有效规则 (启用 + 有通知): {total_valid}")
        if invalid_count > 0:
            evidence.append(f"⚠️ {invalid_count} 个规则无效 (未启用或缺少通知)")

        if total_valid == 0:
            return self._not_scored("虽有规则配置，但无一条有效生效", evidence)

        score = 0.0

        # --- 1. 基础覆盖度 (最高 2 分) ---
        if total_valid >= 20:
            coverage_score = 2.0
            evidence.append(f"✓ 规则覆盖全面 ({total_valid} 条有效规则)")
        elif total_valid >= 10:
            coverage_score = 1.5
            evidence.append(f"ℹ️ 规则覆盖中等 ({total_valid} 条有效规则)")
        elif total_valid >= 3:
            coverage_score = 1.0
            evidence.append(f"ℹ️ 规则覆盖有限 ({total_valid} 条有效规则)")
        else:
            coverage_score = 0.5
            evidence.append(f"⚠️ 规则数量过少 ({total_valid} 条)，建议补充应用/业务层监控")
        score += coverage_score

        # --- 2. 服务级规则识别 (最高 2 分) ---
        slo_explicit_kw = ["slo", "sli", "error_budget", "burn_rate"]
        service_quality_kw = [
            "latency_p99", "latency_p95", "latency_p90",
            "error_rate", "success_rate", "availability",
            "apdex", "p99", "p95"
        ]
        infra_only_kw = [
            "cpu_usage", "memory_usage", "disk_usage", "disk_used",
            "inode_usage", "memory_used_percent", "network_in", "network_out"
        ]

        slo_rules = []
        service_quality_rules = []
        infra_only_rules = []

        for rule in valid_rules:
            r_name = (rule.rule_name or "").lower()
            m_name = (rule.metric_name or "").lower()
            r_expr = (rule.expression or "").lower() if rule.expression else ""
            context_text = f"{r_name} {m_name} {r_expr}"

            if any(kw in context_text for kw in slo_explicit_kw):
                slo_rules.append(rule)
            elif any(kw in context_text for kw in service_quality_kw):
                service_quality_rules.append(rule)
            elif any(kw in m_name for kw in infra_only_kw):
                infra_only_rules.append(rule)

        slo_count = len(slo_rules)
        sq_count = len(service_quality_rules)
        infra_count = len(infra_only_rules)
        non_infra = slo_count + sq_count
        non_infra_ratio = non_infra / total_valid if total_valid else 0

        evidence.append(f"明确 SLO/燃烧率风格规则: {slo_count}")
        evidence.append(f"服务延迟/错误率级规则: {sq_count}")
        evidence.append(f"纯资源阈值规则: {infra_count}")

        if slo_count >= 3:
            service_score = 2.0
            evidence.append("✓ 已建立明确的 SLO/燃烧率体系")
        elif slo_count >= 1:
            service_score = 1.5
            evidence.append(f"✓ 少量 SLO 风格规则 ({slo_count} 条)")
        elif non_infra_ratio >= 0.5:
            service_score = 1.0
            evidence.append(f"ℹ️ 服务质量指标覆盖中等 ({non_infra_ratio * 100:.0f}%)，未明确引入 SLO")
        elif non_infra_ratio > 0:
            service_score = 0.5
            evidence.append(f"⚠️ 少量服务质量指标规则 ({non_infra_ratio * 100:.0f}%)，大部分为资源阈值")
        else:
            service_score = 0
            evidence.append("✗ 未检测到服务级告警，均为基础资源阈值")
        score += service_score

        # --- 3. 多维度覆盖奖励 (最高 1 分) ---
        if infra_count > 0 and non_infra > 0:
            score += 1.0
            evidence.append("✓ 资源层 + 服务层双维度覆盖")
        elif infra_count > 0:
            evidence.append("ℹ️ 仅有资源阈值，缺少服务级告警")
        elif non_infra > 0:
            score += 0.5
            evidence.append("ℹ️ 仅有服务级告警，建议补充基础资源阈值")

        # --- 确保分数不超过满分 ---
        final_score = max(min(round(score), 5), 0)

        if final_score >= 5:
            conclusion = "建立了完善的 SLO 体系，覆盖核心业务，可靠性工程成熟"
        elif final_score >= 4:
            conclusion = "监控规则良好，混合使用阈值与服务级指标，建议将 SLO 系统化"
        elif final_score >= 3:
            conclusion = "监控规则基础，已有服务质量指标，建议引入明确的 SLO 目标"
        elif final_score >= 2:
            conclusion = "监控规则较少且以资源阈值为主，建议补充应用/业务层告警"
        else:
            conclusion = "告警策略单一，缺乏系统性保障"

        return self._scored(final_score, conclusion, evidence)


class MonAlertSeverityAnalyzer(Analyzer):
    """
    告警分级分析器
    
    评估标准：是否定义了 P0-P4 等不同严重等级的告警策略，并关联不同的响应流程
    
    数据来源：
    - 云监控 CMS：告警规则列表，检查是否存在不同 level 的规则
    """

    def key(self) -> str:
        return "mon_alert_severity"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def analyze(self, store) -> ScoreResult:
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")
        if not rules:
            return self._not_scored("未配置告警规则", [])

        evidence = [f"告警规则总数: {len(rules)}"]
        score = 0.0

        valid_rules = [
            r for r in rules
            if r.enable_state and (r.contact_groups or r.webhook_url or r.action_types)
        ]
        invalid_count = len(rules) - len(valid_rules)
        if invalid_count > 0:
            evidence.append(f"⚠️ {invalid_count} 条规则未启用或缺少通知，不计入分级统计")
        if not valid_rules:
            return self._not_scored("所有规则均未生效，分级无意义", evidence)

        level_map: dict[str, int] = {}
        for rule in valid_rules:
            lv = (rule.level or "UNKNOWN").upper()
            level_map[lv] = level_map.get(lv, 0) + 1

        for lv, cnt in sorted(level_map.items()):
            evidence.append(f"  {lv}: {cnt} 条有效规则")

        has_critical = any(lv in ("CRITICAL", "P0", "P1") for lv in level_map)
        has_warn = any(lv in ("WARN", "WARNING", "P2") for lv in level_map)
        has_info = any(lv in ("INFO", "P3", "P4") for lv in level_map)
        active_levels = sum([has_critical, has_warn, has_info])

        # --- 1. CRITICAL 级别是否存在（最高 2 分）---
        critical_count = level_map.get("CRITICAL", 0) + level_map.get("P0", 0) + level_map.get("P1", 0)
        critical_ratio = critical_count / len(valid_rules) if valid_rules else 0

        if critical_count >= 3:
            score += 2.0
            evidence.append(f"✓ CRITICAL 级别规则充足 ({critical_count} 条)")
        elif critical_count >= 1:
            score += 1.5
            evidence.append(f"✓ 存在 CRITICAL 级别规则 ({critical_count} 条)")
        else:
            score += 0
            evidence.append("✗ 缺少 CRITICAL 级别规则，无法保障高优先级故障响应")

        # --- 2. 分级层次完整性（最高 1.5 分）---
        if active_levels >= 3:
            score += 1.5
            evidence.append("✓ 三层分级完整 (CRITICAL / WARN / INFO)")
        elif active_levels == 2:
            score += 1.0
            evidence.append(f"ℹ️ 两层分级，建议补充{'INFO' if has_critical and has_warn else 'CRITICAL'}层")
        else:
            score += 0.3
            evidence.append("⚠️ 仅单一级别，缺乏分级体系")

        # --- 3. 各级别比例合理性（最高 0.5 分）---
        if has_critical and has_warn:
            if critical_ratio <= 0.5:
                score += 0.5
                evidence.append(f"✓ CRITICAL 规则占比合理 ({critical_ratio * 100:.0f}%)")
            else:
                evidence.append(f"⚠️ CRITICAL 规则占比过高 ({critical_ratio * 100:.0f}%)，建议下调部分规则级别")

        final_score = max(min(round(score), 4), 0)

        if final_score >= 4:
            conclusion = "告警分级完善，具备 CRITICAL/WARN/INFO 三层体系且比例合理"
        elif final_score >= 3:
            conclusion = "告警分级较好，覆盖关键级别，建议优化各层比例"
        elif final_score >= 2:
            conclusion = "告警分级基础，存在 CRITICAL 规则，但层次不够完整"
        elif final_score >= 1:
            conclusion = "告警分级薄弱，缺少 CRITICAL 级别或层次单一"
        else:
            conclusion = "告警未有效分级，建议引入多级告警体系"

        return self._scored(final_score, conclusion, evidence)


class MonAlertChannelsAnalyzer(Analyzer):
    """
    告警通道多样性分析器
    
    评估标准：
    - 覆盖 >=4 种渠道 (邮件/短信/IM/电话/API) 得 5 分
    - 覆盖 2-3 种得 3 分
    - 仅 1 种得 1 分
    
    数据来源：
    - 云监控 CMS：DescribeContactList、DescribeContactGroupList API
    """

    def key(self) -> str:
        return "mon_alert_channels"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["cms.alarm_contact.list"]

    def analyze(self, store) -> ScoreResult:
        contacts: list[CmsContactRecord] = store.get("cms.alarm_contact.list")
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")

        if not contacts and not rules:
            return self._not_scored("未配置告警联系人且无告警规则", [])

        evidence = []
        score = 0.0

        # --- 1. 从联系人配置识别可用渠道类型（最高 2 分）---
        available_channels: set[str] = set()
        if contacts:
            evidence.append(f"告警联系人: {len(contacts)} 个")
            for c in contacts:
                for ch in c.channels:
                    available_channels.add(ch.strip().lower())
                if c.email:
                    available_channels.add("email")
                if c.phone:
                    available_channels.add("sms")
                if c.dingtalk_webhook:
                    available_channels.add("dingtalk")

            # 将常见别名均一化
            alias_map = {"mail": "email", "telephone": "sms", "phone": "sms",
                         "dingding": "dingtalk", "ding": "dingtalk"}
            available_channels = {alias_map.get(ch, ch) for ch in available_channels}
            evidence.append(f"联系人可用渠道: {', '.join(sorted(available_channels)) if available_channels else '无'}")
        else:
            evidence.append("⚠️ 未配置联系人")

        # 实时渠道（IM/webhook 响应更快）vs 非实时渠道（邮件可能延迟）
        realtime_channels = {"dingtalk", "wechat", "feishu", "lark", "webhook", "slack", "phone", "sms"}
        has_realtime = bool(available_channels & realtime_channels)
        channel_diversity = len(available_channels)

        if channel_diversity >= 3 and has_realtime:
            score += 2.0
            evidence.append(f"✓ 渠道多样 ({channel_diversity} 种) 且包含实时通道")
        elif channel_diversity >= 2 and has_realtime:
            score += 1.5
            evidence.append(f"✓ 已配置 {channel_diversity} 种渠道，包含实时通道")
        elif channel_diversity >= 2:
            score += 1.0
            evidence.append(f"ℹ️ 已配置 {channel_diversity} 种渠道，但均为非实时渠道（如仅邮件）")
        elif channel_diversity == 1:
            score += 0.5
            evidence.append(f"⚠️ 仅单一渠道: {list(available_channels)[0]}")
        else:
            evidence.append("✗ 联系人未配置任何通知渠道")

        # --- 2. 告警规则实际绑定通知（最高 2 分）---
        has_webhook_active = None
        notify_ratio = 0
        if rules:
            valid_rules = [
                r for r in rules
                if r.enable_state and (r.contact_groups or r.webhook_url or r.action_types)
            ]
            total_rules = len(rules)
            notified_count = len(valid_rules)
            notify_ratio = notified_count / total_rules if total_rules else 0

            webhook_rules = [r for r in valid_rules if r.webhook_url]
            has_webhook_active = len(webhook_rules) > 0

            evidence.append(f"告警规则总数: {total_rules}，绑定通知: {notified_count} ({notify_ratio * 100:.0f}%)")
            if has_webhook_active:
                evidence.append(f"✓ {len(webhook_rules)} 条规则配置了 Webhook 通道")

            if notify_ratio >= 0.8:
                score += 2.0
                evidence.append("✓ 告警规则绑定通知覆盖率高")
            elif notify_ratio >= 0.5:
                score += 1.5
                evidence.append("ℹ️ 告警通知覆盖中等")
            elif notify_ratio >= 0.2:
                score += 1.0
                evidence.append("⚠️ 告警通知覆盖率较低")
            else:
                score += 0
                evidence.append("✗ 绝大多数规则未绑定通知")
        else:
            evidence.append("ℹ️ 无告警规则数据，跳过规则通知覆盖率评估")

        # --- 3. 实时渠道奖励（最高 1 分）---
        if rules:
            if has_webhook_active:
                score += 1.0
                evidence.append("✓ Webhook 通道已被规则实际引用，实时响应有保障")
            elif has_realtime and notify_ratio > 0:
                score += 0.5
                evidence.append("ℹ️ 已配置实时渠道但规则未直接引用 webhook")
        else:
            if has_realtime:
                score += 0.5
                evidence.append("ℹ️ 已配置实时渠道")

        final_score = max(min(round(score), 5), 0)

        if final_score >= 5:
            conclusion = "告警通道完善，多样实时渠道 + 高覆盖率绑定 + webhook 实际活跃"
        elif final_score >= 4:
            conclusion = "告警通道较完善，覆盖多种渠道，建议补充 webhook 实时推送"
        elif final_score >= 3:
            conclusion = "告警通道中等，已有实时渠道，建议提升规则绑定覆盖率"
        elif final_score >= 2:
            conclusion = "告警通道基础，建议引入实时 IM/webhook 渠道"
        else:
            conclusion = "告警通道配置差，建议完善联系人渠道配置"

        return self._scored(final_score, conclusion, evidence)


class MonToolIntegrationAnalyzer(Analyzer):
    """
    工具链集成分析器
    
    评估标准：指标收集工具是否与告警引擎和可视化平台无缝集成，无数据孤岛
    
    数据来源：
    - UModel：APM 的 trace_set_link 和 metric_set_link 定义了关联关系
    - ARMS：检查日志、指标、Trace 是否在同一工作空间下
    """

    def key(self) -> str:
        return "mon_tool_integration"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["apm.service.list"]

    def optional_data(self) -> list[str]:
        return ["cms.alarm_rule.list", "sls.logstore.list", "sls.index_config.list", "grafana.dashboard.list"]

    def analyze(self, store) -> ScoreResult:
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if not services:
            return self._not_scored("未获取到有效的 APM 服务数据", [])

        evidence = [f"APM 服务数: {len(services)}"]
        score = 0.0

        # --- 1. APM 自身覆盖度 (最高 2 分) ---
        trace_enabled_count = sum(1 for s in services if s.trace_enabled)
        trace_ratio = trace_enabled_count / len(services) if services else 0
        evidence.append(f"APM Trace 启用: {trace_enabled_count}/{len(services)} 个服务 ({trace_ratio * 100:.0f}%)")

        if len(services) >= 5 and trace_ratio >= 0.8:
            score += 2.0
            evidence.append("✓ APM 服务视量充足且 Trace 覆盖高")
        elif len(services) >= 2 and trace_ratio >= 0.5:
            score += 1.5
            evidence.append("✓ APM 服务已接入，部分服务启用 Trace")
        elif services:
            score += 0.5
            evidence.append("ℹ️ APM 有服务接入，但 Trace 开启率较低")

        # --- 2. 告警集成 (最高 1 分) ---
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")
        if rules:
            active_rules = [
                r for r in rules
                if r.enable_state and (r.contact_groups or r.webhook_url or r.action_types)
            ]
            active_ratio = len(active_rules) / len(rules) if rules else 0
            evidence.append(f"告警规则: {len(rules)} 条，有效: {len(active_rules)} 条 ({active_ratio * 100:.0f}%)")
            if active_ratio >= 0.5:
                score += 1.0
                evidence.append("✓ 告警集成：有效规则覆盖率充分")
            elif len(active_rules) > 0:
                score += 0.5
                evidence.append("ℹ️ 告警集成：已有有效规则但覆盖率较低")
            else:
                evidence.append("✗ 告警集成：规则均未启用或缺少通知")
        else:
            evidence.append("✗ 告警集成：未检测到告警规则")

        # --- 3. 日志集成 (最高 1 分) ---
        index_configs: list[SlsIndexConfigRecord] = store.get("sls.index_config.list")
        logstores: list[SlsLogstoreRecord] = store.get("sls.logstore.list")
        if index_configs:
            indexed = [ic for ic in index_configs if ic.field_index_count > 0]
            index_ratio = len(indexed) / len(index_configs) if index_configs else 0
            evidence.append(f"日志集成: {len(index_configs)} 个 Logstore 索引配置，字段索引已建立: {len(indexed)} 个")
            if index_ratio >= 0.5:
                score += 1.0
                evidence.append("✓ 日志集成：多数 Logstore 已建立字段索引")
            elif len(indexed) > 0:
                score += 0.5
                evidence.append("ℹ️ 日志集成：已有字段索引但覆盖率较低")
            else:
                evidence.append("⚠️ 日志集成：有 Logstore 但均未建立字段索引")
        elif logstores:
            evidence.append(f"日志集成: {len(logstores)} 个 Logstore（无索引配置数据）")
            score += 0.5
            evidence.append("ℹ️ 日志集成：有 Logstore 但缺少索引配置评估依据")
        else:
            evidence.append("✗ 日志集成：未检测到 SLS Logstore")

        # --- 4. 可视化集成 (最高 1 分) ---
        dashboards: list = store.get("grafana.dashboard.list")
        if dashboards:
            evidence.append(f"可视化集成: {len(dashboards)} 个 Grafana 仪表盘")
            if len(dashboards) >= 3:
                score += 1.0
                evidence.append("✓ 可视化集成：仪表盘覆盖充分")
            else:
                score += 0.5
                evidence.append("ℹ️ 可视化集成：仪表盘数量较少")
        else:
            evidence.append("✗ 可视化集成：未检测到 Grafana 仪表盘")

        final_score = max(min(round(score), 5), 0)

        has_alarm = bool(rules and any(r.enable_state for r in rules))
        has_log = bool(logstores)
        has_visual = bool(dashboards)
        integrated_count = sum([has_alarm, has_log, has_visual])

        if final_score >= 5:
            conclusion = "工具链完善集成：APM + 告警 + 日志 + 可视化全链路打通"
        elif final_score >= 4:
            conclusion = f"工具链集成较好 ({integrated_count}/3 辅助模块)，建议补全缺失环节"
        elif final_score >= 3:
            conclusion = f"工具链部分集成 ({integrated_count}/3 辅助模块)，存在数据孤岛风险"
        elif final_score >= 2:
            conclusion = "工具链集成不足，多个模块缺失或质量较低"
        else:
            conclusion = "工具链几乎未集成，建议尽快引入告警/日志/可视化模块"

        return self._scored(final_score, conclusion, evidence)


class MonCoverageGapAnalyzer(Analyzer):
    """
    监控覆盖差距分析器
    
    评估标准：
    - 核心服务拓扑覆盖率 (4 分)
    - 黄金信号完整性 (4 分)：核心服务必须同时具备 Traffic, Error, Latency 指标
    
    数据来源：
    - UModel：apm.metric.topology（服务调用拓扑）
    - 判断逻辑：将服务拓扑图中的节点与有监控指标的服务进行比对
    """

    def key(self) -> str:
        return "mon_coverage_gap"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "监控能力"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["apm.service.list"]

    def optional_data(self) -> list[str]:
        return ["apm.topology.metrics", "apm.coverage.analysis"]

    def analyze(self, store) -> ScoreResult:
        services: list[ApmServiceRecord] = store.get("apm.service.list")
        if not services:
            return self._not_scored("未获取到 APM 服务数据", [])

        evidence = [f"APM 服务总数: {len(services)}"]
        score = 0.0

        # --- 1. 服务拓扑覆盖率 (最高 4 分) ---
        coverage_data: list[ApmCoverageAnalysisRecord] = store.get("apm.coverage.analysis")
        if coverage_data:
            c = coverage_data[0]
            ratio = c.coverage_ratio or c.coverage_rate or 0.0
            evidence.append(f"服务拓扑覆盖率: {ratio * 100:.1f}% "
                            f"({c.covered_services}/{c.total_deployments or c.total_services} 个应用)")
            if c.untraced_services:
                evidence.append(f"⚠️ 未覆盖服务示例: {', '.join(c.untraced_services[:3])}"
                                f"{'等' if len(c.untraced_services) > 3 else ''}")

            coverage_score = ratio * 4.0  # 0%→0分，100%→4分，平滑评分
            score += coverage_score
            evidence.append(f"拓扑覆盖得分: {coverage_score:.1f}/4")
        else:
            trace_count = sum(1 for s in services if s.trace_enabled)
            trace_ratio = trace_count / len(services) if services else 0
            evidence.append(f"无拓扑覆盖数据，用 Trace 启用率降级估算: "
                            f"{trace_count}/{len(services)} ({trace_ratio * 100:.0f}%)")
            coverage_score = min(trace_ratio * 2.0, 2.0)
            score += coverage_score
            evidence.append(f"拓扑覆盖降级得分: {coverage_score:.1f}/2（无 k8s 对比数据）")

        # --- 2. 黄金信号完整性 (最高 4 分) ---
        if coverage_data:
            c = coverage_data[0]
            has_traffic = c.has_traffic_metric
            has_error = c.has_error_metric
            has_latency = c.has_latency_metric
            signals_count = sum([has_traffic, has_error, has_latency])

            signal_labels = []
            if has_traffic:
                signal_labels.append("Traffic✓")
            else:
                signal_labels.append("Traffic✗")
            if has_error:
                signal_labels.append("Error✓")
            else:
                signal_labels.append("Error✗")
            if has_latency:
                signal_labels.append("Latency✓")
            else:
                signal_labels.append("Latency✗")
            evidence.append(f"黄金信号: {' | '.join(signal_labels)}")

            if c.golden_signals_complete or signals_count == 3:
                signal_score = 4.0
                evidence.append("✓ Traffic/Error/Latency 三个黄金信号均已采集")
            elif signals_count == 2:
                signal_score = 2.5
                missing = [l for l, h in [("Traffic", has_traffic), ("Error", has_error), ("Latency", has_latency)] if
                           not h]
                evidence.append(f"ℹ️ 缺少黄金信号: {', '.join(missing)}")
            elif signals_count == 1:
                signal_score = 1.0
                evidence.append("⚠️ 仅有 1 个黄金信号，监控盲点严重")
            else:
                signal_score = 0
                evidence.append("✗ 未采集任何黄金信号，监控盲点严重")
            score += signal_score
        else:
            rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")
            if rules:
                active = [r for r in rules if r.enable_state]
                latency_kw = ["latency", "p99", "p95", "rt", "response_time"]
                error_kw = ["error", "error_rate", "success_rate", "exception"]
                has_latency_rule = any(
                    any(kw in (r.metric_name or "").lower() for kw in latency_kw) for r in active
                )
                has_error_rule = any(
                    any(kw in (r.metric_name or "").lower() for kw in error_kw) for r in active
                )
                signals_via_alarm = sum([has_latency_rule, has_error_rule])
                evidence.append(f"无覆盖分析数据，通过告警规则间接评估: "
                                f"延迟规则{'\u2713' if has_latency_rule else '\u2717'} | "
                                f"错误规则{'\u2713' if has_error_rule else '\u2717'}")
                signal_score = signals_via_alarm * 1.0
                score += signal_score
            else:
                evidence.append("✗ 无黄金信号评估依据（无覆盖分析也无告警规则）")

        final_score = max(min(round(score), 8), 0)

        if final_score >= 7:
            conclusion = "核心服务监控覆盖完善，黄金信号完整，监控盲点极少"
        elif final_score >= 5:
            conclusion = "监控覆盖较好，黄金信号基本完备，建议补全拓扑覆盖"
        elif final_score >= 3:
            conclusion = "监控覆盖存在明显差距，建议补全黄金信号与拓扑覆盖"
        elif final_score >= 1:
            conclusion = "监控覆盖严重不足，建议尽快建设 APM 与黄金信号采集"
        else:
            conclusion = "监控覆盖几乎为零，监控体系尚未建立"

        return self._scored(final_score, conclusion, evidence)


MONITORING_ANALYZERS = [
    MonMetricsDepthAnalyzer(),
    MonMetricsStdAnalyzer(),
    MonAlertRulesAnalyzer(),
    MonAlertSeverityAnalyzer(),
    MonAlertChannelsAnalyzer(),
    MonToolIntegrationAnalyzer(),
    MonCoverageGapAnalyzer(),
]
