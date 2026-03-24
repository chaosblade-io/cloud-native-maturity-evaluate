"""
Resilience 维度 - 高可用性 (High Availability) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                       |
| ha_redundancy             | 7    | 冗余设计：所有关键组件至少双副本/主从模式运行，无单点故障       |
| ha_multi_zone             | 8    | 多可用区部署：应用实例均匀分布在至少 2 个不同的可用区           |
| ha_load_balancing         | 5    | 负载均衡：入口流量和内部服务间调用均通过负载均衡器分发         |
| ha_global_dist            | 5    | 全球/多活分布：(高阶项) 跨地域的流量调度或异地多活架构         |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import K8sDeploymentRecord, K8sStatefulSetRecord, K8sNodeRecord, K8sIngressRecord, K8sServiceRecord
from ...schema.rds_oss import GtmAddressPoolRecord


class HaRedundancy(Analyzer):
    """
    冗余设计分析器
    
    评估标准：所有关键组件（应用、DB、中间件）是否至少以双副本/主从模式运行，无单点故障 (SPOF)
    
    数据来源：
    - UModel：kube_deployment_spec_replicas，检查所有 Deployment 的副本数
    - UModel：kube_statefulset_replicas，检查 StatefulSet 副本数
    """
    
    def key(self) -> str:
        return "ha_redundancy"
    
    def dimension(self) -> str:
        return "Resilience"
    
    def category(self) -> str:
        return "高可用性"
    
    def max_score(self) -> int:
        return 7
    
    def required_data(self) -> list[str]:
        return ["k8s.deployment.list"]
    
    def optional_data(self) -> list[str]:
        return ["k8s.statefulset.list"]
    
    def analyze(self, store) -> ScoreResult:
        deployments: list[K8sDeploymentRecord] = store.get("k8s.deployment.list")
        
        all_workloads = []
        for d in deployments:
            all_workloads.append({
                "name": f"{d.namespace}/{d.name}", 
                "replicas": d.replicas, 
                "type": "Deployment"
            })
        
        if store.available("k8s.statefulset.list"):
            statefulsets: list[K8sStatefulSetRecord] = store.get("k8s.statefulset.list")
            for s in statefulsets:
                all_workloads.append({
                    "name": f"{s.namespace}/{s.name}", 
                    "replicas": s.replicas, 
                    "type": "StatefulSet"
                })
        
        if not all_workloads:
            return self._not_evaluated("未发现任何工作负载")
        
        # 识别单副本工作负载（单点故障风险）
        singles = [w for w in all_workloads if w["replicas"] <= 1]
        
        if not singles:
            return self._scored(
                7,
                "所有工作负载均为多副本部署，无单点故障",
                [f"共 {len(all_workloads)} 个工作负载，全部为多副本"]
            )
        
        single_ratio = len(singles) / len(all_workloads)
        evidence = [f"{w['type']} {w['name']} replicas={w['replicas']}" for w in singles[:10]]
        if len(singles) > 10:
            evidence.append(f"... 等共 {len(singles)} 个单副本工作负载")
        
        if single_ratio <= 0.1:
            return self._scored(5, f"存在少量单副本工作负载 ({len(singles)}/{len(all_workloads)})", evidence)
        elif single_ratio <= 0.3:
            return self._scored(3, f"存在较多单副本工作负载 ({len(singles)}/{len(all_workloads)})", evidence)
        else:
            return self._not_scored(f"大量工作负载为单副本 ({len(singles)}/{len(all_workloads)})", evidence)


class HaMultiZone(Analyzer):
    """
    多可用区部署分析器
    
    评估标准：应用实例是否均匀分布在至少 2 个不同的可用区 (AZ)，且存储支持跨 AZ 同步
    
    数据来源：
    - UModel：k8s.node entity_set 的 labels 字段，包含 topology.kubernetes.io/zone 标签
    - 通过 Pod-Node 关系可以推算 Pod 的可用区分布
    """
    
    def key(self) -> str:
        return "ha_multi_zone"
    
    def dimension(self) -> str:
        return "Resilience"
    
    def category(self) -> str:
        return "高可用性"
    
    def max_score(self) -> int:
        return 8
    
    def required_data(self) -> list[str]:
        return ["k8s.node.list"]
    
    def analyze(self, store) -> ScoreResult:
        nodes: list[K8sNodeRecord] = store.get("k8s.node.list")
        
        if not nodes:
            return self._not_evaluated("未发现任何节点")
        
        # 统计各可用区的节点数
        zones = {}
        for node in nodes:
            zone = node.zone or node.labels.get("topology.kubernetes.io/zone", "unknown")
            zones[zone] = zones.get(zone, 0) + 1
        
        zone_count = len([z for z in zones.keys() if z != "unknown"])
        evidence = [f"{zone}: {count} 个节点" for zone, count in zones.items()]
        
        if zone_count == 0:
            return self._not_scored("无法识别节点的可用区信息", [f"共 {len(nodes)} 个节点，缺少可用区标签"])
        
        if zone_count >= 3:
            return self._scored(8, f"节点分布在 {zone_count} 个可用区，具备高可用能力", evidence)
        elif zone_count == 2:
            return self._scored(6, f"节点分布在 {zone_count} 个可用区，基本满足高可用要求", evidence)
        else:
            return self._not_scored(f"所有节点集中在单一可用区，存在单点故障风险", evidence)


class HaLoadBalancing(Analyzer):
    """
    负载均衡分析器
    
    评估标准：入口流量和内部服务间调用是否均通过负载均衡器分发，且健康检查正常
    
    数据来源：
    - UModel：k8s.ingress entity_set，Ingress 列表
    - UModel：k8s.metric.ingress_deployment，Ingress 流量分发指标
    """
    
    def key(self) -> str:
        return "ha_load_balancing"
    
    def dimension(self) -> str:
        return "Resilience"
    
    def category(self) -> str:
        return "高可用性"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["k8s.ingress.list", "k8s.service.list"]
    
    def analyze(self, store) -> ScoreResult:
        ingresses: list[K8sIngressRecord] = store.get("k8s.ingress.list")
        services: list[K8sServiceRecord] = store.get("k8s.service.list")
        
        has_ingress = len(ingresses) > 0
        lb_services = [s for s in services if s.type == "LoadBalancer"]
        
        evidence = []
        
        if has_ingress:
            evidence.append(f"Ingress 数量: {len(ingresses)}")
        if lb_services:
            evidence.append(f"LoadBalancer Service 数量: {len(lb_services)}")
        
        if has_ingress and lb_services:
            return self._scored(5, "已配置 Ingress 和 LoadBalancer Service，流量分发完善", evidence)
        elif has_ingress:
            return self._scored(4, "已配置 Ingress 进行流量分发", evidence)
        elif lb_services:
            return self._scored(3, "已配置 LoadBalancer Service 进行流量分发", evidence)
        else:
            return self._not_scored("未配置 Ingress 或 LoadBalancer，缺少负载均衡", [f"仅有 ClusterIP Service {len(services)} 个"])


class HaGlobalDist(Analyzer):
    """
    全球/多活分布分析器
    
    评估标准：(可选高阶项) 是否实现了跨地域 (Region) 的流量调度或异地多活架构
    
    数据来源：
    - GTM API：地址池配置、健康检查策略、地理路由策略
    """
    
    def key(self) -> str:
        return "ha_global_dist"
    
    def dimension(self) -> str:
        return "Resilience"
    
    def category(self) -> str:
        return "高可用性"
    
    def max_score(self) -> int:
        return 5
    
    def required_data(self) -> list[str]:
        return ["gtm.address_pool.list"]
    
    def analyze(self, store) -> ScoreResult:
        pools: list[GtmAddressPoolRecord] = store.get("gtm.address_pool.list")
        
        if not pools:
            return self._not_scored("未配置 GTM 全局流量管理，无跨地域流量调度能力", [])
        
        # 检查是否有多个地址池和健康检查
        active_pools = [p for p in pools if p.monitor_status == "OPEN"]
        evidence = [f"地址池: {p.pool_name}, 负载策略: {p.lb_strategy}" for p in active_pools]
        
        if len(active_pools) >= 2:
            return self._scored(5, f"已配置 GTM 全局流量管理，具备 {len(active_pools)} 个活跃地址池", evidence)
        elif active_pools:
            return self._scored(3, "已配置 GTM 但仅有单一活跃地址池", evidence)
        else:
            return self._scored(1, "已配置 GTM 但未开启健康检查", [f"共 {len(pools)} 个地址池，均未开启监控"])


# 导出所有分析器
HA_ANALYZERS = [
    HaRedundancy(),
    HaMultiZone(),
    HaLoadBalancing(),
    HaGlobalDist(),
]
