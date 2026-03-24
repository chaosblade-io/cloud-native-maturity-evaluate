"""
Resilience 维度 - 健康管理 (Health Management) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)                | 分值 | 评分标准                                                       |
| hm_health_checks            | 6    | 健康检查：配置 Liveness、Readiness 和 Startup 探针，且逻辑合理 |
| hm_self_healing             | 6    | 自动恢复：根据健康检查结果自动重启容器、剔除坏节点             |
| hm_chaos_engineering        | 8    | 混沌工程：定期注入故障以验证系统韧性                           |
| hm_proactive_monitoring     | 8    | 主动监控：基于趋势预测提前告警，而非仅在故障发生后告警         |
"""

from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sPodProbesRecord, K8sEventRecord
from ...schema.chaos import ChaosExperimentRecord, ChaosExperimentRunRecord
from ...schema.cms import CmsAlarmRuleRecord, CmsAlarmSloRecord


class HmHealthChecks(Analyzer):
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

        with_liveness = sum(1 for p in probes if p.liveness_probe is not None)
        with_readiness = sum(1 for p in probes if p.readiness_probe is not None)
        with_startup = sum(1 for p in probes if p.startup_probe is not None)

        with_http_liveness = sum(
            1
            for p in probes
            if p.liveness_probe and p.liveness_probe.probe_type == "httpGet"
        )
        with_http_readiness = sum(
            1
            for p in probes
            if p.readiness_probe and p.readiness_probe.probe_type == "httpGet"
        )
        with_http_startup = sum(
            1
            for p in probes
            if p.startup_probe and p.startup_probe.probe_type == "httpGet"
        )

        score = 0
        evidence = []

        def add_evidence(name, count, total_count):
            rate = count / total_count if total_count else 0
            display_rate = f"{rate * 100:.1f}"
            return rate, f"{name} 覆盖率: {display_rate}%"

        liveness_rate, liv_msg = add_evidence("Liveness", with_liveness, total)
        if liveness_rate >= 0.8:
            score += 2
            evidence.append(f"✓ {liv_msg}")
        elif liveness_rate > 0:
            score += 1
            evidence.append(liv_msg)
        elif with_liveness == 0:
            evidence.append("⚠ 缺少 Liveness 探针配置")

        readiness_rate, read_msg = add_evidence("Readiness", with_readiness, total)
        if readiness_rate >= 0.8:
            score += 2
            evidence.append(f"✓ {read_msg}")
        elif readiness_rate > 0:
            score += 1
            evidence.append(read_msg)
        elif with_readiness == 0:
            evidence.append("⚠ 缺少 Readiness 探针配置")

        configured_probes_count = with_liveness + with_readiness + with_startup
        http_probes_count = with_http_liveness + with_http_readiness + with_http_startup

        if configured_probes_count > 0:
            http_rate = http_probes_count / configured_probes_count
            http_msg = f"HTTP 协议探针比例: {http_rate * 100:.1f}%"

            if http_rate >= 0.5:
                score += 2
                evidence.append(f"✓ {http_msg}")
            elif http_rate > 0:
                score += 1
                evidence.append(http_msg)

        if with_startup > 0:
            startup_rate = with_startup / total
            evidence.append(
                f"ℹ️ Startup 探针覆盖率: {startup_rate * 100:.1f}% (有助于慢启动应用)"
            )

        if score >= 5:
            return self._scored(6, "健康检查配置完善", evidence)
        elif score >= 3:
            return self._scored(score, "健康检查配置基本满足", evidence)
        elif score > 0:
            return self._scored(score, "健康检查配置不完整", evidence)
        else:
            return self._not_scored("探针配置质量极低或未识别有效配置", evidence)


class HmSelfHealing(Analyzer):
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

        # 统计自愈相关事件
        restart_events = [
            e for e in events if e.reason in ("BackOff", "Unhealthy", "Killing")
        ]
        oom_events = [
            e for e in events if "OOM" in e.reason or "OOMKilled" in e.message
        ]
        evicted_events = [e for e in events if e.reason == "Evicted"]

        evidence = []

        if restart_events:
            evidence.append(f"容器重启事件: {len(restart_events)} 次")
        if oom_events:
            evidence.append(f"OOM 事件: {len(oom_events)} 次")
        if evicted_events:
            evidence.append(f"Pod 驱逐事件: {len(evicted_events)} 次")

        # 有自愈事件说明系统在工作
        total_healing_events = (
            len(restart_events) + len(oom_events) + len(evicted_events)
        )

        if total_healing_events > 0:
            return self._scored(6, "K8s 自愈机制运行正常，已有自动恢复记录", evidence)
        else:
            return self._scored(
                4, "K8s 自愈机制已配置，暂无触发记录", ["近期无异常需要自愈"]
            )


class HmChaosEngineering(Analyzer):
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

        if not experiments:
            return self._not_scored("未配置混沌工程实验，无法验证系统韧性", [])

        score = 2  # 基础分：有实验配置
        evidence = [f"混沌实验数量: {len(experiments)}"]

        # 检查实验类型多样性
        experiment_types = set(e.experiment_type for e in experiments)

        if len(experiment_types) >= 4:
            score += 3
            evidence.append(f"✓ 实验类型丰富: {', '.join(experiment_types)}")
        elif len(experiment_types) >= 2:
            score += 2
            evidence.append(f"实验类型: {', '.join(experiment_types)}")
        else:
            score += 1
            evidence.append(f"实验类型单一: {', '.join(experiment_types)}")

        # 检查是否有执行记录
        if store.available("chaos.experiment_run.list"):
            runs: list[ChaosExperimentRunRecord] = store.get(
                "chaos.experiment_run.list"
            )
            finished_runs = [r for r in runs if r.status == "Finished"]
            if finished_runs:
                score += 3
                evidence.append(f"✓ 已完成实验: {len(finished_runs)} 次")
            elif runs:
                score += 1
                evidence.append(f"有实验运行记录")

        return self._scored(min(score, 8), "已实施混沌工程实践", evidence)


class HmProactiveMonitoring(Analyzer):
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

        if not rules:
            return self._not_scored("未配置告警规则", [])

        score = 2  # 基础分：有告警
        evidence = [f"告警规则数量: {len(rules)}"]

        # 检查是否有预测性告警（通过 SLO 分析数据）
        if store.available("cms.alarm_rule.slo_analysis"):
            slo_analysis: list[CmsAlarmSloRecord] = store.get(
                "cms.alarm_rule.slo_analysis"
            )

            predictive_rules = [r for r in slo_analysis if r.has_predictive]
            if predictive_rules:
                score += 4
                evidence.append(f"✓ 预测性告警规则: {len(predictive_rules)} 个")

            slo_rules = [r for r in slo_analysis if r.is_slo_based]
            if slo_rules:
                score += 2
                evidence.append(f"✓ SLO 基础告警规则: {len(slo_rules)} 个")
        else:
            # 没有 SLO 分析数据，检查规则名称是否包含预测性关键词
            predictive_keywords = [
                "predict",
                "trend",
                "forecast",
                "预测",
                "趋势",
                "linear",
            ]
            predictive_by_name = [
                r
                for r in rules
                if any(kw in r.rule_name.lower() for kw in predictive_keywords)
            ]
            if predictive_by_name:
                score += 3
                evidence.append(f"疑似预测性规则: {len(predictive_by_name)} 个")

        if score >= 7:
            return self._scored(8, "主动监控能力完善，具备预测性告警", evidence)
        elif score >= 4:
            return self._scored(score, "具备基础监控能力", evidence)
        else:
            return self._scored(score, "监控能力有待加强", evidence)


# 导出所有分析器
HEALTH_ANALYZERS = [
    HmHealthChecks(),
    HmSelfHealing(),
    HmChaosEngineering(),
    HmProactiveMonitoring(),
]
