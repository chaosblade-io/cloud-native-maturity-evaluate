"""
Resilience 维度 - 健康管理 (Health Management) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)                | 分值 | 评分标准                                                       |
| hm_health_checks            | 6    | 健康检查：配置 Liveness、Readiness 和 Startup 探针，且逻辑合理 |
| hm_self_healing             | 6    | 自动恢复：根据健康检查结果自动重启容器、剔除坏节点             |
| hm_chaos_engineering        | 8    | 混沌工程：定期注入故障以验证系统韧性                           |
| hm_proactive_monitoring     | 8    | 主动监控：基于趋势预测提前告警，而非仅在故障发生后告警         |
"""

from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema.k8s import K8sPodProbesRecord, K8sEventRecord
from sesora.schema.chaos import ChaosExperimentRecord, ChaosExperimentRunRecord
from sesora.schema.cms import CmsAlarmRuleRecord, CmsAlarmSloRecord
from datetime import datetime, timezone, timedelta


class HmHealthChecksAnalyzer(Analyzer):
    """
    健康检查分析器

    评估标准：是否配置了 Liveness (存活)、Readiness (就绪) 和 Startup (启动) 探针，且逻辑合理（不仅检查端口）

    数据来源：
    - ACK API：Pod spec 中的 livenessProbe、readinessProbe、startupProbe 字段
    - 检查探针类型是否为 httpGet（业务层检查）而非简单 tcpSocket
    """

    def key(self) -> str:
        return "hm_health_checks"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "健康管理"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.pod.probes"]

    def analyze(self, store) -> ScoreResult:
        probes: list[K8sPodProbesRecord] = store.get("k8s.pod.probes")

        if not probes:
            return self._not_evaluated("未获取到 Pod 探针配置信息")

        total = len(probes)
        score = 0.0
        evidence = []
        warnings = []

        # --- 1. Liveness 探针覆盖率评分（最高 1.5 分）---
        with_liveness = sum(1 for p in probes if p.liveness_probe is not None)
        liveness_rate = with_liveness / total if total else 0

        if liveness_rate >= 0.8:
            score += 1.5
            evidence.append(f"✓ Liveness 覆盖率: {liveness_rate * 100:.1f}%")
        elif liveness_rate >= 0.5:
            score += 1.0
            evidence.append(f"Liveness 覆盖率: {liveness_rate * 100:.1f}%")
        elif liveness_rate > 0:
            score += 0.5
            warnings.append(f"Liveness 探针覆盖率偏低 ({liveness_rate * 100:.1f}%)")
            evidence.append(f"⚠️ Liveness 覆盖率: {liveness_rate * 100:.1f}%")
        else:
            warnings.append("未配置 Liveness 探针，无法检测容器存活状态")
            evidence.append("❌ Liveness 覆盖率: 0%")

        # --- 2. Readiness 探针覆盖率评分（最高 1.5 分）---
        with_readiness = sum(1 for p in probes if p.readiness_probe is not None)
        readiness_rate = with_readiness / total if total else 0

        if readiness_rate >= 0.8:
            score += 1.5
            evidence.append(f"✓ Readiness 覆盖率: {readiness_rate * 100:.1f}%")
        elif readiness_rate >= 0.5:
            score += 1.0
            evidence.append(f"Readiness 覆盖率: {readiness_rate * 100:.1f}%")
        elif readiness_rate > 0:
            score += 0.5
            warnings.append(f"Readiness 探针覆盖率偏低 ({readiness_rate * 100:.1f}%)")
            evidence.append(f"⚠️ Readiness 覆盖率: {readiness_rate * 100:.1f}%")
        else:
            warnings.append("未配置 Readiness 探针，无法检测服务就绪状态")
            evidence.append("❌ Readiness 覆盖率: 0%")

        # --- 3. Startup 探针覆盖率评分（最高 1 分）---
        with_startup = sum(1 for p in probes if p.startup_probe is not None)
        startup_rate = with_startup / total if total else 0

        if startup_rate >= 0.5:
            score += 1.0
            evidence.append(f"✓ Startup 覆盖率: {startup_rate * 100:.1f}%")
        elif startup_rate > 0:
            score += 0.5
            evidence.append(f"Startup 覆盖率: {startup_rate * 100:.1f}%")
        else:
            evidence.append("ℹ️ Startup 覆盖率: 0% (适用于慢启动应用)")

        # --- 4. HTTP 探针质量评分（最高 1.5 分）---
        pods_with_http_probe = sum(
            1 for p in probes
            if (p.liveness_probe and p.liveness_probe.probe_type == "httpGet") or
            (p.readiness_probe and p.readiness_probe.probe_type == "httpGet") or
            (p.startup_probe and p.startup_probe.probe_type == "httpGet")
        )
        http_rate = pods_with_http_probe / total if total else 0

        if http_rate >= 0.7:
            score += 1.5
            evidence.append(f"✓ HTTP 探针质量优秀: {http_rate * 100:.1f}% Pod 使用 HTTP 探针")
        elif http_rate >= 0.4:
            score += 1.0
            evidence.append(f"HTTP 探针质量良好: {http_rate * 100:.1f}% Pod 使用 HTTP 探针")
        elif http_rate > 0:
            score += 0.5
            evidence.append(f"HTTP 探针比例: {http_rate * 100:.1f}%")
        else:
            warnings.append("未使用 HTTP 探针，建议配置 HTTP 端点检查以获取更准确的业务健康状态")
            evidence.append("⚠️ HTTP 探针: 0% (建议配置 /health 端点)")

        # --- 5. 探针完整性检查 ---
        both_probes = sum(
            1 for p in probes
            if p.liveness_probe is not None and p.readiness_probe is not None
        )
        both_rate = both_probes / total if total else 0

        if both_rate >= 0.6:
            score += 0.5
            evidence.append(f"✓ 探针配置完整: {both_rate * 100:.1f}% Pod 同时配置 Liveness+Readiness")
        else:
            if both_rate > 0:
                evidence.append(f"ℹ️ 同时配置 Liveness+Readiness: {both_rate * 100:.1f}%")

        # --- 6. 状态判定 ---
        final_score = max(min(round(score, 1), 6), 0)

        if final_score >= 5:
            status_msg = "健康检查配置成熟：覆盖全面、HTTP 探针质量高"
        elif final_score >= 4:
            status_msg = "健康检查配置良好：基本满足要求，建议提升 HTTP 探针比例"
        elif final_score >= 2.5:
            status_msg = "健康检查配置基础：存在覆盖不足或探针类型单一"
        elif final_score >= 1:
            status_msg = "健康检查配置薄弱：探针覆盖率偏低，建议全面配置"
        else:
            status_msg = "健康检查配置缺失：缺乏基本的容器健康检测"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HmSelfHealingAnalyzer(Analyzer):
    """
    自动恢复分析器

    评估标准：系统是否能根据健康检查结果自动重启容器、剔除坏节点或重新调度实例，无需人工干预

    数据来源：
    - UModel：k8s.event.events，K8s Events 数据
    - 包含 reason: OOMKilled、reason: BackOff、reason: Evicted 等字段
    - kube-state-metrics：kube_pod_container_status_restarts_total，容器重启次数
    """

    def key(self) -> str:
        return "hm_self_healing"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "健康管理"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.event.list"]

    def analyze(self, store) -> ScoreResult:
        events: list[K8sEventRecord] = store.get("k8s.event.list")

        if not events:
            return self._not_evaluated("未获取到 K8s 事件数据")

        score = 0.0
        evidence = []
        warnings = []

        now = datetime.now(timezone.utc)
        recent_threshold = now - timedelta(days=7)

        restart_events = [
            e for e in events
            if e.reason in ("BackOff", "Unhealthy", "Killing")
        ]
        recent_restarts = [
            e for e in restart_events
            if e.last_timestamp and e.last_timestamp > recent_threshold
        ]

        oom_events = [
            e for e in events
            if "OOM" in e.reason or "OOMKilled" in e.message
        ]
        recent_ooms = [
            e for e in oom_events
            if e.last_timestamp and e.last_timestamp > recent_threshold
        ]

        evicted_events = [e for e in events if e.reason == "Evicted"]
        recent_evictions = [
            e for e in evicted_events
            if e.last_timestamp and e.last_timestamp > recent_threshold
        ]

        total_events = len(restart_events) + len(oom_events) + len(evicted_events)
        recent_total = len(recent_restarts) + len(recent_ooms) + len(recent_evictions)

        # --- 2. 自愈活跃度评分（最高 2 分）---
        if recent_total > 0:
            if recent_total <= 5:
                score += 2.0
                evidence.append(f"✓ 自愈机制活跃: 近7天 {recent_total} 次自愈事件")
            elif recent_total <= 20:  # 中等事件量
                score += 1.5
                evidence.append(f"ℹ️ 自愈机制活跃: 近7天 {recent_total} 次自愈事件")
                warnings.append(f"近期自愈事件较多 ({recent_total} 次)，建议检查系统稳定性")
            else:
                score += 0.5
                warnings.append(f"近期自愈事件频繁 ({recent_total} 次)，系统可能存在稳定性问题")
                evidence.append(f"⚠️ 自愈事件频繁: 近7天 {recent_total} 次")
        else:
            if total_events > 0:
                score += 1.0
                evidence.append(f"ℹ️ 近期无自愈事件，历史共 {total_events} 次")
            else:
                score += 0.5
                evidence.append("ℹ️ 暂无自愈事件记录（可能是新部署或系统非常稳定）")

        # --- 3. 事件类型覆盖评分（最高 2 分）---
        event_types = []
        if restart_events:
            event_types.append("容器重启")
            evidence.append(f"✓ 容器重启自愈: {len(restart_events)} 次")
        if oom_events:
            event_types.append("OOM 恢复")
            evidence.append(f"✓ OOM 自愈: {len(oom_events)} 次")
        if evicted_events:
            event_types.append("Pod 驱逐")
            evidence.append(f"✓ Pod 驱逐自愈: {len(evicted_events)} 次")

        type_count = len(event_types)
        if type_count >= 3:
            score += 2.0
            evidence.append(f"✓ 自愈类型全面: 覆盖 {', '.join(event_types)}")
        elif type_count == 2:
            score += 1.5
            evidence.append(f"✓ 自愈类型良好: 覆盖 {', '.join(event_types)}")
        elif type_count == 1:
            score += 0.5
            evidence.append(f"ℹ️ 自愈类型单一: 仅 {event_types[0]}")
        else:
            warnings.append("未发现自愈事件，无法评估自愈能力")

        # --- 4. 自愈严重性评估（扣分项）---
        severe_events = len(oom_events) + len(evicted_events)
        if severe_events > 10:
            score -= 0.5
            warnings.append(f"发现 {severe_events} 次严重故障事件（OOM/驱逐），建议优化资源配置")
            evidence.append(f"⚠️ 严重故障事件: {severe_events} 次")

        final_score = max(min(round(score, 1), 6), 0)

        if final_score >= 5:
            status_msg = "自愈机制成熟：活跃度高、类型覆盖全面"
        elif final_score >= 4:
            status_msg = "自愈机制良好：具备基本的自动恢复能力"
        elif final_score >= 2.5:
            status_msg = "自愈机制基础：有自愈记录但类型或活跃度有待提升"
        elif final_score >= 1:
            status_msg = "自愈机制薄弱：自愈记录较少或类型单一"
        else:
            status_msg = "自愈机制未验证：暂无自愈事件记录"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HmChaosEngineeringAnalyzer(Analyzer):
    """
    混沌工程分析器

    评估标准：是否在生产或准生产环境中定期注入故障（网络延迟、Pod 杀除、CPU 满载）以验证系统韧性

    数据来源：
    - Chaos Mesh API（若使用 ACK 托管版）：实验历史列表
    - 检查过去一段时间内是否有实验记录，以及实验类型是否覆盖核心场景
    """

    def key(self) -> str:
        return "hm_chaos_engineering"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "健康管理"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["chaos.experiment.list"]

    def optional_data(self) -> list[str]:
        return ["chaos.experiment_run.list"]

    def analyze(self, store) -> ScoreResult:
        experiments: list[ChaosExperimentRecord] = store.get("chaos.experiment.list")

        score = 0.0
        evidence = []
        warnings = []

        if not experiments:
            evidence.append("ℹ️ 未配置混沌工程实验")
            return self._scored(
                0,
                "未实施混沌工程：高级实践，当前无故障注入验证能力",
                evidence
            )

        total_experiments = len(experiments)
        evidence.append(f"混沌实验数量: {total_experiments}")
        now = datetime.now(timezone.utc)
        recent_threshold = now - timedelta(days=30)

        # --- 1. 实验配置评分（最高 2 分）---
        if total_experiments >= 5:
            score += 2.0
            evidence.append(f"✓ 实验配置丰富: {total_experiments} 个实验")
        elif total_experiments >= 3:
            score += 1.5
            evidence.append(f"✓ 实验配置良好: {total_experiments} 个实验")
        elif total_experiments >= 1:
            score += 1.0
            evidence.append(f"实验配置: {total_experiments} 个实验")
        else:
            score += 0.5

        # --- 2. 实验类型多样性评分（最高 2 分）---
        experiment_types = set(e.experiment_type for e in experiments)
        type_count = len(experiment_types)

        if type_count >= 4:
            score += 2.0
            evidence.append(f"✓ 实验类型丰富: {', '.join(experiment_types)}")
        elif type_count == 3:
            score += 1.5
            evidence.append(f"✓ 实验类型良好: {', '.join(experiment_types)}")
        elif type_count == 2:
            score += 1.0
            evidence.append(f"实验类型: {', '.join(experiment_types)}")
        else:
            score += 0.5
            warnings.append("实验类型单一，建议增加网络延迟、CPU满载、Pod杀除等多种故障类型")
            evidence.append(f"实验类型单一: {', '.join(experiment_types)}")

        # --- 3. 实验执行活跃度评分（最高 3 分）---
        if store.available("chaos.experiment_run.list"):
            runs: list[ChaosExperimentRunRecord] = store.get(
                "chaos.experiment_run.list"
            )

            if runs:
                finished_runs = [r for r in runs if r.status == "Finished"]
                recent_finished = [
                    r for r in finished_runs
                    if r.start_time and r.start_time > recent_threshold
                ]

                total_runs = len(runs)
                finished_count = len(finished_runs)
                recent_finished_count = len(recent_finished)

                if recent_finished_count >= 4:
                    score += 2.0
                    evidence.append(f"✓ 实验执行活跃: 近30天完成 {recent_finished_count} 次")
                elif recent_finished_count >= 1:
                    score += 1.0
                    evidence.append(f"实验执行: 近30天完成 {recent_finished_count} 次")
                elif finished_count > 0:
                    score += 0.5
                    warnings.append("近期无实验执行记录，建议定期执行混沌实验")
                    evidence.append(f"ℹ️ 历史完成: {finished_count} 次，近期无执行")
                else:
                    warnings.append("实验未执行或未完成，建议运行实验验证系统韧性")
                    evidence.append(f"⚠️ 实验运行: {total_runs} 次，完成 0 次")

                if total_runs > 0:
                    success_rate = finished_count / total_runs
                    if success_rate >= 0.8:
                        score += 1.0
                        evidence.append(f"✓ 实验成功率高: {success_rate * 100:.0f}%")
                    elif success_rate >= 0.5:
                        score += 0.5
                        evidence.append(f"实验成功率: {success_rate * 100:.0f}%")
                    else:
                        warnings.append(f"实验成功率偏低 ({success_rate * 100:.0f}%)，建议检查实验配置")
                        evidence.append(f"⚠️ 实验成功率: {success_rate * 100:.0f}%")
            else:
                warnings.append("有实验配置但无执行记录，建议运行实验")
                evidence.append("⚠️ 无实验执行记录")
        else:
            warnings.append("无法获取实验执行记录，建议配置 chaos.experiment_run.list 数据源")
            evidence.append("ℹ️ 无实验执行数据")

        final_score = max(min(round(score, 1), 8), 0)

        if final_score >= 7:
            status_msg = "混沌工程成熟：实验丰富、类型多样、定期执行"
        elif final_score >= 5.5:
            status_msg = "混沌工程良好：具备基本的故障注入验证能力"
        elif final_score >= 4:
            status_msg = "混沌工程基础：有实验配置但执行或类型有待完善"
        elif final_score >= 2:
            status_msg = "混沌工程薄弱：实验配置或执行不足"
        else:
            status_msg = "未实施混沌工程：缺乏故障注入验证"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class HmProactiveMonitoringAnalyzer(Analyzer):
    """
    主动监控分析器

    评估标准：是否基于趋势预测（如磁盘将满、内存泄漏趋势）提前告警，而非仅在故障发生后告警

    数据来源：
    - 云监控 CMS：告警规则列表
    - 检查规则表达式中是否包含 predict_linear 或类似的趋势预测函数
    - 若全是 current_value > threshold 类型的规则，说明缺乏主动性
    """

    def key(self) -> str:
        return "hm_proactive_monitoring"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "健康管理"

    def max_score(self) -> int:
        return 8

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def optional_data(self) -> list[str]:
        return ["cms.alarm_rule.slo_analysis"]

    def analyze(self, store) -> ScoreResult:
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")

        score = 0.0
        evidence = []
        warnings = []

        # 未配置告警规则
        if not rules:
            evidence.append("❌ 未配置告警规则")
            return self._scored(
                0,
                "未配置监控告警：缺乏基本的故障检测能力",
                evidence
            )

        total_rules = len(rules)
        evidence.append(f"告警规则数量: {total_rules}")

        # --- 1. 告警规则覆盖率评分（最高 2 分）---
        if total_rules >= 20:
            score += 2.0
            evidence.append(f"✓ 告警规则丰富: {total_rules} 个")
        elif total_rules >= 10:
            score += 1.5
            evidence.append(f"✓ 告警规则良好: {total_rules} 个")
        elif total_rules >= 5:
            score += 1.0
            evidence.append(f"告警规则数量: {total_rules} 个")
        else:
            score += 0.5
            warnings.append(f"告警规则数量较少 ({total_rules} 个)，建议增加监控覆盖")
            evidence.append(f"⚠️ 告警规则数量: {total_rules} 个")

        # --- 2. 预测性告警能力评分（最高 3 分）---
        has_predictive = False

        if store.available("cms.alarm_rule.slo_analysis"):
            slo_analysis: list[CmsAlarmSloRecord] = store.get(
                "cms.alarm_rule.slo_analysis"
            )

            if slo_analysis:
                predictive_rules = [r for r in slo_analysis if r.has_predictive]
                slo_rules = [r for r in slo_analysis if r.is_slo_based]

                predictive_count = len(predictive_rules)

                if predictive_count >= 3:
                    score += 3.0
                    evidence.append(f"✓ 预测性告警完善: {predictive_count} 个趋势预测规则")
                    has_predictive = True
                elif predictive_count >= 1:
                    score += 2.0
                    evidence.append(f"✓ 预测性告警: {predictive_count} 个趋势预测规则")
                    has_predictive = True

                slo_count = len(slo_rules)
                if slo_count >= 3 and not has_predictive:
                    score += 1.5
                    evidence.append(f"✓ SLO 基础告警: {slo_count} 个规则")
                elif slo_count >= 1 and not has_predictive:
                    score += 0.5
                    evidence.append(f"SLO 基础告警: {slo_count} 个规则")
            else:
                evidence.append("ℹ️ 无 SLO 分析数据")
        else:
            predictive_keywords = [
                "predict", "trend", "forecast", "预测", "趋势",
                "linear", "deriv", "rate", "increase", "growth"
            ]

            predictive_by_name = [
                r for r in rules
                if any(kw in r.rule_name.lower() for kw in predictive_keywords)
            ]

            predictive_by_expr = []
            for r in rules:
                if r.expression:
                    expr = r.expression.lower()
                    if any(kw in expr for kw in predictive_keywords):
                        predictive_by_expr.append(r)

            predictive_count = len(set(predictive_by_name + predictive_by_expr))

            if predictive_count >= 3:
                score += 2.0
                evidence.append(f"✓ 疑似预测性告警: {predictive_count} 个规则（基于名称/表达式）")
                has_predictive = True
            elif predictive_count >= 1:
                score += 1.0
                evidence.append(f"疑似预测性告警: {predictive_count} 个规则（基于名称/表达式）")
                has_predictive = True

            if not has_predictive:
                warnings.append("未检测到预测性告警规则，建议配置趋势预测类告警（如磁盘将满、内存泄漏）")
                evidence.append("ℹ️ 预测性告警: 未检测（建议配置 predict_linear 等趋势函数）")

        # --- 3. 告警规则质量评分（最高 2 分）---
        quality_score = 0.0

        # 检查是否有通知渠道配置
        rules_with_notification = [
            r for r in rules
            if r.contact_groups or r.webhook_url or r.action_types
        ]
        if len(rules_with_notification) >= total_rules * 0.8:
            quality_score += 0.5
            evidence.append(f"✓ 告警通知配置完善: {len(rules_with_notification)}/{total_rules}")
        elif rules_with_notification:
            quality_score += 0.25
            evidence.append(f"告警通知配置: {len(rules_with_notification)}/{total_rules}")
        else:
            warnings.append("告警规则缺少通知渠道配置，建议配置联系人/通知组")

        level_counts = {}
        for r in rules:
            level = r.level if r.level else "Unknown"
            level_counts[level] = level_counts.get(level, 0) + 1

        if len(level_counts) >= 3:
            quality_score += 0.5
            evidence.append(f"✓ 告警分级完善: {len(level_counts)} 个级别 ({', '.join(level_counts.keys())})")
        elif len(level_counts) >= 2:
            quality_score += 0.25
            evidence.append(f"告警分级: {len(level_counts)} 个级别 ({', '.join(level_counts.keys())})")

        rules_with_webhook = [r for r in rules if r.webhook_url]
        if len(rules_with_webhook) >= total_rules * 0.3:
            quality_score += 0.5
            evidence.append(f"✓ Webhook 自动化配置: {len(rules_with_webhook)} 个规则")
        elif rules_with_webhook:
            quality_score += 0.25
            evidence.append(f"Webhook 配置: {len(rules_with_webhook)} 个规则")

        enabled_rules = [r for r in rules if r.enable_state]
        enabled_ratio = len(enabled_rules) / total_rules if total_rules else 0
        if enabled_ratio >= 0.9:
            quality_score += 0.5
            evidence.append(f"✓ 规则启用率高: {len(enabled_rules)}/{total_rules}")
        elif enabled_ratio >= 0.7:
            quality_score += 0.25
            evidence.append(f"规则启用率: {len(enabled_rules)}/{total_rules}")
        else:
            disabled_count = total_rules - len(enabled_rules)
            warnings.append(f"有 {disabled_count} 个规则未启用，建议检查或清理")

        score += min(quality_score, 2.0)

        # --- 4. 主动监控覆盖率评分（最高 1 分）---
        resource_keywords = ['cpu', 'memory', 'disk', 'network', 'load']
        app_keywords = ['jvm', 'gc', 'thread', 'connection', 'pool']
        business_keywords = ['qps', 'latency', 'error', 'success', 'rate']

        resource_rules = sum(
            1 for r in rules
            if any(kw in r.rule_name.lower() for kw in resource_keywords)
        )
        app_rules = sum(
            1 for r in rules
            if any(kw in r.rule_name.lower() for kw in app_keywords)
        )
        business_rules = sum(
            1 for r in rules
            if any(kw in r.rule_name.lower() for kw in business_keywords)
        )

        coverage_types = sum([
            1 for count in [resource_rules, app_rules, business_rules] if count > 0
        ])

        if coverage_types >= 3:
            score += 1.0
            evidence.append(f"✓ 监控维度全面: 资源({resource_rules}) 应用({app_rules}) 业务({business_rules})")
        elif coverage_types == 2:
            score += 0.5
            evidence.append(f"监控维度: 资源({resource_rules}) 应用({app_rules}) 业务({business_rules})")
        else:
            evidence.append(f"ℹ️ 监控维度单一: 资源({resource_rules}) 应用({app_rules}) 业务({business_rules})")

        final_score = max(min(round(score, 1), 8), 0)

        if final_score >= 7:
            status_msg = "主动监控成熟：预测性告警完善、规则质量高、维度全面"
        elif final_score >= 5.5:
            status_msg = "主动监控良好：具备趋势预测能力，规则配置较完善"
        elif final_score >= 4:
            status_msg = "主动监控基础：有基本告警覆盖，建议增加预测性规则"
        elif final_score >= 2:
            status_msg = "主动监控薄弱：告警规则数量或质量有待提升"
        else:
            status_msg = "主动监控缺失：缺乏有效的预测性监控能力"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


HEALTH_ANALYZERS = [
    HmHealthChecksAnalyzer(),
    HmSelfHealingAnalyzer(),
    HmChaosEngineeringAnalyzer(),
    HmProactiveMonitoringAnalyzer(),
]
