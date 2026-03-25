"""
Observability 维度 - 可视化与洞察 (Visualization) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)        | 分值 | 评分标准                                                       |
| dash_diversity      | 0-5  | 仪表盘类型丰富度：扫描 tags，覆盖 system/app/business/ux       |
| dash_realtime       | 4    | 实时监控：仪表盘数据延迟 ≤15s，支持实时故障发现                |
| dash_historical     | 4    | 历史回溯：支持长周期 (月/季) 的历史数据趋势分析                |
| dash_role_based     | 4    | 角色视图：按 folder 或 tag 隔离视图，或有丰富 templating 变量  |
| dash_actionable     | 3    | 可行动性：仪表盘直接关联下钻分析或告警触发入口                 |
"""
from sesora.core.analyzer import Analyzer, ScoreResult
from sesora.schema import SlsLogstoreRecord
from sesora.schema.grafana import GrafanaDashboardRecord, GrafanaDashboardAnalysisRecord, GrafanaFolderRecord


class DashDiversityAnalyzer(Analyzer):
    """
    仪表盘类型丰富度分析器
    
    评估标准：扫描 Grafana Dashboard JSON 中的 tags 字段
    - 若存在 system, app, business, ux 等标签对应的仪表盘，则得分
    
    数据来源：
    - ARMS Grafana API：仪表盘列表，分析仪表盘的标签/分类
    """

    def key(self) -> str:
        return "dash_diversity"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "可视化与洞察"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["grafana.dashboard.list"]

    def optional_data(self) -> list[str]:
        return ["grafana.dashboard.analysis"]

    def analyze(self, store) -> ScoreResult:
        dashboards: list[GrafanaDashboardRecord] = store.get("grafana.dashboard.list")

        if not dashboards:
            return self._not_scored("未配置 Grafana 仪表盘", [])

        evidence = [f"仪表盘总数: {len(dashboards)}"]

        type_keywords = {
            "business": ["business", "order", "payment", "transaction", "conversion", "revenue", "销售", "订单", "gmv",
                         "营收"],
            "ux": ["ux", "user", "frontend", "web", "mobile", "page", "latency", "apdex", "体验", "用户"],
            "app": ["app", "application", "service", "api", "microservice", "backend", "应用", "服务"],
            "system": ["system", "node", "host", "infrastructure", "k8s", "kubernetes", "cluster", "cpu", "memory",
                       "系统", "节点"]
        }

        type_dashboards: dict[str, list[GrafanaDashboardRecord]] = {t: [] for t in type_keywords}
        assigned_dashboards: set[str] = set()

        for dash in dashboards:
            dash_id = dash.uid or dash.title or str(id(dash))
            if dash_id in assigned_dashboards:
                continue

            dash_tags = [t.lower() for t in (dash.tags or [])]
            dash_name = dash.title.lower() if dash.title else ""
            dash_text = " ".join(dash_tags) + " " + dash_name

            for dtype, keywords in type_keywords.items():
                if any(kw in dash_text for kw in keywords):
                    type_dashboards[dtype].append(dash)
                    assigned_dashboards.add(dash_id)
                    break

        covered_types = []
        total_classified = 0
        for dtype, dashes in type_dashboards.items():
            if dashes:
                covered_types.append(dtype)
                total_classified += len(dashes)
                evidence.append(f"✓ {dtype}: {len(dashes)} 个")

        analysis_list: list[GrafanaDashboardAnalysisRecord] = store.get("grafana.dashboard.analysis")
        if analysis_list:
            analysis_types: set[str] = set()
            for a in analysis_list:
                if a.system_dashboards > 0:
                    analysis_types.add("system")
                if a.app_dashboards > 0:
                    analysis_types.add("app")
                if a.business_dashboards > 0:
                    analysis_types.add("business")
                if a.ux_dashboards > 0:
                    analysis_types.add("ux")

            covered_types = list(set(covered_types) | analysis_types)
            evidence.append(f"分析数据补充类型: {analysis_types}")

        type_count = len(covered_types)
        unclassified_count = len(dashboards) - total_classified
        if unclassified_count > 0:
            evidence.append(f"未分类仪表盘: {unclassified_count} 个")

        score = 0.0

        type_coverage_score = (type_count / 4) * 3.0
        score += type_coverage_score

        rich_types = sum(1 for dashes in type_dashboards.values() if len(dashes) >= 2)
        richness_score = (rich_types / 4) * 1.5
        score += richness_score

        if len(dashboards) >= 20:
            score += 0.5
            evidence.append("✓ 仪表盘规模较大，可视化工作投入充足")
        elif len(dashboards) >= 10:
            score += 0.25
            evidence.append("ℹ️ 仪表盘规模适中")

        final_score = max(min(round(score), 5), 0)

        if final_score >= 4:
            conclusion = "仪表盘类型丰富：覆盖系统/应用/业务/UX，且各类数量充足"
        elif final_score >= 3:
            conclusion = "仪表盘类型较丰富，建议补全缺失类型或增加各类数量"
        elif final_score >= 2:
            conclusion = "仪表盘覆盖部分类型，可视化工作初具规模"
        elif final_score >= 1:
            conclusion = "仪表盘类型单一，建议扩展业务/UX等高价值类型"
        else:
            conclusion = "仪表盘未能有效分类，建议规范化 tags 或命名"

        return self._scored(final_score, conclusion, evidence)


class DashRealtimeAnalyzer(Analyzer):
    """
    实时监控分析器
    
    评估标准：仪表盘数据延迟是否在秒级 (≤15s)，支持实时故障发现
    
    数据来源：
    - UModel：metric_set 的 interval_us 字段标注了采集间隔
    - 15000000 (15秒) 表示支持实时性
    """

    def key(self) -> str:
        return "dash_realtime"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "可视化与洞察"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["grafana.dashboard.list"]

    def analyze(self, store) -> ScoreResult:
        dashboards: list[GrafanaDashboardRecord] = store.get("grafana.dashboard.list")

        if not dashboards:
            return self._not_scored("未配置 Grafana 仪表盘", [])

        realtime_intervals = {"5s", "10s", "15s"}
        near_realtime_intervals = {"30s", "1m", "60s"}

        realtime_dashboards = []
        near_realtime_dashboards = []
        low_frequency_dashboards = []
        no_refresh_dashboards = []

        core_keywords = ["error", "alert", "critical", "incident", "故障", "告警", "实时"]
        core_realtime_count = 0
        core_total_count = 0

        for dash in dashboards:
            interval = (dash.refresh_interval or "").strip().lower()
            dash_title = (dash.title or "").lower()
            is_core = any(kw in dash_title for kw in core_keywords)

            if is_core:
                core_total_count += 1

            if interval in realtime_intervals:
                realtime_dashboards.append(dash)
                if is_core:
                    core_realtime_count += 1
            elif interval in near_realtime_intervals:
                near_realtime_dashboards.append(dash)
            elif interval in ("", "off", "0", "false", "null"):
                no_refresh_dashboards.append(dash)
            else:
                low_frequency_dashboards.append(dash)

        evidence = [
            f"仪表盘总数: {len(dashboards)}",
            f"实时刷新 (≤15s): {len(realtime_dashboards)} 个",
            f"近实时 (30s-1m): {len(near_realtime_dashboards)} 个",
            f"低频刷新 (>1m): {len(low_frequency_dashboards)} 个",
            f"无自动刷新: {len(no_refresh_dashboards)} 个"
        ]

        effective_refresh_count = len(realtime_dashboards) + len(near_realtime_dashboards)

        if effective_refresh_count == 0:
            return self._not_scored("仪表盘未配置有效的自动刷新 (≤1m)", evidence)

        total_count = len(dashboards)
        realtime_ratio = len(realtime_dashboards) / total_count
        effective_refresh_ratio = effective_refresh_count / total_count
        no_refresh_ratio = len(no_refresh_dashboards) / total_count

        core_realtime_ratio = core_realtime_count / core_total_count if core_total_count > 0 else 1.0
        if core_total_count > 0:
            evidence.append(
                f"核心盘实时覆盖: {core_realtime_count}/{core_total_count} ({core_realtime_ratio * 100:.0f}%)")

        score = 0.0

        # 1. 实时刷新比例（最高 2 分）
        realtime_score = min(realtime_ratio / 0.5, 1.0) * 2.0
        score += realtime_score

        # 2. 近实时补充（最高 1 分）
        near_only_ratio = max(0, int(effective_refresh_ratio - realtime_ratio))
        near_score = min(near_only_ratio / 0.5, 1.0) * 1.0
        score += near_score

        # 3. 核心盘实时覆盖奖励/惩罚（最高 1 分）
        if core_total_count > 0:
            if core_realtime_ratio >= 0.8:
                score += 1.0
                evidence.append("✓ 核心盘实时覆盖充足")
            elif core_realtime_ratio >= 0.5:
                score += 0.5
                evidence.append("ℹ️ 核心盘部分实时")
            else:
                evidence.append("⚠️ 核心盘实时覆盖不足，建议优先配置")

        # 4. 无刷新盘惩罚（最大 -1 分）
        if no_refresh_ratio >= 0.5:
            score -= 1.0
            evidence.append("⚠️ 超过半数仪表盘未配置自动刷新")
        elif no_refresh_ratio >= 0.3:
            score -= 0.5
            evidence.append("ℹ️ 较多仪表盘未配置自动刷新")

        final_score = max(min(round(score), 4), 0)

        if final_score >= 4:
            conclusion = "实时监控能力完善：多数仪表盘 ≤15s 刷新，核心盘覆盖充足"
        elif final_score >= 3:
            conclusion = "实时监控能力较好，建议提升核心盘刷新频率"
        elif final_score >= 2:
            conclusion = "具备基础实时监控能力，建议扩大实时覆盖范围"
        elif final_score >= 1:
            conclusion = "实时监控能力有限，多为低频刷新"
        else:
            conclusion = "实时监控能力薄弱，建议检查仪表盘使用情况"

        return self._scored(final_score, conclusion, evidence)


class DashHistoricalAnalyzer(Analyzer):
    """
    历史回溯分析器
    
    评估标准：是否支持长周期 (月/季) 的历史数据趋势分析和容量规划对比
    
    数据来源：
    - ARMS / SLS：查询历史数据的最大时间跨度，验证是否支持 3 个月以上的历史查询
    """

    def key(self) -> str:
        return "dash_historical"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "可视化与洞察"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["sls.logstore.list"]

    def optional_data(self) -> list[str]:
        return ["grafana.dashboard.list"]

    def analyze(self, store) -> ScoreResult:
        raw_logstores: list[SlsLogstoreRecord] = store.get("sls.logstore.list")
        if not raw_logstores:
            return self._not_scored("未获取到日志存储配置", [])

        logstores: list[SlsLogstoreRecord] = [ls for ls in raw_logstores if
                                              ls.ttl and isinstance(ls.ttl, (int, float))]

        if not logstores:
            return self._not_scored("有效的日志存储配置为空", [])

        ttls = [ls.ttl for ls in logstores]
        max_retention = max(ttls)
        avg_retention = sum(ttls) / len(ttls)
        total = len(logstores)

        # 各档位覆盖率
        count_ge_180 = sum(1 for t in ttls if t >= 180)
        count_ge_90 = sum(1 for t in ttls if t >= 90)
        count_ge_30 = sum(1 for t in ttls if t >= 30)
        count_lt_7 = sum(1 for t in ttls if t < 7)

        evidence = [
            f"Logstore 数量: {total}",
            f"最长保留: {max_retention} 天",
            f"平均保留: {avg_retention:.1f} 天",
            f"保留 >= 180 天: {count_ge_180} 个 ({count_ge_180 / total * 100:.1f}%)",
            f"保留 >= 90 天: {count_ge_90} 个 ({count_ge_90 / total * 100:.1f}%)",
            f"保留 >= 30 天: {count_ge_30} 个 ({count_ge_30 / total * 100:.1f}%)"
        ]

        score = 0.0

        # 1. 平均保留期（最高 2 分）
        avg_score = min(avg_retention / 180, 1.0) * 2.0
        score += avg_score

        # 2. 最大保留期补充（最高 1 分）
        if max_retention >= 180:
            score += 1.0
            evidence.append("✓ 支持半年级历史分析")
        elif max_retention >= 90:
            score += 0.5
            evidence.append("✓ 支持季度级历史分析")

        # 3. 长周期覆盖率（最高 1 分）
        long_term_ratio = count_ge_90 / total
        if long_term_ratio >= 0.5:
            score += 1.0
            evidence.append(f"✓ 长周期存储覆盖充足 ({long_term_ratio * 100:.0f}%)")
        elif long_term_ratio >= 0.3:
            score += 0.5
            evidence.append(f"ℹ️ 长周期存储部分覆盖 ({long_term_ratio * 100:.0f}%)")

        # 4. 短保留惩罚（最大 -1 分）
        short_ratio = count_lt_7 / total
        if short_ratio >= 0.3:
            score -= 1.0
            evidence.append(f"⚠️ 较多短保留 Logstore ({short_ratio * 100:.0f}% < 7天)")
        elif short_ratio >= 0.1:
            score -= 0.5
            evidence.append(f"ℹ️ 部分短保留 Logstore ({short_ratio * 100:.0f}% < 7天)")

        final_score = max(min(round(score), 4), 0)

        if final_score >= 4:
            conclusion = "历史回溯能力完善：平均保留期长、长周期覆盖充足"
        elif final_score >= 3:
            conclusion = "历史回溯能力良好：支持季度级分析"
        elif final_score >= 2:
            conclusion = "历史回溯能力基础：支持月度级分析"
        elif final_score >= 1:
            conclusion = "历史回溯能力有限：仅支持周级分析"
        else:
            conclusion = "历史回溯能功薄弱：数据保留期过短"

        return self._scored(final_score, conclusion, evidence)


class DashRoleBasedAnalyzer(Analyzer):
    """
    角色视图分析器
    
    评估标准：检查是否存在按 folder 或 tag 隔离的视图
    - 如 folder: dev-view, folder: exec-view
    - 或仪表盘内包含丰富的 templating 变量供用户自筛选
    
    数据来源：
    - ARMS Grafana API：仪表盘列表和文件夹结构
    """

    def key(self) -> str:
        return "dash_role_based"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "可视化与洞察"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["grafana.dashboard.list"]

    def optional_data(self) -> list[str]:
        return ["grafana.folder.list"]

    def analyze(self, store) -> ScoreResult:
        dashboards: list[GrafanaDashboardRecord] = store.get("grafana.dashboard.list")

        if not dashboards:
            return self._not_scored("未配置 Grafana 仪表盘", [])

        evidence = [f"仪表盘总数: {len(dashboards)}"]
        score = 0.0

        folders: list[GrafanaFolderRecord] = store.get("grafana.folder.list")
        if folders:
            role_keywords = {
                "dev": ["dev-team", "developer", "dev-view", "开发"],
                "ops": ["ops-team", "operator", "ops-view", "sre", "运维"],
                "exec": ["exec", "executive", "manager", "管理层", "高管"],
                "business": ["business", "product", "业务", "产品"]
            }
            flat_keywords = [kw for kws in role_keywords.values() for kw in kws]

            role_folders = [f for f in folders if any(kw in f.title.lower() for kw in flat_keywords)]
            evidence.append(f"文件夹数: {len(folders)}")

            if role_folders:
                role_ratio = len(role_folders) / len(folders)
                folder_score = min(role_ratio / 0.3, 1.0) * 1.5
                score += folder_score
                evidence.append(f"✓ 角色文件夹: {len(role_folders)} 个 ({role_ratio * 100:.0f}%)")
            else:
                evidence.append("ℹ️ 未检测到明确的角色隔离文件夹")
        else:
            evidence.append("ℹ️ 未获取文件夹数据")

        # --- 2. Templating 变量丰富度（最高 1.5 分）---
        total_vars = sum(d.variable_count for d in dashboards)
        avg_vars = total_vars / len(dashboards) if dashboards else 0
        dashboards_with_vars = [d for d in dashboards if d.variable_count > 0]
        var_coverage = len(dashboards_with_vars) / len(dashboards) if dashboards else 0

        evidence.append(f"平均变量数: {avg_vars:.1f}")
        evidence.append(f"有变量的仪表盘: {len(dashboards_with_vars)} 个 ({var_coverage * 100:.0f}%)")

        if avg_vars >= 3 and var_coverage >= 0.5:
            score += 1.5
            evidence.append("✓ 丰富的 templating 变量配置")
        elif avg_vars >= 2 and var_coverage >= 0.3:
            score += 1.0
            evidence.append("ℹ️ 变量配置较为充实")
        elif avg_vars >= 1:
            score += 0.5
            evidence.append("ℹ️ 基础变量配置")
        else:
            evidence.append("⚠️ 缺少 templating 变量，仪表盘交互性有限")

        # --- 3. 标签分类体系（最高 1 分）---
        all_tags: set[str] = set()
        tagged_dashboards = 0
        for dash in dashboards:
            if dash.tags:
                all_tags.update(t.lower() for t in dash.tags)
                tagged_dashboards += 1

        tag_coverage = tagged_dashboards / len(dashboards) if dashboards else 0
        evidence.append(f"标签种类: {len(all_tags)}，带标签盘: {tagged_dashboards} 个 ({tag_coverage * 100:.0f}%)")

        if len(all_tags) >= 8 and tag_coverage >= 0.6:
            score += 1.0
            evidence.append("✓ 完善的标签分类体系")
        elif len(all_tags) >= 5 and tag_coverage >= 0.4:
            score += 0.5
            evidence.append("ℹ️ 基础标签分类")
        else:
            evidence.append("ℹ️ 标签分类有待完善")

        final_score = max(min(round(score), 4), 0)

        if final_score >= 4:
            conclusion = "角色视图完善：文件夹隔离 + 丰富变量 + 完善标签"
        elif final_score >= 3:
            conclusion = "角色视图能力较好，建议补全某一维度"
        elif final_score >= 2:
            conclusion = "具备基础角色视图能力"
        elif final_score >= 1:
            conclusion = "角色视图能力有限，建议优化文件夹或变量配置"
        else:
            conclusion = "仪表盘无角色隔离或变量配置"

        return self._scored(final_score, conclusion, evidence)


class DashActionableAnalyzer(Analyzer):
    """
    可行动性分析器
    
    评估标准：仪表盘是否直接关联下钻分析或告警触发入口，而非仅展示静态图表
    
    数据来源：
    - ARMS：检查仪表盘面板是否配置了告警联动或下钻链接
    """

    def key(self) -> str:
        return "dash_actionable"

    def dimension(self) -> str:
        return "Observability"

    def category(self) -> str:
        return "可视化与洞察"

    def max_score(self) -> int:
        return 3

    def required_data(self) -> list[str]:
        return ["grafana.dashboard.list"]

    def analyze(self, store) -> ScoreResult:
        dashboards: list[GrafanaDashboardRecord] = store.get("grafana.dashboard.list")

        if not dashboards:
            return self._not_scored("未配置 Grafana 仪表盘", [])

        total_count = len(dashboards)

        with_alerts = [d for d in dashboards if d.alert_count > 0]
        with_links = [d for d in dashboards if d.has_links]

        evidence = [
            f"仪表盘总数: {total_count}",
            f"有告警配置的仪表盘: {len(with_alerts)} 个",
            f"支持下钻的仪表盘: {len(with_links)} 个"
        ]

        score = 0.0

        # --- 1. 告警联动能力（最高 1.5 分）---
        total_alerts = sum(d.alert_count for d in with_alerts)
        alert_coverage = len(with_alerts) / total_count if total_count > 0 else 0

        evidence.append(f"告警规则总数: {total_alerts}")

        avg_alerts_per_dash = total_alerts / total_count if total_count > 0 else 0
        alert_score = 0.0

        if avg_alerts_per_dash >= 2.0 and alert_coverage >= 0.4:
            alert_score = 1.5
            evidence.append("✓ 完善的告警联动：告警规则充足且覆盖广泛")
        elif avg_alerts_per_dash >= 1.0 and alert_coverage >= 0.2:
            alert_score = 1.0
            evidence.append("ℹ️ 基础告警联动：有一定的告警规则配置")
        elif total_alerts > 0:
            alert_score = 0.5
            evidence.append(f"ℹ️ 告警配置较少: 共 {total_alerts} 条，建议扩充覆盖")
        else:
            evidence.append("⚠️ 未配置告警联动")

        score += alert_score

        # --- 2. 下钻链接能力（最高 1.5 分）---
        link_coverage = len(with_links) / total_count if total_count > 0 else 0

        core_keywords = ["error", "alert", "critical", "incident", "故障", "告警", "实时"]
        core_dashboards = [d for d in dashboards if any(kw in (d.title or "").lower() for kw in core_keywords)]
        core_with_links = [d for d in core_dashboards if d.has_links]
        core_link_coverage = len(core_with_links) / len(core_dashboards) if core_dashboards else 1.0

        evidence.append(f"下钻链接覆盖: {link_coverage * 100:.0f}%")
        if core_dashboards:
            evidence.append(
                f"核心盘下钻覆盖: {core_link_coverage * 100:.0f}% ({len(core_with_links)}/{len(core_dashboards)})")

        link_score = 0.0
        if link_coverage >= 0.5 and core_link_coverage >= 0.6:
            link_score = 1.5
            evidence.append("✓ 完善的下钻能力：全面覆盖且核心盘支持")
        elif link_coverage >= 0.3 or core_link_coverage >= 0.5:
            link_score = 1.0
            evidence.append("ℹ️ 基础下钻能力：部分仪表盘支持跳转")
        elif with_links:
            link_score = 0.5
            evidence.append("ℹ️ 下钻能力有限：仅少量仪表盘配置链接")
        else:
            evidence.append("⚠️ 缺失下钻链接：无法从图表跳转至详情")

        score += link_score

        final_score = max(min(round(score), 3), 0)

        if final_score >= 3:
            conclusion = "仪表盘可行动性完善：告警联动充足、下钻链接完善"
        elif final_score >= 2:
            conclusion = "仪表盘具备良好可行动性，建议补全缺失维度"
        elif final_score >= 1:
            conclusion = "仪表盘可行动性基础，主要依赖静态展示"
        else:
            conclusion = "仪表盘缺乏可行助性：无告警联动、无下钻链接"

        return self._scored(final_score, conclusion, evidence)


VISUALIZATION_ANALYZERS = [
    DashDiversityAnalyzer(),
    DashRealtimeAnalyzer(),
    DashHistoricalAnalyzer(),
    DashRoleBasedAnalyzer(),
    DashActionableAnalyzer(),
]
