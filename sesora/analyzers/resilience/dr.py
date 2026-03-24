"""
Resilience 维度 - 灾难恢复 (Disaster Recovery) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                       |
| dr_backup_strategy        | 6    | 备份策略：对代码、配置、数据库、对象存储实施自动化、定期备份   |
| dr_recovery_plan          | 5    | 恢复计划 (DRP)：有文档化、步骤清晰的灾难恢复操作手册           |
| dr_rto_rpo_defined        | 5    | RTO/RPO 定义：为关键业务系统定义了明确的 RTO 和 RPO            |
| dr_recovery_testing       | 9    | 恢复演练：过去 6 个月内进行过真实的灾难恢复演练                |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sCronJobRecord
from ...schema.rds_oss import RdsBackupPolicyRecord, OssBucketLifecycleRecord
from ...schema.manual import ManualDrPlanRecord, ManualRtoRpoRecord, ManualDrTestingRecord
from datetime import datetime, timezone


class DrBackupStrategy(Analyzer):
    """
    备份策略分析器
    
    评估标准：是否对代码、配置、数据库、对象存储实施了自动化、定期的备份，并验证了备份完整性
    
    数据来源：
    - UModel：k8s.cronjob entity_set，schedule 字段，判断是否有定期备份任务
    - RDS API：DescribeBackupPolicy，检查自动备份策略是否开启且备份周期合理
    - OSS API：GetBucketLifecycle，检查是否有备份数据的生命周期管理策略
    - 3-2-1 原则检查: 确认备份数据是否至少有 3 份拷贝
    """

    def key(self) -> str:
        return "dr_backup_strategy"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "灾难恢复"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["rds.backup_policy.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.cronjob.list", "oss.bucket.lifecycle"]

    def analyze(self, store) -> ScoreResult:
        rds_policies: list[RdsBackupPolicyRecord] = store.get("rds.backup_policy.list")

        score = 0.0
        evidence = []
        warnings = []

        # --- 1. RDS 备份策略检查（最高 3 分）---
        if rds_policies:
            total_rds = len(rds_policies)
            valid_policies = [p for p in rds_policies if p.backup_retention_period >= 7]
            retention_coverage = len(valid_policies) / total_rds

            evidence.append(f"RDS 实例总数: {total_rds}")

            if valid_policies:
                evidence.append(f"RDS 备份保留>=7天: {len(valid_policies)}/{total_rds} ({retention_coverage:.0%})")

                if retention_coverage < 1.0:
                    warnings.append(f"{total_rds - len(valid_policies)} 个 RDS 实例备份保留期不足 7 天")

                retention_score = min(retention_coverage, 1.0) * 2.0
                score += retention_score

                cross_region = [p for p in valid_policies if p.cross_backup_enabled]
                cross_ratio = len(cross_region) / total_rds

                if cross_ratio >= 0.5:
                    score += 1.0
                    evidence.append(f"✓ RDS 跨地域备份覆盖充足: {len(cross_region)}/{total_rds} ({cross_ratio:.0%})")
                elif cross_ratio >= 0.2:
                    score += 0.5
                    evidence.append(f"ℹ️ RDS 跨地域备份部分覆盖: {len(cross_region)}/{total_rds} ({cross_ratio:.0%})")
                    warnings.append(f"跨地域备份覆盖仅 {cross_ratio:.0%}，建议扩展以满足3-2-1原则")
                elif cross_region:
                    evidence.append(f"⚠️ RDS 跨地域备份覆盖低: {len(cross_region)}/{total_rds}")
                    warnings.append("跨地域备份覆盖不足，存在单地域风险")
            else:
                warnings.append("所有 RDS 实例备份保留期均小于 7 天")
                evidence.append("⚠️ RDS 备份策略：无实例满足保留期>=7天")
        else:
            evidence.append("ℹ️ 未发现 RDS 备份策略数据")

        # --- 2. K8s CronJob 备份检查（最高 2 分）---
        cronjobs: list[K8sCronJobRecord] = store.get("k8s.cronjob.list")
        if cronjobs:
            backup_keywords = ["backup", "dump", "export", "snapshot"]
            exclude_keywords = ["checker", "verify", "test", "clean"]

            backup_jobs = []
            for j in cronjobs:
                name = j.name.lower()
                is_backup = any(kw in name for kw in backup_keywords)
                is_exclude = any(kw in name for kw in exclude_keywords)

                if is_backup and not is_exclude and not j.suspend:
                    backup_jobs.append(j)

            if backup_jobs:
                if len(backup_jobs) >= 3:
                    score += 2.0
                    evidence.append(f"✓ K8s 有效备份任务充足: {len(backup_jobs)} 个")
                else:
                    score += 1.0
                    evidence.append(f"ℹ️ K8s 有效备份任务: {len(backup_jobs)} 个 (建议增加覆盖)")
            else:
                all_backup_jobs = [j for j in cronjobs
                                   if any(kw in j.name.lower() for kw in backup_keywords)
                                   and not any(kw in j.name.lower() for kw in exclude_keywords)]
                if all_backup_jobs:
                    suspended_count = sum(1 for j in all_backup_jobs if j.suspend)
                    warnings.append(f"{suspended_count} 个备份 CronJob 处于挂起状态，未生效")
                    evidence.append(f"⚠️ K8s 备份任务: {len(all_backup_jobs)} 个 (全部挂起)")
        else:
            evidence.append("ℹ️ 未发现 K8s CronJob 数据")

        # --- 3. OSS 生命周期检查（最高 1 分）---
        lifecycles: list[OssBucketLifecycleRecord] = store.get("oss.bucket.lifecycle")
        if lifecycles:
            archive_keywords = ["archive", "ia", "cold", "glacier", "归档", "冷存储"]
            valid_lifecycle_count = 0

            for lc in lifecycles:
                rules = lc.transitions
                has_archive = any(
                    any(kw in str(r.get("storage_class", "")).lower() for kw in archive_keywords)
                    or any(kw in str(r).lower() for kw in archive_keywords)
                    for r in rules
                )
                if has_archive:
                    valid_lifecycle_count += 1

            lifecycle_coverage = valid_lifecycle_count / len(lifecycles)

            if valid_lifecycle_count > 0:
                if lifecycle_coverage >= 0.5:
                    score += 1.0
                    evidence.append(f"✓ OSS 归档策略覆盖充足: {valid_lifecycle_count}/{len(lifecycles)}")
                else:
                    score += 0.5
                    evidence.append(f"ℹ️ OSS 归档策略部分覆盖: {valid_lifecycle_count}/{len(lifecycles)}")

                if valid_lifecycle_count < len(lifecycles):
                    warnings.append(
                        f"{len(lifecycles) - valid_lifecycle_count} 个 OSS 桶缺乏归档策略，仅有删除规则")
            else:
                evidence.append(
                    f"⚠️ OSS 生命周期: {len(lifecycles)} 个桶均无归档策略 (可能存在误删风险)")
        else:
            evidence.append("ℹ️ 未发现 OSS 生命周期数据")

        final_score = max(min(round(score), 6), 0)

        if final_score >= 6:
            status_msg = "备份策略完善：覆盖多源且符合 3-2-1 原则"
        elif final_score >= 4:
            status_msg = "备份策略良好：覆盖主要数据源，建议补充异地备份"
        elif final_score >= 2:
            status_msg = "备份策略基础：仅覆盖部分数据源或缺乏异地容灾"
        elif final_score >= 1:
            status_msg = "备份策略薄弱：存在数据丢失风险"
        else:
            return self._not_scored("未发现有效的备份策略配置", evidence)

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(final_score, status_msg, evidence)


class DrRecoveryPlan(Analyzer):
    """
    恢复计划分析器
    
    评估标准：是否有文档化的、步骤清晰的灾难恢复操作手册 (Runbook)，并定期更新
    
    数据来源：人工问卷
    """

    def key(self) -> str:
        return "dr_recovery_plan"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "灾难恢复"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.dr_plan"]

    def analyze(self, store) -> ScoreResult:
        plans: list[ManualDrPlanRecord] = store.get("manual.dr_plan")

        if not plans:
            return self._not_evaluated("灾难恢复计划需人工填写，暂无数据")

        plan = plans[-1]

        if not plan.has_dr_plan:
            return self._not_scored("未制定灾难恢复计划", [])

        score = 0.0
        evidence = []
        warnings = []

        if plan.plan_document_url:
            evidence.append(f"计划文档: {plan.plan_document_url}")
        else:
            evidence.append("计划文档: 已存在（未提供链接）")

        # --- 1. 时效性评估（最高 2 分）---
        now = datetime.now(timezone.utc)

        if plan.last_updated:
            update_time = plan.last_updated
            if update_time.tzinfo is None:
                update_time = update_time.replace(tzinfo=timezone.utc)

            days_since_update = (now - update_time).days

            if days_since_update <= 90:
                score += 2.0
                evidence.append(f"✓ 时效性良好: 距更新 {days_since_update} 天（≤3个月）")
            elif days_since_update <= 180:
                score += 1.5
                evidence.append(f"✓ 时效性合格: 距更新 {days_since_update} 天（≤6个月）")
            elif days_since_update <= 365:
                score += 0.5
                warnings.append(f"DRP 已 {days_since_update} 天未更新，可能存在过时风险")
                evidence.append(f"⚠️ 时效性不足: 距更新 {days_since_update} 天（>6个月）")
            else:
                warnings.append(f"DRP 已超过 1 年未更新，存在严重过时风险")
                evidence.append(f"⚠️ 时效性过期: 距更新 {days_since_update} 天（>12个月）")
        else:
            warnings.append("DRP 缺少更新时间记录，无法判断时效性")
            evidence.append("⚠️ 时效性未知: 无更新时间记录")

        # --- 2. 完整度评估（最高 3 分）---
        completeness_items = [
            ("明确恢复步骤", plan.steps_defined, 1.5),
            ("责任角色分配", plan.roles_assigned, 0.75),
            ("通信计划", plan.communication_plan, 0.75),
        ]

        completed_items = []
        for item_name, is_completed, item_score in completeness_items:
            if is_completed:
                score += item_score
                completed_items.append(item_name)
                evidence.append(f"✓ {item_name}")

        missing_items = [name for name, done, _ in completeness_items if not done]
        if missing_items:
            warnings.append(f"DRP 缺少: {', '.join(missing_items)}")

        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "DRP 成熟：时效性好、内容完整"
        elif final_score >= 3.5:
            status_msg = "DRP 良好：时效性合格、内容基本完整"
        elif final_score >= 2.5:
            status_msg = "DRP 基础：存在时效性或完整性不足"
        elif final_score >= 1.5:
            status_msg = "DRP 薄弱：时效性和完整性均存在问题"
        else:
            status_msg = "DRP 不成熟：时效性差或内容严重缺失"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class DrRtoRpoDefined(Analyzer):
    """
    RTO/RPO 定义分析器
    
    评估标准：是否为每个关键业务系统定义了明确的恢复时间目标 (RTO) 和恢复点目标 (RPO)，且架构设计能满足该指标
    
    数据来源：人工问卷
    """

    def key(self) -> str:
        return "dr_rto_rpo_defined"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "灾难恢复"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["manual.rto_rpo"]

    def analyze(self, store) -> ScoreResult:
        configs: list[ManualRtoRpoRecord] = store.get("manual.rto_rpo")

        if not configs:
            return self._not_evaluated("RTO/RPO 定义需人工填写，暂无数据")

        total_services = len(configs)
        defined_services = [c for c in configs if c.rto_defined and c.rpo_defined]
        supported_services = [c for c in defined_services if c.architecture_supports]

        if not defined_services:
            return self._not_scored("未为任何服务定义 RTO/RPO 目标", [f"共 {total_services} 个服务"])

        score = 0.0
        evidence = []
        warnings = []

        coverage = len(defined_services) / total_services

        # --- 1. 覆盖率评分（最高 2.5 分）---
        if coverage >= 0.9:
            coverage_score = 2.5
            evidence.append(f"✓ 覆盖率优秀: {len(defined_services)}/{total_services} ({coverage:.0%})")
        elif coverage >= 0.7:
            coverage_score = 2.0
            evidence.append(f"✓ 覆盖率良好: {len(defined_services)}/{total_services} ({coverage:.0%})")
        elif coverage >= 0.5:
            coverage_score = 1.5
            evidence.append(f"ℹ️ 覆盖率中等: {len(defined_services)}/{total_services} ({coverage:.0%})")
        elif coverage >= 0.3:
            coverage_score = 1.0
            warnings.append(f"覆盖率偏低: 仅 {len(defined_services)}/{total_services} ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率偏低: {len(defined_services)}/{total_services} ({coverage:.0%})")
        else:
            coverage_score = 0.5
            warnings.append(f"覆盖率严重不足: 仅 {len(defined_services)}/{total_services} ({coverage:.0%})")
            evidence.append(f"⚠️ 覆盖率严重不足: {len(defined_services)}/{total_services} ({coverage:.0%})")

        score += coverage_score

        # --- 2. 架构支持率评分（最高 2.5 分）---
        if defined_services:
            support_rate = len(supported_services) / len(defined_services)

            if support_rate >= 0.9:
                support_score = 2.5
                evidence.append(
                    f"✓ 架构支持率优秀: {len(supported_services)}/{len(defined_services)} ({support_rate:.0%})")
            elif support_rate >= 0.7:
                support_score = 2.0
                evidence.append(
                    f"✓ 架构支持率良好: {len(supported_services)}/{len(defined_services)} ({support_rate:.0%})")
            elif support_rate >= 0.5:
                support_score = 1.0
                warnings.append(f"部分 RTO/RPO 目标架构无法支撑")
                evidence.append(
                    f"ℹ️ 架构支持率中等: {len(supported_services)}/{len(defined_services)} ({support_rate:.0%})")
            elif support_rate > 0:
                support_score = 0.5
                warnings.append(f"多数 RTO/RPO 目标架构无法支撑，存在'纸上谈兵'风险")
                evidence.append(
                    f"⚠️ 架构支持率低: {len(supported_services)}/{len(defined_services)} ({support_rate:.0%})")
            else:
                support_score = 0
                warnings.append("所有 RTO/RPO 目标均无架构支撑，属于空头指标")
                evidence.append(f"⚠️ 架构支持率为零: 定义的 RTO/RPO 无法实现")
        else:
            support_score = 0

        score += support_score

        for c in defined_services[:5]:
            arch_status = "✓" if c.architecture_supports else "⚠️"
            evidence.append(
                f"{arch_status} {c.service_name}: RTO={c.rto_minutes}min, RPO={c.rpo_minutes}min"
            )

        if len(defined_services) > 5:
            evidence.append(f"... 共 {len(defined_services)} 个服务已定义 RTO/RPO")

        # --- 4. 状态判定 ---
        final_score = max(min(round(score, 1), 5), 0)

        if final_score >= 4.5:
            status_msg = "RTO/RPO 体系成熟：覆盖全面、架构支撑可靠"
        elif final_score >= 3.5:
            status_msg = "RTO/RPO 体系良好：覆盖较全、架构基本支撑"
        elif final_score >= 2.5:
            status_msg = "RTO/RPO 体系基础：存在覆盖或架构支撑不足"
        elif final_score >= 1.5:
            status_msg = "RTO/RPO 体系薄弱：覆盖率和架构支撑均有欠缺"
        else:
            status_msg = "RTO/RPO 体系不成熟：定义缺失或无法实现"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


class DrRecoveryTesting(Analyzer):
    """
    恢复演练分析器

    评估标准：过去 6 个月内是否进行过真实的灾难恢复演练（不仅仅是桌面推演），并产出了改进报告

    数据来源：人工问卷
    """

    def key(self) -> str:
        return "dr_recovery_testing"

    def dimension(self) -> str:
        return "Resilience"

    def category(self) -> str:
        return "灾难恢复"

    def max_score(self) -> int:
        return 9

    def required_data(self) -> list[str]:
        return ["manual.dr_testing"]

    def analyze(self, store) -> ScoreResult:
        records: list[ManualDrTestingRecord] = store.get("manual.dr_testing")

        if not records:
            return self._not_evaluated("灾难恢复演练记录需人工填写，暂无数据")

        record = records[-1]

        if not record.has_testing:
            return self._not_scored("过去 6 个月未进行灾难恢复演练", [])

        score = 0.0
        evidence = []
        warnings = []

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        # --- 1. 时效性评估（最高 2 分）---
        days_since_test = None
        if record.last_test_date:
            test_time = record.last_test_date
            if test_time.tzinfo is None:
                test_time = test_time.replace(tzinfo=timezone.utc)
            days_since_test = (now - test_time).days
            evidence.append(
                f"最近演练时间: {record.last_test_date.strftime('%Y-%m-%d') if hasattr(record.last_test_date, 'strftime') else record.last_test_date}")

        if days_since_test is not None:
            if days_since_test <= 90:
                score += 2.0
                evidence.append(f"✓ 时效性优秀: 距演练 {days_since_test} 天（≤3个月）")
            elif days_since_test <= 180:
                score += 1.5
                evidence.append(f"✓ 时效性合格: 距演练 {days_since_test} 天（≤6个月）")
            elif days_since_test <= 365:
                score += 0.5
                warnings.append(f"演练已超过 6 个月，时效性不足")
                evidence.append(f"⚠️ 时效性不足: 距演练 {days_since_test} 天（>6个月）")
            else:
                warnings.append("演练已超过 1 年，不满足'6个月内'评估标准")
                evidence.append(f"⚠️ 时效性过期: 距演练 {days_since_test} 天（>12个月）")
        else:
            warnings.append("未提供演练时间，无法判断时效性")
            evidence.append("⚠️ 时效性未知: 无演练时间记录")

        # --- 2. 演练类型评估（最高 4 分）---
        if record.test_type == "full":
            score += 4.0
            evidence.append("✓ 演练类型: 全量演练（真实切换验证）")
        elif record.test_type == "partial":
            score += 2.5
            evidence.append("✓ 演练类型: 部分演练（关键系统验证）")
        elif record.test_type == "tabletop":
            score += 0.5
            warnings.append("桌面推演无实际切换验证，建议升级为实战演练")
            evidence.append("⚠️ 演练类型: 桌面推演（仅讨论，无实战验证）")
        else:
            score += 0.5
            warnings.append("演练类型不明确，默认视为桌面推演级别")
            evidence.append("⚠️ 演练类型: 未知（视为桌面推演级别）")

        # --- 3. 演练覆盖范围（最高 1.5 分）---
        if record.test_scope:
            scope_lower = record.test_scope.lower()
            if any(kw in scope_lower for kw in ["全链路", "全部", "full", "complete", "端到端", "所有"]):
                score += 1.5
                evidence.append(f"✓ 演练范围: {record.test_scope}")
            elif any(kw in scope_lower for kw in ["核心", "关键", "core", "critical", "主要"]):
                score += 1.0
                evidence.append(f"✓ 演练范围: {record.test_scope}")
            elif any(kw in scope_lower for kw in ["部分", "partial", "单个", "single"]):
                score += 0.5
                evidence.append(f"ℹ️ 演练范围: {record.test_scope}")
                warnings.append("演练覆盖范围有限，建议扩展至更多系统")
            else:
                score += 0.5
                evidence.append(f"ℹ️ 演练范围: {record.test_scope}")
        else:
            evidence.append("ℹ️ 未提供演练覆盖范围信息")

        # --- 4. 改进闭环评估（最高 1.5 分）---
        if record.improvement_report:
            score += 0.75
            evidence.append("✓ 已产出改进报告")

        if record.issues_found > 0:
            resolved_rate = record.issues_resolved / record.issues_found
            evidence.append(f"发现问题: {record.issues_found} 个, 已解决: {record.issues_resolved} 个")
            if resolved_rate >= 0.8:
                score += 0.75
                evidence.append("✓ 问题解决率高，形成闭环")
            elif resolved_rate >= 0.5:
                score += 0.5
                warnings.append(f"问题解决率 {resolved_rate:.0%}，部分问题待跟进")
            else:
                warnings.append(f"问题解决率仅 {resolved_rate:.0%}，改进跟进不足")
        elif record.test_type in ["full", "partial"]:
            score += 0.5
            evidence.append("✓ 演练未发现问题（系统健壮或演练设计良好）")

        final_score = max(min(round(score, 1), 9), 0)

        if final_score >= 7.5:
            status_msg = "DR 演练成熟：时效性好、全量验证、形成闭环"
        elif final_score >= 5.5:
            status_msg = "DR 演练良好：时效性合格、实战验证、有改进"
        elif final_score >= 3.5:
            status_msg = "DR 演练基础：存在时效性或实战性不足"
        elif final_score >= 2:
            status_msg = "DR 演练薄弱：主要为桌面推演或时效性差"
        else:
            status_msg = "DR 演练不成熟：不满足基本评估标准"

        if warnings:
            evidence.extend([f"⚠️ {w}" for w in warnings])

        return self._scored(round(final_score), status_msg, evidence)


# 导出所有分析器
DR_ANALYZERS = [
    DrBackupStrategy(),
    DrRecoveryPlan(),
    DrRtoRpoDefined(),
    DrRecoveryTesting(),
]
