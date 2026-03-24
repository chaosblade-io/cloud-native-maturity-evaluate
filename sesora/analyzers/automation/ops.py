"""
Automation 维度 - 运维自动化 (Operations Automation) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)        | 分值 | 评分标准                                            |
| ------------------- | ---- | --------------------------------------------------- |
| incident_management | 6    | 故障自动发现、自动告警、甚至自动愈合 (Self-healing) |
| scaling_automation  | 6    | 基于指标 (CPU/Mem/QPS) 自动扩缩容 (HPA/VPA)         |
| backup_automation   | 5    | 数据/状态定期自动备份及恢复演练自动化               |
| security_automation | 7    | 漏洞扫描、补丁更新、密钥轮换自动化                  |
"""
from datetime import datetime, timedelta, timezone

from ...core.analyzer import Analyzer, ScoreResult
from ...schema.cms import CmsAlarmRuleRecord, CmsEventTriggerRecord
from ...schema.k8s import K8sHpaRecord, K8sVpaRecord, K8sCronJobRecord
from ...schema.rds_oss import RdsBackupPolicyRecord
from ...schema.acr import AcrImageScanResultRecord
from ...schema.codeup import CodeupPipelineStageRecord


class IncidentManagementAnalyzer(Analyzer):
    """
    故障管理自动化分析器
    
    评估标准：故障自动发现、自动告警、甚至自动愈合 (Self-healing)
    
    数据来源：
    - 云监控 CMS：告警规则列表 API（DescribeAlarmRuleList），检查是否存在有效的告警规则
    - 云监控 CMS / EventBridge：告警触发的自动化动作配置，检查是否绑定了 Webhook 或 Function
    """

    def key(self) -> str:
        return "incident_management"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "运维自动化"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["cms.alarm_rule.list"]

    def optional_data(self) -> list[str]:
        return ["cms.event_trigger.list"]

    def analyze(self, store) -> ScoreResult:
        rules: list[CmsAlarmRuleRecord] = store.get("cms.alarm_rule.list")

        if not rules:
            return self._not_evaluated("未获取到告警规则数据")

        evidence = []
        score = 0

        # 1. 检查告警规则（故障自动发现）
        enabled_rules = [r for r in rules if r.enable_state]

        if not enabled_rules:
            return self._not_scored(
                "告警规则均未启用，无法自动发现故障",
                [f"共 {len(rules)} 条规则，均未启用"]
            )

        evidence.append(f"启用的告警规则: {len(enabled_rules)}/{len(rules)} 条")
        score += 2

        # 2. 检查告警通知（自动告警）
        rules_with_notification = [r for r in enabled_rules if r.has_notification]
        if rules_with_notification:
            score += 2
            evidence.append(f"配置通知的规则: {len(rules_with_notification)} 条")
        else:
            evidence.append("⚠ 告警规则未配置通知")

        # 3. 检查自动化动作（Self-healing）
        healing_score = 0
        if store.available("cms.event_trigger.list"):
            triggers: list[CmsEventTriggerRecord] = store.get("cms.event_trigger.list")

            if triggers:
                is_enabled = [t for t in triggers if t.enabled]
                if is_enabled:
                    # 根据启用的触发器数量细化评分
                    enabled_count = len(is_enabled)
                    if enabled_count >= 5:
                        healing_score = 2
                        evidence.append(f"配置自动化动作的触发器: {enabled_count} 个 (覆盖完善)")
                    elif enabled_count >= 2:
                        healing_score = 1.5
                        evidence.append(f"配置自动化动作的触发器: {enabled_count} 个 (覆盖良好)")
                    else:
                        healing_score = 1
                        evidence.append(f"配置自动化动作的触发器: {enabled_count} 个 (初步覆盖)")
                else:
                    evidence.append("⚠ 存在事件触发器但均未启用自动化动作")
            else:
                evidence.append("⚠ 未获取到事件触发器数据，无法评估自动化动作配置")
        else:
            evidence.append("⚠ 未获取到事件触发器数据，无法评估自动化动作配置")

        score += healing_score

        if score >= 5.5:
            return self._scored(6, "故障自动发现、自动告警、自动愈合 (Self-healing) 完善", evidence)
        elif score >= 4.5:
            return self._scored(5, "故障自动发现、自动告警完善，具备初步自愈能力", evidence)
        elif score >= 3.5:
            return self._scored(4, "故障自动发现和告警能力良好", evidence)
        elif score >= 2.5:
            return self._scored(3, "具备故障自动发现和基础告警能力", evidence)
        elif score >= 1.5:
            return self._scored(2, "具备基础故障自动发现能力", evidence)
        else:
            return self._scored(1, "故障管理自动化能力非常有限", evidence)


class ScalingAutomationAnalyzer(Analyzer):
    """
    扩缩容自动化分析器
    
    评估标准：基于指标 (CPU/Mem/QPS) 自动扩缩容 (HPA/VPA)
    
    数据来源：
    - ACK API：GET /apis/autoscaling/v2/namespaces/{ns}/horizontalpodautoscalers
      获取 HPA 列表，检查 spec.minReplicas 与 spec.maxReplicas 是否不同
    """

    def key(self) -> str:
        return "scaling_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "运维自动化"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.hpa.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.vpa.list"]

    def analyze(self, store) -> ScoreResult:
        hpas: list[K8sHpaRecord] = store.get("k8s.hpa.list")

        if not hpas:
            return self._not_evaluated("未获取到 HPA 数据或 HPA 数据为空，无法评估扩缩容自动化")

        evidence = []
        base_score = 0
        bonus_score = 0

        # --- 1. 分析 HPA 配置质量 ---
        total_hpas = len(hpas)

        dynamic_hpas = [h for h in hpas if h.min_replicas != h.max_replicas and h.max_replicas > h.min_replicas]
        static_hpas = [h for h in hpas if h.min_replicas == h.max_replicas]

        if not dynamic_hpas:
            if static_hpas:
                return self._not_scored(
                    "HPA 已配置但均未启用动态扩缩容 (min=max)",
                    [f"共 {len(static_hpas)} 个 HPA 处于固定副本模式"]
                )
            else:
                return self._not_scored("存在 HPA 对象但配置异常", ["无有效 min/max 配置"])

        dynamic_ratio = len(dynamic_hpas) / total_hpas

        # 基础分 (0-3 分)：根据动态比例给分
        if dynamic_ratio >= 0.8:
            base_score = 3
            evidence.append(f"HPA 覆盖良好：{len(dynamic_hpas)}/{total_hpas} 个已启用动态扩缩容")
        elif dynamic_ratio >= 0.5:
            base_score = 2
            evidence.append(
                f"HPA 部分覆盖：{len(dynamic_hpas)}/{total_hpas} 个已启用动态扩缩容 ({len(static_hpas)} 个固定)")
        else:
            base_score = 1
            evidence.append(f"HPA 覆盖较低：仅 {len(dynamic_hpas)}/{total_hpas} 个启用动态扩缩容")

        metric_types = set()
        for h in dynamic_hpas:
            for metric in h.metrics:
                if metric.type == "Resource":
                    if metric.resource_name == "cpu":
                        metric_types.add("CPU")
                    elif metric.resource_name == "memory":
                        metric_types.add("Memory")
                else:
                    metric_types.add("Custom")

        metric_evidence = [f"{t}: {sum(1 for h in dynamic_hpas if getattr(h, f'has_{t.lower()}_metric', False))}" for t
                           in metric_types]
        if metric_evidence:
            evidence.append(f"扩缩容指标类型：{', '.join(metric_evidence)}")

        if "Custom" in metric_types:
            bonus_score += 1
        elif len(metric_types) >= 2:
            bonus_score += 0.5

        # --- 3. VPA 检查与冲突检测 (0-2 分) ---
        vpa_score = 0
        has_conflict = False
        if store.available("k8s.vpa.list"):
            vpas: list[K8sVpaRecord] = store.get("k8s.vpa.list")
            if vpas:
                auto_vpas = [v for v in vpas if v.update_mode == "Auto"]
                rec_vpas = [v for v in vpas if v.update_mode == "Initial" or v.update_mode == "Recommendation"]

                evidence.append(f"VPA 配置：{len(vpas)} 个 (Auto: {len(auto_vpas)}, 推荐/初始: {len(rec_vpas)})")

                if auto_vpas and dynamic_hpas:
                    has_conflict = True
                    evidence.append(
                        "⚠ 警告：同时存在 HPA 和 Auto 模式 VPA，存在控制冲突风险 (建议 VPA 使用 Recommendation 模式)")
                    vpa_score = 0.5
                elif rec_vpas:
                    vpa_score = 2
                    evidence.append(" VPA 采用推荐的 Recommendation/Initial 模式，与 HPA 兼容性好")
                elif auto_vpas:
                    vpa_score = 1
                    evidence.append(" VPA 使用 Auto 模式 (注意：如同时使用 HPA 可能产生冲突)")
                else:
                    vpa_score = 0.5

        total_score = base_score + bonus_score + vpa_score
        if has_conflict:
            total_score = max(0, total_score - 1)

        if total_score >= 5.5:
            return self._scored(6, "具备完善的多维自动扩缩容能力 (HPA+VPA)", evidence)
        elif total_score >= 4.5:
            return self._scored(5, "具备良好的自动扩缩容策略", evidence)
        elif total_score >= 3.5:
            return self._scored(4, "具备较好的自动扩缩容能力", evidence)
        elif total_score >= 2.5:
            return self._scored(3, "已配置基础自动扩缩容，但覆盖或策略有待优化", evidence)
        elif total_score >= 1.5:
            return self._scored(2, "自动扩缩容能力初步建立", evidence)
        else:
            return self._scored(1, "自动扩缩容能力薄弱或配置不当", evidence)


class BackupAutomationAnalyzer(Analyzer):
    """
    备份自动化分析器
    """

    def key(self) -> str:
        return "backup_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "运维自动化"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "k8s.cronjob.list",
            "rds.backup_policy.list"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        score = 0
        has_data = False

        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)

        # 1. 检查 K8s CronJob 中的备份任务
        if store.available("k8s.cronjob.list"):
            has_data = True
            cronjobs: list[K8sCronJobRecord] = store.get("k8s.cronjob.list")

            backup_keywords = ["backup", "dump", "export", "snapshot", "备份", "导出"]
            backup_jobs = [j for j in cronjobs
                           if any(kw in j.name.lower() for kw in backup_keywords)]

            if backup_jobs:
                recent_success = [
                    j for j in backup_jobs
                    if j.last_successful_time and j.last_successful_time >= seven_days_ago
                ]

                if recent_success:
                    score += 2
                    evidence.append(f"✅ K8s 备份任务: {len(recent_success)} 个近期成功执行 (7 天内)")
                else:
                    evidence.append(f"⚠️ K8s 备份任务: 发现 {len(backup_jobs)} 个，但近期 (7 天) 无成功记录")
                    score += 0.5

        # 2. 检查 RDS 自动备份策略
        if store.available("rds.backup_policy.list"):
            has_data = True
            policies: list[RdsBackupPolicyRecord] = store.get("rds.backup_policy.list")

            enabled_policies = [p for p in policies if p.backup_retention_period > 0]

            if enabled_policies:
                score += 1.5
                evidence.append(f"✅ RDS 自动备份: {len(enabled_policies)} 个实例已启用")

                long_retention = [p for p in enabled_policies if p.backup_retention_period >= 7]
                if long_retention:
                    evidence.append(f"  其中 {len(long_retention)} 个保留策略 >= 7 天")

        if not has_data:
            return self._not_evaluated("未获取到备份相关数据 (K8s CronJob, RDS Policies)")

        if score == 0:
            return self._not_scored("未检测到有效的自动备份证据", evidence if evidence else [
                "未发现近期成功的备份任务或启用的 RDS 策略"])

        if score >= 4:
            return self._scored(5, "数据/状态定期自动备份覆盖完善", evidence)
        elif score >= 3:
            return self._scored(4, "自动备份配置较完善，覆盖多种数据类型", evidence)
        elif score >= 2:
            return self._scored(3, "已配置自动备份，覆盖部分核心数据", evidence)
        elif score >= 1:
            return self._scored(2, "自动备份初步配置，但覆盖有限或执行不稳定", evidence)
        else:
            return self._scored(1, "自动备份配置薄弱或长期未执行", evidence)


class SecurityAutomationAnalyzer(Analyzer):
    """
    安全自动化分析器
    
    评估标准：漏洞扫描、补丁更新、密钥轮换自动化
    
    数据来源：
    - ACR API：GetScanImageResult，检查镜像仓库是否启用了安全扫描，
      以及是否有高危漏洞被自动阻断的记录
    - 云效 Flow：流水线阶段定义，检查是否存在镜像安全扫描阶段
    - 云效 Flow：检查是否有自动创建 PR 来升级依赖库版本（如 Dependabot/Renovate 记录）
    """

    def key(self) -> str:
        return "security_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "运维自动化"

    def max_score(self) -> int:
        return 7

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "acr.image_scan.list",
            "codeup.pipeline.stages"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        score = 0
        has_data = False

        # 1. 检查 ACR 镜像安全扫描
        if store.available("acr.image_scan.list"):
            has_data = True
            scan_results: list[AcrImageScanResultRecord] = store.get("acr.image_scan.list")

            if scan_results:
                score += 1.5
                evidence.append(f"镜像安全扫描: 检测到 {len(scan_results)} 个扫描记录")

                high_vuln = [s for s in scan_results if s.high_severity_count > 0]

                if not high_vuln:
                    score += 2.0
                    evidence.append("  ✅ 未发现高危或严重漏洞镜像")
                else:
                    score += 0.5
                    evidence.append(f"  ⚠️ 存在漏洞风险: {len(high_vuln)} 个高危")
            else:
                evidence.append("  ℹ️ 已接入扫描服务，但暂无扫描数据")

        # 2. 检查流水线中的安全扫描阶段 (DevSecOps)
        if store.available("codeup.pipeline.stages"):
            has_data = True
            stages: list[CodeupPipelineStageRecord] = store.get("codeup.pipeline.stages")

            security_stages = [
                s for s in stages
                if s.has_security_scan
            ]

            if security_stages:
                score += 1.0
                evidence.append(f"流水线安全阶段: 发现 {len(security_stages)} 个")

                blocking_stages = [s for s in security_stages if s.on_failure == "block"]
                if blocking_stages:
                    score += 1.5
                    evidence.append(f"  ✅ 强制阻断: {len(blocking_stages)} 个阶段配置了失败阻断")
                else:
                    evidence.append("  ⚠️ 提示：安全阶段未配置失败阻断，风险可能流入生产")

        if not has_data:
            return self._not_evaluated("未获取到安全自动化相关数据 (ACR 扫描或 Codeup 流水线)")

        if score == 0:
            return self._not_scored("未检测到有效的安全自动化配置",
                                    evidence if evidence else ["未发现镜像扫描记录或流水线安全阶段"])

        if score >= 5.5:
            return self._scored(7, "安全自动化完善：漏洞扫描、镜像安全、流水线卡点全覆盖", evidence)
        elif score >= 4.5:
            return self._scored(6, "安全自动化较完善：镜像扫描无高危漏洞，流水线具备安全阻断", evidence)
        elif score >= 3.5:
            return self._scored(5, "安全自动化良好：具备镜像扫描和流水线安全阶段", evidence)
        elif score >= 2.5:
            return self._scored(4, "安全自动化较好：镜像扫描覆盖，部分流水线安全配置", evidence)
        elif score >= 1.5:
            return self._scored(3, "安全自动化初步：具备基础镜像扫描能力", evidence)
        elif score >= 0.5:
            return self._scored(2, "安全自动化有限：仅接入扫描服务或少量安全配置", evidence)
        else:
            return self._scored(1, "安全自动化能力非常有限，建议加强流水线卡点和定期扫描", evidence)


# 导出所有分析器
OPS_ANALYZERS = [
    IncidentManagementAnalyzer(),
    ScalingAutomationAnalyzer(),
    BackupAutomationAnalyzer(),
    SecurityAutomationAnalyzer(),
]
