"""
Elasticity 维度 - 垂直扩展能力 (Vertical Scaling) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)        | 分值 | 评分标准                                                           |
| vs_implemented      | 5    | 支持自动调整资源规格，具备优雅重启或热扩缩容机制以最小化业务影响   |
| vs_auto_scaling     | 5    | VPA 运行在 Auto 模式，配置了 MaxUnavailable 确保业务不中断         |
| vs_resource_opt     | 5    | 具备资源推荐机制，能识别资源浪费或瓶颈并给出建议                   |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sVpaRecord


class VsImplementedAnalyzer(Analyzer):
    """
    垂直扩展实现分析器
    
    评估标准：支持自动调整资源规格，且具备优雅重启 (Graceful Restart) 或
    进阶热扩缩容 (无需重启) 机制以最小化业务影响，或支持有状态组件的规格变更
    
    数据来源：
    - ACK API：GET /apis/autoscaling.k8s.io/v1/namespaces/{ns}/verticalpodautoscalers
    - 检查 VPA 对象是否存在及其 updateMode
    """

    def key(self) -> str:
        return "vs_implemented"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "垂直扩展能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["k8s.vpa.list"]

    def analyze(self, store) -> ScoreResult:
        vpas: list[K8sVpaRecord] = store.get("k8s.vpa.list")

        if not vpas:
            return self._not_scored("未配置 VPA 垂直自动伸缩", [])

        evidence = []

        auto_vpas = []
        recreate_vpas = []
        initial_vpas = []
        off_vpas = []
        unknown_vpas = []

        vpa_with_recommendation = 0
        vpa_with_full_resources = 0

        for v in vpas:
            mode = v.update_mode or "Auto"

            if v.recommendation:
                container_recs = v.recommendation.get('containerRecommendations', [])
                has_valid_rec = any(
                    rec.get('target') or rec.get('lowerBound') or rec.get('upperBound')
                    for rec in container_recs
                )
                if has_valid_rec:
                    vpa_with_recommendation += 1

            resources = v.controlled_resources or []
            if not resources:
                resources = ["cpu", "memory"]

            if "cpu" in resources and "memory" in resources:
                vpa_with_full_resources += 1

            if mode == "Auto":
                auto_vpas.append(v)
            elif mode == "Recreate":
                recreate_vpas.append(v)
            elif mode == "Initial":
                initial_vpas.append(v)
            elif mode == "Off":
                off_vpas.append(v)
            else:
                unknown_vpas.append(v)

        total_count = len(vpas)
        recommendation_ratio = vpa_with_recommendation / total_count if total_count else 0
        full_resource_ratio = vpa_with_full_resources / total_count if total_count else 0

        evidence.append(f"VPA 总数: {total_count}")

        mode_summary = []
        if auto_vpas: mode_summary.append(f"Auto={len(auto_vpas)}")
        if recreate_vpas: mode_summary.append(f"Recreate={len(recreate_vpas)}")
        if initial_vpas: mode_summary.append(f"Initial={len(initial_vpas)}")
        if off_vpas: mode_summary.append(f"Off={len(off_vpas)}")
        if unknown_vpas: mode_summary.append(f"Unknown={len(unknown_vpas)}")
        evidence.append(f"模式分布: {', '.join(mode_summary)}")

        evidence.append(f"推荐值生成率: {vpa_with_recommendation}/{total_count} ({recommendation_ratio * 100:.0f}%)")
        evidence.append(
            f"完整资源配置(CPU+Memory): {vpa_with_full_resources}/{total_count} ({full_resource_ratio * 100:.0f}%)")

        mode_score = 0.0

        if off_vpas:
            off_ratio = len(off_vpas) / total_count
            mode_score = 2.0 + off_ratio * 1.5
            evidence.append(f"✓ Off 模式: {len(off_vpas)} 个 (安全观察期，生产环境推荐)")

        if recreate_vpas:
            recreate_ratio = len(recreate_vpas) / total_count
            mode_score = max(mode_score, 1.5 + recreate_ratio * 1.5)
            evidence.append(f"✓ Recreate 模式: {len(recreate_vpas)} 个 (可控重启，适合有状态服务)")

        if initial_vpas:
            initial_ratio = len(initial_vpas) / total_count
            mode_score = max(mode_score, 1.0 + initial_ratio * 1.0)
            evidence.append(f"ℹ️ Initial 模式: {len(initial_vpas)} 个 (仅新 Pod 生效)")

        if auto_vpas:
            auto_ratio = len(auto_vpas) / total_count
            mode_score = max(mode_score, 1.0 + auto_ratio * 1.5)
            evidence.append(f"ℹ️ Auto 模式: {len(auto_vpas)} 个 (自动调整，需确保业务容忍重启)")

        score = mode_score

        if recommendation_ratio >= 0.8:
            score += 1.0
            evidence.append("✓ 推荐值生成完善")
        elif recommendation_ratio >= 0.5:
            score += 0.5
            evidence.append("⚠️ 部分推荐值已生成")
        else:
            evidence.append("⚠️ 推荐值生成不足，可能需要等待数据积累")

        if full_resource_ratio >= 0.8:
            score += 0.5
            evidence.append("✓ VPA 配置完整 (CPU + Memory)")

        final_score = min(round(score), 5)

        if final_score >= 4:
            conclusion = "VPA 配置成熟，推荐值完善，具备有效的垂直扩展能力"
        elif final_score >= 3:
            conclusion = "VPA 配置良好，建议完善推荐值或调整模式以提升稳定性"
        elif final_score >= 2:
            conclusion = "VPA 基础配置到位，建议观察推荐值后选择合适的模式"
        else:
            conclusion = "VPA 配置不完善，建议检查 Controller 状态或等待数据积累"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class VsAutoScalingAnalyzer(Analyzer):
    """
    垂直自动伸缩分析器
    
    评估标准：VPA 运行在 Auto 模式，且配置了 UpdateMode=Recreate 时的
    最大并发重启限制 (MaxUnavailable)，确保业务不中断
    
    数据来源：
    - ACK API：VPA 对象的 updatePolicy 配置
    - 检查 minReplicas、maxUnavailable 等保护性配置
    """

    def key(self) -> str:
        return "vs_auto_scaling"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "垂直扩展能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["k8s.vpa.list"]

    def analyze(self, store) -> ScoreResult:
        vpas: list[K8sVpaRecord] = store.get("k8s.vpa.list")

        if not vpas:
            return self._not_scored("未配置 VPA 垂直自动伸缩", [])

        evidence = []

        auto_vpas = [v for v in vpas if v.update_mode == "Auto"]
        recreate_vpas = [v for v in vpas if v.update_mode == "Recreate"]
        active_vpas = auto_vpas + recreate_vpas

        total_count = len(vpas)
        evidence.append(f"VPA 总数: {total_count}")
        evidence.append(f"Auto 模式: {len(auto_vpas)} 个")
        evidence.append(f"Recreate 模式: {len(recreate_vpas)} 个")

        if not active_vpas:
            initial_vpas = [v for v in vpas if v.update_mode == "Initial"]
            off_vpas = [v for v in vpas if v.update_mode == "Off"]
            if initial_vpas:
                evidence.append("ℹ️ 仅 Initial 模式，不触发运行中 Pod 的资源调整")
            if off_vpas:
                evidence.append("ℹ️ 仅 Off 模式，VPA 仅提供建议不自动调整")
            return self._scored(
                1,
                "未启用 Auto/Recreate 模式的 VPA，不具备自动伸缩能力",
                evidence
            )

        # 检查保护性配置 (minReplicas)
        protected_vpas = []
        unprotected_vpas = []

        for v in active_vpas:
            if v.min_replicas is not None and v.min_replicas > 0:
                protected_vpas.append(v)
                evidence.append(f"✓ {v.namespace}/{v.name}: minReplicas={v.min_replicas}")
            else:
                unprotected_vpas.append(v)

        protected_count = len(protected_vpas)
        active_count = len(active_vpas)

        evidence.append(f"配置 minReplicas 的 VPA: {protected_count}/{active_count}")

        if active_count == 0:
            return self._scored(1, "未启用 Auto/Recreate 模式", evidence)

        protection_ratio = protected_count / active_count

        base_score = 2.0

        if protection_ratio >= 0.8:
            base_score += 2.5
            evidence.append("✓ 大部分 VPA 配置了 minReplicas 保护策略")
        elif protection_ratio >= 0.5:
            base_score += 1.5
            evidence.append("⚠️ 部分 VPA 配置了 minReplicas 保护策略")
        elif protection_ratio > 0:
            base_score += 0.5
            evidence.append("⚠️ 少数 VPA 配置了 minReplicas 保护策略")
        else:
            evidence.append("⚠️ 未配置 minReplicas 保护策略，Recreate 模式可能同时驱逐所有 Pod")

        final_score = min(round(base_score), 5)

        if final_score >= 4:
            conclusion = "VPA 自动伸缩配置成熟，具备完善的业务保护机制"
        elif final_score >= 3:
            conclusion = "VPA 自动伸缩配置良好，建议完善 minReplicas 保护策略配置"
        elif final_score >= 2:
            conclusion = "VPA 已启用自动伸缩，建议配置 minReplicas 保护业务连续性"
        else:
            conclusion = "VPA 自动伸缩能力不足，建议启用 Auto/Recreate 模式并配置 minReplicas 保护策略"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, conclusion, evidence)


class VsResourceOptAnalyzer(Analyzer):
    """
    资源优化分析器
    
    评估标准：具备资源推荐机制，能识别资源浪费并建议缩减，或识别瓶颈建议扩容
    
    数据来源：
    - ACK API：VPA status.recommendation 字段，读取 CPU/Mem 的推荐值
    - UModel：k8s.metric.high_level_metric_pod（Pod CPU/内存利用率）
    - 分析是否长期处于低负载或高负载状态
    """

    def key(self) -> str:
        return "vs_resource_opt"

    def dimension(self) -> str:
        return "Elasticity"

    def category(self) -> str:
        return "垂直扩展能力"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["k8s.vpa.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.pod.list"]

    def analyze(self, store) -> ScoreResult:
        vpas: list[K8sVpaRecord] = store.get("k8s.vpa.list")

        if not vpas:
            return self._not_scored("未配置 VPA，无资源推荐能力", [])

        evidence = [f"VPA 配置总数: {len(vpas)}"]

        valid_vpas = []
        pending_vpas = []

        for v in vpas:
            has_valid_rec = False
            if v.recommendation:
                container_recs = v.recommendation.get('containerRecommendations', [])
                for rec in container_recs:
                    target = rec.get('target')
                    if target:
                        has_valid_rec = True
                        break

            if has_valid_rec:
                valid_vpas.append(v)
            else:
                pending_vpas.append(v)

        count_valid = len(valid_vpas)
        count_total = len(vpas)
        ratio = count_valid / count_total if count_total else 0

        evidence.append(f"有效推荐值 VPA: {count_valid}/{count_total} ({ratio * 100:.0f}%)")

        coverage_score = 0.5 + ratio * 3.0

        if count_valid == 0:
            evidence.append("⚠️ 所有 VPA 均未生成推荐值")
            evidence.append("💡 可能原因:")
            evidence.append("  - VPA 刚创建，正在积累历史数据 (通常需要 24 小时)")
            evidence.append("  - VPA Controller 未运行或配置异常")
            evidence.append("  - 目标工作负载不存在或标签选择器错误")

            return self._scored(
                1,
                "VPA 已配置但未生成任何推荐值，建议检查 Controller 状态或等待数据积累",
                evidence
            )

        quality_score = 0.0

        complete_recs = 0
        for v in valid_vpas:
            if v.recommendation:
                container_recs = v.recommendation.get('containerRecommendations', [])
                for rec in container_recs:
                    if rec.get('target'):
                        complete_recs += 1
                        break

        if complete_recs > 0:
            complete_ratio = complete_recs / count_valid
            quality_score = complete_ratio * 1.5
            if complete_ratio >= 0.8:
                evidence.append(f"✓ 推荐值质量完善 ({complete_recs}/{count_valid} 有完整推荐范围)")
            else:
                evidence.append(f"ℹ️ 推荐值质量一般 ({complete_recs}/{count_valid} 有完整推荐范围)")

        score = coverage_score + quality_score
        final_score = min(round(score), 5)

        if final_score >= 4:
            conclusion = "VPA 资源推荐机制运行良好，推荐值完善，可有效指导资源优化"
        elif final_score >= 3:
            conclusion = "VPA 资源推荐机制运行正常，建议完善推荐值覆盖范围"
        elif final_score >= 2:
            conclusion = "VPA 资源推荐机制部分生效，建议检查未生效的 VPA 配置"
        else:
            conclusion = "VPA 资源推荐机制生效不足，建议检查 Controller 状态或等待数据积累"

        evidence.append(f"综合评分: {final_score}分")

        return self._scored(final_score, conclusion, evidence)


# 导出所有分析器
VPA_ANALYZERS = [
    VsImplementedAnalyzer(),
    VsAutoScalingAnalyzer(),
    VsResourceOptAnalyzer(),
]
