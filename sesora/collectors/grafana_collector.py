"""
Grafana Collector - Grafana 仪表盘采集器

支持以下数据源：
1. 自建 Grafana / 第三方 Grafana（通过 URL + API Token）
2. 阿里云 ARMS Grafana（通过 workspace_id）

采集内容：
- Grafana 仪表盘列表及详细信息
- 文件夹结构
- 仪表盘分析汇总
"""
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import List, Optional
import requests
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.grafana import (
    GrafanaDashboardRecord,
    GrafanaFolderRecord,
    GrafanaDashboardAnalysisRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class GrafanaCollectorConfig:
    """Grafana Collector 配置"""
    grafana_url: str = ""
    grafana_api_token: str = ""
    grafana_workspace_id: str = ""
    grafana_folder_ids: List[int] = None
    grafana_tags: List[str] = None

    def __post_init__(self):
        if self.grafana_folder_ids is None:
            self.grafana_folder_ids = []
        if self.grafana_tags is None:
            self.grafana_tags = []


class GrafanaCollector(CollectorBase):
    def __init__(self, config: GrafanaCollectorConfig):
        self.config = config
        self.grafana_url = config.grafana_url
        self.api_token = config.grafana_api_token
        self.folder_ids = config.grafana_folder_ids
        self.tags = config.grafana_tags
        
        # 如果是阿里云 ARMS Grafana，构造 URL
        if config.grafana_workspace_id and not self.grafana_url:
            self.grafana_url = f"https://{config.grafana_workspace_id}.grafana.aliyuncs.com"
        
        if not self.grafana_url:
            raise ValueError("必须提供 grafana_url 或 grafana_workspace_id")
        if not self.api_token:
            raise ValueError("必须提供 grafana_api_token")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

    def name(self) -> str:
        return "grafana_collector"

    def _collect(self) -> List:
        """执行 Grafana 数据采集"""
        records: List = []

        # 采集文件夹
        folders = self._collect_folders()
        records.extend(folders)
        logger.info(f"采集到 {len(folders)} 个文件夹")

        # 采集仪表盘
        dashboards = self._collect_dashboards()
        records.extend(dashboards)
        logger.info(f"采集到 {len(dashboards)} 个仪表盘")

        # 生成分析汇总
        analysis = self._generate_analysis(dashboards)
        records.append(analysis)
        logger.info("生成分析汇总记录")

        return records

    def _collect_folders(self) -> List[GrafanaFolderRecord]:
        """采集 Grafana 文件夹"""
        records: List[GrafanaFolderRecord] = []

        try:
            response = requests.get(
                f"{self.grafana_url}/api/folders",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            folders = response.json()

            for folder in folders:
                # 过滤文件夹
                if self.folder_ids and folder["id"] not in self.folder_ids:
                    continue

                # 获取文件夹中的仪表盘数量
                search_response = requests.get(
                    f"{self.grafana_url}/api/search",
                    headers=self.headers,
                    params={"folderIds": folder["id"], "type": "dash-db"},
                    timeout=30
                )
                dashboard_count = len(search_response.json()) if search_response.ok else 0

                record = GrafanaFolderRecord(
                    id=folder["id"],
                    uid=folder["uid"],
                    title=folder["title"],
                    dashboard_count=dashboard_count,
                    create_time=self._parse_datetime(folder.get("created")),
                )
                records.append(record)

        except Exception as e:
            logger.error(f"采集文件夹失败: {e}")

        return records

    def _collect_dashboards(self) -> List[GrafanaDashboardRecord]:
        """采集 Grafana 仪表盘"""
        records: List[GrafanaDashboardRecord] = []

        try:
            # 1. 获取仪表盘列表
            params = {"type": "dash-db"}
            if self.folder_ids:
                params["folderIds"] = ",".join(map(str, self.folder_ids))
            if self.tags:
                params["tag"] = self.tags

            response = requests.get(
                f"{self.grafana_url}/api/search",
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            dashboards = response.json()

            # 2. 获取每个仪表盘的详细信息
            for dash in dashboards:
                try:
                    record = self._collect_dashboard_detail(dash)
                    records.append(record)
                except Exception as e:
                    logger.warning(f"获取仪表盘 {dash.get('uid')} 详情失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"采集仪表盘列表失败: {e}")

        return records

    def _collect_dashboard_detail(self, dashboard_summary: dict) -> GrafanaDashboardRecord:
        """获取单个仪表盘的详细信息"""
        uid = dashboard_summary["uid"]
        
        # 获取仪表盘完整定义
        response = requests.get(
            f"{self.grafana_url}/api/dashboards/uid/{uid}",
            headers=self.headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        dashboard = data.get("dashboard", {})
        meta = data.get("meta", {})

        # 解析面板
        panels = dashboard.get("panels", [])
        panels_count = len([p for p in panels if p.get("type") != "row"])

        # 解析模板变量
        templating = dashboard.get("templating", {})
        templating_list = templating.get("list", [])
        templating_vars = [v["name"] for v in templating_list if v.get("name")]
        has_templating = len(templating_vars) > 0

        # 解析告警（Grafana 8+ 使用 unified alerting）
        has_alerts = False
        alert_count = 0
        alert_rules_count = 0
        
        # 检查面板中的告警
        for panel in panels:
            if panel.get("alert"):
                has_alerts = True
                alert_count += 1
                alert_rules_count += 1

        # 检查链接和下钻
        links = dashboard.get("links", [])
        has_links = len(links) > 0
        has_drill_down = any(
            link.get("type") in ["link", "dashboards"] 
            for link in links
        )

        # 检查面板中的链接
        if not has_drill_down:
            for panel in panels:
                if panel.get("links") or panel.get("fieldConfig", {}).get("defaults", {}).get("links"):
                    has_drill_down = True
                    break

        return GrafanaDashboardRecord(
            uid=uid,
            title=dashboard.get("title", ""),
            folder_id=dashboard_summary.get("folderId", 0),
            folder_title=dashboard_summary.get("folderTitle", ""),
            tags=dashboard.get("tags", []),
            panels_count=panels_count,
            refresh_interval=dashboard.get("refresh", ""),
            time_range=dashboard.get("time", {}).get("from", ""),
            has_templating=has_templating,
            templating_vars=templating_vars,
            variable_count=len(templating_vars),
            has_alerts=has_alerts,
            alert_rules_count=alert_rules_count,
            alert_count=alert_count,
            has_drill_down=has_drill_down,
            has_links=has_links,
            create_time=self._parse_datetime(meta.get("created")),
            update_time=self._parse_datetime(meta.get("updated")),
        )

    def _generate_analysis(
        self, dashboards: List[GrafanaDashboardRecord]
    ) -> GrafanaDashboardAnalysisRecord:
        """生成仪表盘分析汇总"""
        system_dashboards = 0
        app_dashboards = 0
        business_dashboards = 0
        ux_dashboards = 0
        realtime_dashboards = 0
        dashboards_with_alerts = 0
        dashboards_with_drilldown = 0

        for dash in dashboards:
            # 按标签分类
            tags = [tag.lower() for tag in dash.tags]
            if any(tag in tags for tag in ["system", "infrastructure", "infra", "k8s", "nodes"]):
                system_dashboards += 1
            if any(tag in tags for tag in ["app", "application", "apm", "service"]):
                app_dashboards += 1
            if any(tag in tags for tag in ["business", "metrics", "kpi"]):
                business_dashboards += 1
            if any(tag in tags for tag in ["ux", "frontend", "rum", "user"]):
                ux_dashboards += 1

            # 实时仪表盘（刷新间隔 <= 15s）
            refresh = dash.refresh_interval
            if refresh:
                try:
                    # 解析刷新间隔，如 "5s", "1m", "30s"
                    if refresh.endswith("s"):
                        seconds = int(refresh[:-1])
                        if seconds <= 15:
                            realtime_dashboards += 1
                except:
                    pass

            # 统计告警和下钻
            if dash.has_alerts:
                dashboards_with_alerts += 1
            if dash.has_drill_down:
                dashboards_with_drilldown += 1

        # 获取唯一文件夹数
        folder_ids = set(dash.folder_id for dash in dashboards)
        folders_count = len(folder_ids)

        return GrafanaDashboardAnalysisRecord(
            total_dashboards=len(dashboards),
            system_dashboards=system_dashboards,
            app_dashboards=app_dashboards,
            business_dashboards=business_dashboards,
            ux_dashboards=ux_dashboards,
            realtime_dashboards=realtime_dashboards,
            dashboards_with_alerts=dashboards_with_alerts,
            dashboards_with_drilldown=dashboards_with_drilldown,
            folders_count=folders_count,
        )

    @staticmethod
    def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """解析 datetime 字符串"""
        if not dt_str:
            return None
        try:
            # Grafana 返回 ISO 8601 格式
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except:
            return None
