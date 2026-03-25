from datetime import datetime
from typing import List, Optional, Tuple

import yaml
from alibabacloud_cs20151215 import models as cs_models
from alibabacloud_cs20151215.client import Client as CSClient
from alibabacloud_tea_openapi import models as open_api_models
from kubernetes import client as k8s_client, config as k8s_config

from sesora.core.context import AssessmentContext
from sesora.core.dataitem import DataSource
from sesora.schema.k8s import (
    K8sNodeRecord,
    K8sDeploymentRecord,
    K8sStatefulSetRecord,
    K8sPodRecord,
    K8sPodProbesRecord,
    ContainerProbeConfig,
    K8sCronJobRecord,
    K8sServiceRecord,
    K8sIngressRecord,
    K8sNetworkPolicyRecord,
    K8sEventRecord,
    K8sHpaRecord,
    HpaMetric,
    MetricTarget,
    MetricIdentifier,
    LabelSelector,
    ObjectReference,
    K8sNamespaceRecord,
    K8sResourceQuotaRecord,
    K8sPvRecord,
    K8sAhpaMetricsRecord,
    K8sVpaRecord,
    IstioDestinationRuleRecord,
    IstioVirtualServiceRecord,
    ArgoCdApplicationRecord,
    K8sGatekeeperConstraintRecord,
    K8sKyvernoPolicyRecord,
)
from sesora.schema.chaos import (
    ChaosExperimentRecord,
    ChaosExperimentRunRecord,
    ChaosScheduleRecord,
    ChaosWorkflowRecord,
)
from sesora.schema.policy import (
    KyvernoPolicyRecord,
    KyvernoPolicyViolationRecord,
    OpaConstraintTemplateRecord,
    OpaConstraintRecord,
    OpaViolationRecord,
)


class ACKCollector:
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.client = self._create_client()

    def _create_client(self) -> CSClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"cs.{self.context.region}.aliyuncs.com",
            protocol="https",
        )
        return CSClient(config)

    def collect(self) -> DataSource:
        records: List = []
        status = "ok"

        try:
            kubeconfig_yamls: List[Tuple[str, str]] = []  # (source, kubeconfig_yaml)

            cluster_ids = self._get_cluster_ids()
            # for cluster_id in cluster_ids:
            #     print(f"正在采集 ACK 集群 {cluster_id} kubeconfig...")
            #     kubeconfig_yaml = self._get_cluster_kubeconfig(cluster_id)
            #     if kubeconfig_yaml is None:
            #         print(f"  获取集群 {cluster_id} kubeconfig 失败，跳过该集群")
            #         continue
            #     kubeconfig_yamls.append((f"cluster:{cluster_id}", kubeconfig_yaml))

            for kubeconfig_path in self.context.kubeconfig_paths:
                with open(kubeconfig_path, "r") as f:
                    kubeconfig_yaml = f.read()
                    kubeconfig_yamls.append(
                        (f"file:{kubeconfig_path}", kubeconfig_yaml)
                    )

            for source, kubeconfig_yaml in kubeconfig_yamls:
                print(f"正在采集 {source} 中的 Kubernetes 资源...")
                source_records = self._collect_workloads_via_k8s(kubeconfig_yaml)
                records.extend(source_records)

        except Exception as e:
            print(f"ACK 采集失败: {e}")
            status = "error"

        return DataSource(
            collector="ack_collector",
            collected_at=datetime.now(),
            status=status,
            records=records,
        )

    def _get_cluster_ids(self) -> List[str]:
        if self.context.cluster_id:
            return [self.context.cluster_id]

        cluster_ids = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.describe_clusters_for_region(
                self.context.region,
                cs_models.DescribeClustersForRegionRequest(
                    page_number=page_no, page_size=page_size
                ),
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"获取 ACK 集群列表失败: {response.status_code}")

            for cluster in body.clusters:
                cluster_ids.append(cluster.cluster_id)

            total_count = body.page_info.total_count
            if len(cluster_ids) >= total_count:
                break
            page_no += 1

        return cluster_ids

    def _get_cluster_kubeconfig(self, cluster_id: str) -> Optional[str]:
        response = self.client.describe_cluster_user_kubeconfig(
            cluster_id,
            cs_models.DescribeClusterUserKubeconfigRequest(
                private_ip_address=False,
                temporary_duration_minutes=60,
            ),
        )
        if response.status_code != 200:
            print(f"  获取集群 {cluster_id} kubeconfig 失败: {response.status_code}")
            return None
        body = response.body
        return body.config

    def _list_ns(self, list_fn_namespaced, list_fn_all):
        """根据 namespace_filter 调用命名空间或集群级别的列表接口，返回所有 items。"""
        namespace_filter = self.context.get_namespace_filter()
        if namespace_filter:
            items = []
            for ns in namespace_filter:
                items.extend(list_fn_namespaced(namespace=ns).items)
            return items
        return list_fn_all().items

    def _list_custom_ns(self, group, version, plural):
        namespace_filter = self.context.get_namespace_filter()
        custom_api = k8s_client.CustomObjectsApi()
        try:
            if namespace_filter:
                items = []
                for ns in namespace_filter:
                    items.extend(
                        custom_api.list_namespaced_custom_object(
                            group=group,
                            version=version,
                            namespace=ns,
                            plural=plural,
                        ).get("items", [])
                    )
                return items
            return custom_api.list_cluster_custom_object(
                group=group,
                version=version,
                plural=plural,
            ).get("items", [])
        except k8s_client.ApiException as e:
            if e.status == 404:
                print(f"  CRD {group}/{version}/{plural} 不存在，已跳过")
                return []
            else:
                raise

    def _collect_workloads_via_k8s(self, kubeconfig_yaml: str) -> List:
        records: List = []

        config_dict = yaml.safe_load(kubeconfig_yaml)
        k8s_config.load_kube_config_from_dict(config_dict)

        apps_v1 = k8s_client.AppsV1Api()
        core_v1 = k8s_client.CoreV1Api()
        batch_v1 = k8s_client.BatchV1Api()
        networking_v1 = k8s_client.NetworkingV1Api()
        autoscaling_v2 = k8s_client.AutoscalingV2Api()
        custom_api = k8s_client.CustomObjectsApi()

        namespace_filter = self.context.get_namespace_filter()

        # Namespace
        ns_list = core_v1.list_namespace()
        for ns_obj in ns_list.items:
            record = self._parse_namespace(ns_obj)
            records.append(record)

        # Node（通过 K8s API 获取完整信息）
        node_list = core_v1.list_node()
        for node in node_list.items:
            record = self._parse_node_via_k8s(node)
            records.append(record)

        # PersistentVolume
        pv_list = core_v1.list_persistent_volume()
        for pv in pv_list.items:
            record = self._parse_pv(pv)
            records.append(record)

        # Deployment
        deploy_list = self._list_ns(
            apps_v1.list_namespaced_deployment,
            apps_v1.list_deployment_for_all_namespaces,
        )
        for deploy in deploy_list:
            record = self._parse_deployment(deploy)
            records.append(record)

        # StatefulSet
        sts_list = self._list_ns(
            apps_v1.list_namespaced_stateful_set,
            apps_v1.list_stateful_set_for_all_namespaces,
        )
        for sts in sts_list:
            record = self._parse_statefulset(sts)
            records.append(record)

        # Pod + PodProbes
        pod_list = self._list_ns(
            core_v1.list_namespaced_pod, core_v1.list_pod_for_all_namespaces
        )
        for pod in pod_list:
            pod_record = self._parse_pod(pod)
            records.append(pod_record)
            probe_records = self._parse_pod_probes(pod)
            records.extend(probe_records)

        # CronJob
        cj_list = self._list_ns(
            batch_v1.list_namespaced_cron_job, batch_v1.list_cron_job_for_all_namespaces
        )
        for cj in cj_list:
            record = self._parse_cronjob(cj)
            records.append(record)

        # Service
        svc_list = self._list_ns(
            core_v1.list_namespaced_service, core_v1.list_service_for_all_namespaces
        )
        for svc in svc_list:
            record = self._parse_service(svc)
            records.append(record)

        # Ingress
        ing_list = self._list_ns(
            networking_v1.list_namespaced_ingress,
            networking_v1.list_ingress_for_all_namespaces,
        )
        for ing in ing_list:
            record = self._parse_ingress(ing)
            records.append(record)

        # NetworkPolicy
        np_list = self._list_ns(
            networking_v1.list_namespaced_network_policy,
            networking_v1.list_network_policy_for_all_namespaces,
        )
        for np_obj in np_list:
            record = self._parse_network_policy(np_obj)
            records.append(record)

        # Event
        event_list = self._list_ns(
            core_v1.list_namespaced_event, core_v1.list_event_for_all_namespaces
        )
        for event in event_list:
            record = self._parse_event(event)
            records.append(record)

        # HPA
        hpa_list = self._list_ns(
            autoscaling_v2.list_namespaced_horizontal_pod_autoscaler,
            autoscaling_v2.list_horizontal_pod_autoscaler_for_all_namespaces,
        )
        for hpa in hpa_list:
            record = self._parse_hpa(hpa)
            records.append(record)

        # ResourceQuota
        rq_list = self._list_ns(
            core_v1.list_namespaced_resource_quota,
            core_v1.list_resource_quota_for_all_namespaces,
        )
        for rq in rq_list:
            record = self._parse_resource_quota(rq)
            records.append(record)

        # AHPA (Advanced HPA, ACK CRD)
        ahpa_list = self._list_custom_ns(
            group="autoscaling.alibabacloud.com",
            version="v1beta1",
            plural="advancedhorizontalpodautoscalers",
        )
        for ahpa in ahpa_list:
            record = self._parse_ahpa(ahpa)
            records.append(record)

        # VPA (Vertical Pod Autoscaler, CRD)
        vpa_list = self._list_custom_ns(
            group="autoscaling.k8s.io",
            version="v1",
            plural="verticalpodautoscalers",
        )
        for vpa in vpa_list:
            record = self._parse_vpa(vpa)
            records.append(record)

        # Istio DestinationRule (Service Mesh CRD)
        dr_list = self._list_custom_ns(
            group="networking.istio.io",
            version="v1",
            plural="destinationrules",
        )
        for dr in dr_list:
            record = self._parse_destination_rule(dr)
            records.append(record)

        # Istio VirtualService (Service Mesh CRD)
        vs_list = self._list_custom_ns(
            group="networking.istio.io",
            version="v1",
            plural="virtualservices",
        )
        for vs in vs_list:
            record = self._parse_virtual_service(vs)
            records.append(record)

        # ArgoCD Application (GitOps CRD)
        argocd_app_list = self._list_custom_ns(
            group="argoproj.io",
            version="v1alpha1",
            plural="applications",
        )
        for app in argocd_app_list:
            record = self._parse_argocd_application(app)
            records.append(record)

        # Chaos Mesh - 各种类型的混沌实验
        chaos_types = [
            "podchaos", "networkchaos", "iochaos", "stresschaos",
            "timechaos", "kernelchaos", "dnschaos", "httpchaos"
        ]
        for chaos_type in chaos_types:
            chaos_list = self._list_custom_ns(
                group="chaos-mesh.org",
                version="v1alpha1",
                plural=chaos_type,
            )
            for chaos_obj in chaos_list:
                # 解析实验配置
                experiment_record = self._parse_chaos_experiment(chaos_obj, chaos_type)
                records.append(experiment_record)
                
                # 从实验 status 中提取执行记录
                run_records = self._parse_chaos_experiment_runs(chaos_obj)
                records.extend(run_records)

        # Chaos Mesh Schedule (调度记录)
        schedule_list = self._list_custom_ns(
            group="chaos-mesh.org",
            version="v1alpha1",
            plural="schedules",
        )
        for schedule_obj in schedule_list:
            record = self._parse_chaos_schedule(schedule_obj)
            records.append(record)

        # Chaos Mesh Workflow (工作流)
        workflow_list = self._list_custom_ns(
            group="chaos-mesh.org",
            version="v1alpha1",
            plural="workflows",
        )
        for workflow_obj in workflow_list:
            record = self._parse_chaos_workflow(workflow_obj)
            records.append(record)

        # Kyverno ClusterPolicy
        kyverno_cluster_policies = self._list_custom_ns(
            group="kyverno.io",
            version="v1",
            plural="clusterpolicies",
        )
        for policy_obj in kyverno_cluster_policies:
            # 详细版（policy schema）
            record = self._parse_kyverno_policy(policy_obj, is_cluster_policy=True)
            records.append(record)
            # 简化版（k8s schema，保持兼容性）
            simple_record = self._parse_kyverno_policy_simplified(policy_obj, is_cluster_policy=True)
            records.append(simple_record)

        # Kyverno Policy (命名空间级别)
        kyverno_policies = self._list_custom_ns(
            group="kyverno.io",
            version="v1",
            plural="policies",
        )
        for policy_obj in kyverno_policies:
            # 详细版（policy schema）
            record = self._parse_kyverno_policy(policy_obj, is_cluster_policy=False)
            records.append(record)
            # 简化版（k8s schema，保持兼容性）
            simple_record = self._parse_kyverno_policy_simplified(policy_obj, is_cluster_policy=False)
            records.append(simple_record)

        # Kyverno PolicyReport (违规记录)
        policy_reports = self._list_custom_ns(
            group="wgpolicyk8s.io",
            version="v1alpha2",
            plural="policyreports",
        )
        for report_obj in policy_reports:
            violation_records = self._parse_kyverno_policy_violations(report_obj)
            records.extend(violation_records)

        # OPA Gatekeeper ConstraintTemplates
        constraint_templates = self._list_custom_ns(
            group="templates.gatekeeper.sh",
            version="v1",
            plural="constrainttemplates",
        )
        template_kinds = []
        for template_obj in constraint_templates:
            record = self._parse_opa_constraint_template(template_obj)
            records.append(record)
            # 收集 ConstraintTemplate 的 kind 名称，用于查询对应的 Constraints
            template_kinds.append(record.crd_kind)

        # OPA Gatekeeper Constraints (动态查询各种类型)
        for kind in template_kinds:
            # Constraint 资源的 plural 通常是 kind 的小写复数形式
            plural = kind.lower() + "s" if not kind.lower().endswith("s") else kind.lower()
            try:
                constraints = self._list_custom_ns(
                    group="constraints.gatekeeper.sh",
                    version="v1beta1",
                    plural=plural,
                )
                for constraint_obj in constraints:
                    # 详细版 Constraint（policy schema）
                    record = self._parse_opa_constraint(constraint_obj, kind)
                    records.append(record)
                    # 简化版 Constraint（k8s schema，保持兼容性）
                    simple_record = self._parse_opa_constraint_simplified(constraint_obj, kind)
                    records.append(simple_record)
                    # 从 Constraint 的 status 中提取违规记录
                    violation_records = self._parse_opa_violations(constraint_obj, kind)
                    records.extend(violation_records)
            except Exception as e:
                print(f"  查询 Constraint {kind} 失败: {e}")
                continue

        return records

    def _parse_deployment(self, deploy) -> K8sDeploymentRecord:
        strategy = ""
        max_surge = None
        max_unavailable = None
        if deploy.spec.strategy:
            strategy = deploy.spec.strategy.type or ""
            if deploy.spec.strategy.rolling_update:
                ru = deploy.spec.strategy.rolling_update
                max_surge = str(ru.max_surge) if ru.max_surge is not None else None
                max_unavailable = (
                    str(ru.max_unavailable) if ru.max_unavailable is not None else None
                )

        # 解析 node_selector
        node_selector = {}
        if deploy.spec.template.spec.node_selector:
            node_selector = dict(deploy.spec.template.spec.node_selector)

        return K8sDeploymentRecord(
            namespace=deploy.metadata.namespace,
            name=deploy.metadata.name,
            replicas=deploy.spec.replicas or 0,
            ready_replicas=deploy.status.ready_replicas or 0,
            labels=dict(deploy.metadata.labels) if deploy.metadata.labels else {},
            node_selector=node_selector,
            annotations=(
                dict(deploy.metadata.annotations) if deploy.metadata.annotations else {}
            ),
            strategy=strategy,
            max_surge=max_surge,
            max_unavailable=max_unavailable,
        )

    def _parse_statefulset(self, sts) -> K8sStatefulSetRecord:
        volume_claim_templates = []
        if sts.spec.volume_claim_templates:
            for vct in sts.spec.volume_claim_templates:
                tpl = {
                    "name": vct.metadata.name,
                }
                if vct.spec and vct.spec.resources and vct.spec.resources.requests:
                    tpl["storage"] = vct.spec.resources.requests.get("storage", "")
                if vct.spec and vct.spec.access_modes:
                    tpl["access_modes"] = vct.spec.access_modes
                if vct.spec and vct.spec.storage_class_name:
                    tpl["storage_class"] = vct.spec.storage_class_name
                volume_claim_templates.append(tpl)

        return K8sStatefulSetRecord(
            namespace=sts.metadata.namespace,
            name=sts.metadata.name,
            replicas=sts.spec.replicas or 0,
            ready_replicas=sts.status.ready_replicas or 0,
            service_name=sts.spec.service_name or "",
            labels=dict(sts.metadata.labels) if sts.metadata.labels else {},
            volume_claim_templates=volume_claim_templates,
        )

    def _parse_pod(self, pod) -> K8sPodRecord:
        containers = []
        total_restart_count = 0
        resource_requests = {}
        resource_limits = {}

        for c in pod.spec.containers or []:
            container_info = {
                "name": c.name,
                "image": c.image or "",
            }
            if c.resources:
                if c.resources.requests:
                    container_info["requests"] = dict(c.resources.requests)
                    resource_requests.update(c.resources.requests)
                if c.resources.limits:
                    container_info["limits"] = dict(c.resources.limits)
                    resource_limits.update(c.resources.limits)
            containers.append(container_info)

        # 解析重启次数
        if pod.status and pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                total_restart_count += cs.restart_count or 0

        # 解析 node_selector
        node_selector = {}
        if pod.spec.node_selector:
            node_selector = dict(pod.spec.node_selector)

        # 解析 affinity
        affinity = {}
        if pod.spec.affinity:
            aff = pod.spec.affinity
            if aff.node_affinity:
                affinity["nodeAffinity"] = True
            if aff.pod_affinity:
                affinity["podAffinity"] = True
            if aff.pod_anti_affinity:
                affinity["podAntiAffinity"] = True

        return K8sPodRecord(
            namespace=pod.metadata.namespace,
            name=pod.metadata.name,
            status=pod.status.phase if pod.status else "Unknown",
            node_name=pod.spec.node_name or "",
            restart_count=total_restart_count,
            labels=dict(pod.metadata.labels) if pod.metadata.labels else {},
            containers=containers,
            creation_timestamp=pod.metadata.creation_timestamp,
            qos_class=pod.status.qos_class if pod.status else "",
            resource_requests=resource_requests,
            resource_limits=resource_limits,
            node_selector=node_selector,
            affinity=affinity,
        )

    def _parse_pod_probes(self, pod) -> List[K8sPodProbesRecord]:
        records: List[K8sPodProbesRecord] = []

        if not pod.spec.containers:
            return records

        for container in pod.spec.containers:
            liveness = self._parse_probe(container.liveness_probe)
            readiness = self._parse_probe(container.readiness_probe)
            startup = self._parse_probe(container.startup_probe)

            record = K8sPodProbesRecord(
                namespace=pod.metadata.namespace,
                pod_name=pod.metadata.name,
                container_name=container.name,
                liveness_probe=liveness,
                readiness_probe=readiness,
                startup_probe=startup,
            )
            records.append(record)

        return records

    @staticmethod
    def _parse_probe(probe) -> Optional[ContainerProbeConfig]:
        if probe is None:
            return None

        probe_type = ""
        path = ""
        port = 0

        if probe.http_get:
            probe_type = "httpGet"
            path = probe.http_get.path or ""
            port = probe.http_get.port
        elif probe.tcp_socket:
            probe_type = "tcpSocket"
            port = probe.tcp_socket.port
        elif probe._exec:
            probe_type = "exec"
        elif probe.grpc:
            probe_type = "grpc"
            port = probe.grpc.port

        # port 可能是字符串（如 'http-port'）或整数，统一转为字符串
        port_str = str(port) if port is not None else ""

        return ContainerProbeConfig(
            probe_type=probe_type,
            path=path,
            port=port_str,
            initial_delay_seconds=probe.initial_delay_seconds or 0,
            period_seconds=probe.period_seconds or 10,
            timeout_seconds=probe.timeout_seconds or 1,
            success_threshold=probe.success_threshold or 1,
            failure_threshold=probe.failure_threshold or 3,
        )

    def _parse_cronjob(self, cj) -> K8sCronJobRecord:
        return K8sCronJobRecord(
            namespace=cj.metadata.namespace,
            name=cj.metadata.name,
            schedule=cj.spec.schedule or "",
            suspend=cj.spec.suspend or False,
            concurrency_policy=cj.spec.concurrency_policy or "Allow",
            successful_job_history_limit=(
                cj.spec.successful_jobs_history_limit
                if cj.spec.successful_jobs_history_limit is not None
                else 3
            ),
            failed_job_history_limit=(
                cj.spec.failed_jobs_history_limit
                if cj.spec.failed_jobs_history_limit is not None
                else 1
            ),
            last_schedule_time=cj.status.last_schedule_time if cj.status else None,
            last_successful_time=(
                cj.status.last_successful_time if cj.status else None
            ),
        )

    def _parse_service(self, svc) -> K8sServiceRecord:
        ports = []
        if svc.spec.ports:
            for p in svc.spec.ports:
                port_info = {
                    "port": p.port,
                    "protocol": p.protocol or "TCP",
                }
                if p.target_port is not None:
                    port_info["target_port"] = p.target_port
                if p.node_port is not None:
                    port_info["node_port"] = p.node_port
                if p.name:
                    port_info["name"] = p.name
                ports.append(port_info)

        # 解析 external_ips (K8s Python 客户端中 externalIPs 映射为 external_i_ps)
        external_ips = []
        if svc.spec.external_i_ps:
            external_ips = list(svc.spec.external_i_ps)
        if svc.status and svc.status.load_balancer and svc.status.load_balancer.ingress:
            for lb_ing in svc.status.load_balancer.ingress:
                if lb_ing.ip:
                    external_ips.append(lb_ing.ip)
                elif lb_ing.hostname:
                    external_ips.append(lb_ing.hostname)

        return K8sServiceRecord(
            namespace=svc.metadata.namespace,
            name=svc.metadata.name,
            type=svc.spec.type,
            cluster_ip=svc.spec.cluster_ip or "",
            external_ips=external_ips,
            ports=ports,
            selector=dict(svc.spec.selector) if svc.spec.selector else {},
        )

    def _parse_ingress(self, ing) -> K8sIngressRecord:
        rules = []
        if ing.spec.rules:
            for rule in ing.spec.rules:
                rule_info = {"host": rule.host or ""}
                paths = []
                if rule.http and rule.http.paths:
                    for path in rule.http.paths:
                        path_info = {
                            "path": path.path or "/",
                            "path_type": path.path_type or "Prefix",
                        }
                        if path.backend:
                            if path.backend.service:
                                path_info["service_name"] = (
                                    path.backend.service.name or ""
                                )
                                if path.backend.service.port:
                                    if path.backend.service.port.number:
                                        path_info["service_port"] = (
                                            path.backend.service.port.number
                                        )
                                    elif path.backend.service.port.name:
                                        path_info["service_port"] = (
                                            path.backend.service.port.name
                                        )
                        paths.append(path_info)
                rule_info["paths"] = paths
                rules.append(rule_info)

        # 解析 tls
        tls = []
        tls_enabled = False
        if ing.spec.tls:
            tls_enabled = True
            for t in ing.spec.tls:
                tls_info = {
                    "hosts": list(t.hosts) if t.hosts else [],
                    "secret_name": t.secret_name or "",
                }
                tls.append(tls_info)

        # 解析 ingress_class
        ingress_class = ""
        if ing.spec.ingress_class_name:
            ingress_class = ing.spec.ingress_class_name
        annotations = dict(ing.metadata.annotations) if ing.metadata.annotations else {}
        if not ingress_class:
            ingress_class = annotations.get("kubernetes.io/ingress.class", "")

        return K8sIngressRecord(
            namespace=ing.metadata.namespace,
            name=ing.metadata.name,
            rules=rules,
            tls=tls,
            ingress_class=ingress_class,
            tls_enabled=tls_enabled,
            annotations=annotations,
        )

    def _parse_network_policy(self, np_obj) -> K8sNetworkPolicyRecord:
        pod_selector = {}
        if np_obj.spec.pod_selector:
            if np_obj.spec.pod_selector.match_labels:
                pod_selector["matchLabels"] = dict(
                    np_obj.spec.pod_selector.match_labels
                )
            if np_obj.spec.pod_selector.match_expressions:
                pod_selector["matchExpressions"] = [
                    {
                        "key": expr.key,
                        "operator": expr.operator,
                        "values": list(expr.values) if expr.values else [],
                    }
                    for expr in np_obj.spec.pod_selector.match_expressions
                ]

        # 解析 policy_types
        policy_types = (
            list(np_obj.spec.policy_types) if np_obj.spec.policy_types else []
        )

        # 解析 ingress_rules
        ingress_rules = []
        if np_obj.spec.ingress:
            for rule in np_obj.spec.ingress:
                rule_info = {}
                if rule._from:
                    rule_info["from"] = self._parse_np_peers(rule._from)
                if rule.ports:
                    rule_info["ports"] = [
                        {"port": p.port, "protocol": p.protocol or "TCP"}
                        for p in rule.ports
                    ]
                ingress_rules.append(rule_info)

        # 解析 egress_rules
        egress_rules = []
        if np_obj.spec.egress:
            for rule in np_obj.spec.egress:
                rule_info = {}
                if rule.to:
                    rule_info["to"] = self._parse_np_peers(rule.to)
                if rule.ports:
                    rule_info["ports"] = [
                        {"port": p.port, "protocol": p.protocol or "TCP"}
                        for p in rule.ports
                    ]
                egress_rules.append(rule_info)

        return K8sNetworkPolicyRecord(
            namespace=np_obj.metadata.namespace,
            name=np_obj.metadata.name,
            pod_selector=pod_selector,
            policy_types=policy_types,
            ingress_rules=ingress_rules,
            egress_rules=egress_rules,
        )

    @staticmethod
    def _parse_np_peers(peers) -> list:
        result = []
        for peer in peers:
            peer_info = {}
            if peer.pod_selector:
                sel = {}
                if peer.pod_selector.match_labels:
                    sel["matchLabels"] = dict(peer.pod_selector.match_labels)
                peer_info["podSelector"] = sel
            if peer.namespace_selector:
                sel = {}
                if peer.namespace_selector.match_labels:
                    sel["matchLabels"] = dict(peer.namespace_selector.match_labels)
                peer_info["namespaceSelector"] = sel
            if peer.ip_block:
                ip_info = {"cidr": peer.ip_block.cidr or ""}
                if peer.ip_block._except:
                    ip_info["except"] = list(peer.ip_block._except)
                peer_info["ipBlock"] = ip_info
            result.append(peer_info)
        return result

    def _parse_event(self, event) -> K8sEventRecord:
        involved_object = {}
        if event.involved_object:
            obj = event.involved_object
            involved_object = {
                "kind": obj.kind or "",
                "name": obj.name or "",
                "namespace": obj.namespace or "",
            }
            if obj.uid:
                involved_object["uid"] = obj.uid

        # 解析 source
        source = {}
        if event.source:
            if event.source.component:
                source["component"] = event.source.component
            if event.source.host:
                source["host"] = event.source.host

        return K8sEventRecord(
            namespace=event.metadata.namespace,
            name=event.metadata.name,
            reason=event.reason or "",
            message=event.message or "",
            type=event.type or "Normal",
            count=event.count or 1,
            first_timestamp=event.first_timestamp,
            last_timestamp=event.last_timestamp,
            involved_object=involved_object,
            source=source,
        )

    def _parse_hpa(self, hpa) -> K8sHpaRecord:
        # 解析 scaleTargetRef
        target_kind = ""
        target_name = ""
        if hpa.spec.scale_target_ref:
            target_kind = hpa.spec.scale_target_ref.kind or ""
            target_name = hpa.spec.scale_target_ref.name or ""

        # 解析 metrics
        metrics = []

        if hpa.spec.metrics:
            for m in hpa.spec.metrics:
                hpa_metric = self._parse_hpa_metric(m)
                if not hpa_metric:
                    continue
                metrics.append(hpa_metric)

        return K8sHpaRecord(
            namespace=hpa.metadata.namespace,
            name=hpa.metadata.name,
            min_replicas=hpa.spec.min_replicas or 1,
            max_replicas=hpa.spec.max_replicas or 0,
            current_replicas=hpa.status.current_replicas if hpa.status else 0,
            target_kind=target_kind,
            target_name=target_name,
            metrics=metrics,
        )

    def _parse_hpa_metric(self, m) -> Optional[HpaMetric]:
        metric_type = m.type  # Resource/Pods/Object/External

        if metric_type == "Resource" and m.resource:
            target = self._parse_metric_target(m.resource.target)
            return HpaMetric(
                type="Resource",
                target=target,
                resource_name=m.resource.name or "",
            )
        elif metric_type == "Pods" and m.pods:
            target = self._parse_metric_target(m.pods.target)
            return HpaMetric(
                type="Pods",
                target=target,
                pods_metric=self._parse_metric_identifier(m.pods.metric),
            )
        elif metric_type == "Object" and m.object:
            target = self._parse_metric_target(m.object.target)
            obj_ref = None
            if m.object.described_object:
                obj_ref = ObjectReference(
                    kind=m.object.described_object.kind or "",
                    name=m.object.described_object.name or "",
                    api_version=m.object.described_object.api_version,
                )
            return HpaMetric(
                type="Object",
                target=target,
                object_metric=self._parse_metric_identifier(m.object.metric),
                object_target=obj_ref,
            )
        elif metric_type == "External" and m.external:
            target = self._parse_metric_target(m.external.target)
            return HpaMetric(
                type="External",
                target=target,
                external_metric=self._parse_metric_identifier(m.external.metric),
            )
        else:
            return None

    @staticmethod
    def _parse_metric_target(target) -> MetricTarget:
        """
        解析 MetricTarget

        Args:
            target: K8s MetricTarget 对象

        Returns:
            MetricTarget: 解析后的指标目标
        """
        target_type = target.type or "Utilization"
        value = None
        average_value = None

        if target_type == "Utilization":
            value = target.average_utilization
        elif target_type == "AverageValue":
            # average_value 可能是字符串如 "100m"，简化处理
            raw = target.average_value
            if raw is not None:
                try:
                    average_value = float(raw)
                except (ValueError, TypeError):
                    average_value = None
                    value = str(raw)
        elif target_type == "Value":
            raw = target.value
            if raw is not None:
                try:
                    value = int(raw)
                except (ValueError, TypeError):
                    value = str(raw)

        return MetricTarget(
            type=target_type,
            value=value,
            average_value=average_value,
        )

    @staticmethod
    def _parse_metric_identifier(metric) -> Optional[MetricIdentifier]:
        if metric is None:
            return None

        selector = None
        if metric.selector:
            match_labels = (
                dict(metric.selector.match_labels)
                if metric.selector.match_labels
                else None
            )
            match_expressions = None
            if metric.selector.match_expressions:
                match_expressions = [
                    {
                        "key": expr.key,
                        "operator": expr.operator,
                        "values": list(expr.values) if expr.values else [],
                    }
                    for expr in metric.selector.match_expressions
                ]
            selector = LabelSelector(
                match_labels=match_labels,
                match_expressions=match_expressions,
            )

        return MetricIdentifier(
            name=metric.name or "",
            selector=selector,
        )

    def _parse_namespace(self, ns_obj) -> K8sNamespaceRecord:
        status = "Active"
        if ns_obj.status and ns_obj.status.phase:
            status = ns_obj.status.phase

        return K8sNamespaceRecord(
            name=ns_obj.metadata.name,
            status=status,
            labels=dict(ns_obj.metadata.labels) if ns_obj.metadata.labels else {},
            annotations=(
                dict(ns_obj.metadata.annotations) if ns_obj.metadata.annotations else {}
            ),
            creation_timestamp=ns_obj.metadata.creation_timestamp,
        )

    def _parse_node_via_k8s(self, node) -> K8sNodeRecord:
        # 解析状态
        status = "Unknown"
        if node.status and node.status.conditions:
            for cond in node.status.conditions:
                if cond.type == "Ready":
                    status = "Ready" if cond.status == "True" else "NotReady"
                    break

        # 解析 capacity / allocatable
        capacity = {}
        allocatable = {}
        if node.status:
            if node.status.capacity:
                capacity = dict(node.status.capacity)
            if node.status.allocatable:
                allocatable = dict(node.status.allocatable)

        # 解析 labels
        labels = dict(node.metadata.labels) if node.metadata.labels else {}

        # 解析 taints
        taints = []
        if node.spec.taints:
            for t in node.spec.taints:
                taint_info = {
                    "key": t.key or "",
                    "effect": t.effect or "",
                }
                if t.value:
                    taint_info["value"] = t.value
                taints.append(taint_info)

        # 从 labels 提取常用信息
        zone = labels.get(
            "topology.kubernetes.io/zone",
            labels.get("failure-domain.beta.kubernetes.io/zone", ""),
        )
        region = labels.get(
            "topology.kubernetes.io/region",
            labels.get("failure-domain.beta.kubernetes.io/region", ""),
        )
        instance_type = labels.get(
            "node.kubernetes.io/instance-type",
            labels.get("beta.kubernetes.io/instance-type", ""),
        )

        return K8sNodeRecord(
            name=node.metadata.name,
            status=status,
            capacity=capacity,
            allocatable=allocatable,
            labels=labels,
            annotations=(
                dict(node.metadata.annotations) if node.metadata.annotations else {}
            ),
            taints=taints,
            zone=zone,
            region=region,
            instance_type=instance_type,
        )

    def _parse_resource_quota(self, rq) -> K8sResourceQuotaRecord:
        hard = {}
        used = {}
        if rq.status:
            if rq.status.hard:
                hard = dict(rq.status.hard)
            if rq.status.used:
                used = dict(rq.status.used)

        return K8sResourceQuotaRecord(
            namespace=rq.metadata.namespace,
            name=rq.metadata.name,
            hard=hard,
            used=used,
        )

    def _parse_pv(self, pv) -> K8sPvRecord:
        # 解析 capacity
        capacity = ""
        if pv.spec.capacity:
            capacity = pv.spec.capacity.get("storage", "")

        return K8sPvRecord(
            name=pv.metadata.name,
            capacity=capacity,
            access_modes=list(pv.spec.access_modes) if pv.spec.access_modes else [],
            reclaim_policy=pv.spec.persistent_volume_reclaim_policy or "",
            status=pv.status.phase if pv.status else "",
            storage_class=pv.spec.storage_class_name or "",
        )

    def _parse_ahpa(self, ahpa: dict) -> K8sAhpaMetricsRecord:
        metadata = ahpa.get("metadata", {})
        spec = ahpa.get("spec", {})

        # 解析预测配置
        prediction = spec.get("prediction", {})
        prediction_enabled = False
        prediction_config = {}
        if prediction:
            prediction_enabled = prediction.get("enabled", False)
            prediction_config = {k: v for k, v in prediction.items() if k != "enabled"}

        # 解析模式
        mode = spec.get("mode", "Active")

        return K8sAhpaMetricsRecord(
            namespace=metadata.get("namespace", ""),
            name=metadata.get("name", ""),
            prediction_enabled=prediction_enabled,
            prediction_config=prediction_config,
            mode=mode,
        )

    def _parse_vpa(self, vpa: dict) -> K8sVpaRecord:
        metadata = vpa.get("metadata", {})
        spec = vpa.get("spec", {})
        status = vpa.get("status", {})

        # 解析 targetRef
        target_ref = spec.get("targetRef", {})
        target_kind = target_ref.get("kind", "")
        target_name = target_ref.get("name", "")

        # 解析 updatePolicy
        update_policy = spec.get("updatePolicy", {})
        update_mode = update_policy.get("updateMode", "Auto")

        # 解析保护性配置
        # minReplicas: 在 Recreate 模式下，确保至少保留的副本数
        min_replicas = update_policy.get("minReplicas")

        # 解析 resourcePolicy -> containerPolicies -> controlledResources
        controlled_resources = []
        resource_policy = spec.get("resourcePolicy", {})
        container_policies = resource_policy.get("containerPolicies", [])
        if container_policies:
            # 取第一个策略的 controlledResources（通常只有一个 * 策略）
            first_policy = container_policies[0]
            controlled_resources = first_policy.get("controlledResources", [])

        # 解析 recommendation
        recommendation = {}
        if status.get("recommendation"):
            rec = status["recommendation"]
            container_recs = rec.get("containerRecommendations", [])
            recommendation = {
                "containerRecommendations": [
                    {
                        "containerName": cr.get("containerName", ""),
                        "lowerBound": cr.get("lowerBound", {}),
                        "target": cr.get("target", {}),
                        "upperBound": cr.get("upperBound", {}),
                        "uncappedTarget": cr.get("uncappedTarget", {}),
                    }
                    for cr in container_recs
                ]
            }

        return K8sVpaRecord(
            namespace=metadata.get("namespace", ""),
            name=metadata.get("name", ""),
            target_kind=target_kind,
            target_name=target_name,
            update_mode=update_mode,
            controlled_resources=controlled_resources,
            recommendation=recommendation,
            min_replicas=min_replicas,
        )

    @staticmethod
    def _parse_destination_rule(dr: dict) -> IstioDestinationRuleRecord:
        metadata = dr.get("metadata", {})
        spec = dr.get("spec", {})

        # 解析 host
        host = spec.get("host", "")

        # 解析 traffic_policy
        traffic_policy = spec.get("trafficPolicy", {})

        # 解析 subsets
        subsets = spec.get("subsets", [])

        return IstioDestinationRuleRecord(
            namespace=metadata.get("namespace", ""),
            name=metadata.get("name", ""),
            host=host,
            traffic_policy=traffic_policy,
            subsets=subsets,
        )

    @staticmethod
    def _parse_virtual_service(vs: dict) -> IstioVirtualServiceRecord:
        metadata = vs.get("metadata", {})
        spec = vs.get("spec", {})

        # 解析 hosts
        hosts = spec.get("hosts", [])

        # 解析 gateways
        gateways = spec.get("gateways", [])

        # 解析 http 路由
        http_routes = []
        for route in spec.get("http", []):
            route_info = {
                "name": route.get("name", ""),
                "match": route.get("match", []),
                "route": route.get("route", []),
                "redirect": route.get("redirect", {}),
                "rewrite": route.get("rewrite", {}),
                "retries": route.get("retries", {}),
                "fault": route.get("fault", {}),
                "mirror": route.get("mirror", {}),
                "timeout": route.get("timeout", ""),
            }
            http_routes.append(route_info)

        # 解析 tcp 路由
        tcp_routes = []
        for route in spec.get("tcp", []):
            route_info = {
                "match": route.get("match", []),
                "route": route.get("route", []),
            }
            tcp_routes.append(route_info)

        return IstioVirtualServiceRecord(
            namespace=metadata.get("namespace", ""),
            name=metadata.get("name", ""),
            hosts=hosts,
            gateways=gateways,
            http_routes=http_routes,
            tcp_routes=tcp_routes,
        )

    @staticmethod
    def _parse_argocd_application(app: dict) -> ArgoCdApplicationRecord:
        metadata = app.get("metadata", {})
        spec = app.get("spec", {})
        status = app.get("status", {})

        # 解析 source
        source = spec.get("source", {})
        repo_url = source.get("repoURL", "")
        target_revision = source.get("targetRevision", "HEAD")
        path = source.get("path", "")

        # 解析 destination
        destination = spec.get("destination", {})
        destination_server = destination.get("server", "")
        destination_namespace = destination.get("namespace", "")

        # 解析 syncPolicy
        sync_policy = spec.get("syncPolicy", {})
        auto_sync_enabled = sync_policy.get("automated") is not None
        auto_prune_enabled = False
        self_heal_enabled = False
        if auto_sync_enabled:
            automated = sync_policy.get("automated", {})
            auto_prune_enabled = automated.get("prune", False)
            self_heal_enabled = automated.get("selfHeal", False)

        # 解析 status
        sync_status = ""
        health_status = ""
        if status:
            sync_result = status.get("sync", {})
            sync_status = sync_result.get("status", "Unknown")
            health_result = status.get("health", {})
            health_status = health_result.get("status", "Unknown")

        return ArgoCdApplicationRecord(
            name=metadata.get("name", ""),
            namespace=metadata.get("namespace", "argocd"),
            repo_url=repo_url,
            target_revision=target_revision,
            path=path,
            destination_server=destination_server,
            destination_namespace=destination_namespace,
            sync_status=sync_status,
            health_status=health_status,
            sync_policy=sync_policy,
            auto_sync=auto_sync_enabled,
            auto_sync_enabled=auto_sync_enabled,
            auto_prune_enabled=auto_prune_enabled,
            self_heal_enabled=self_heal_enabled,
        )

    @staticmethod
    def _parse_chaos_experiment(chaos_obj: dict, chaos_type: str) -> ChaosExperimentRecord:
        """解析 Chaos Mesh 混沌实验"""
        metadata = chaos_obj.get("metadata", {})
        spec = chaos_obj.get("spec", {})
        status = chaos_obj.get("status", {})

        # 将 plural 形式转换为 CamelCase 类型名
        type_mapping = {
            "podchaos": "PodChaos",
            "networkchaos": "NetworkChaos",
            "iochaos": "IOChaos",
            "stresschaos": "StressChaos",
            "timechaos": "TimeChaos",
            "kernelchaos": "KernelChaos",
            "dnschaos": "DNSChaos",
            "httpchaos": "HTTPChaos",
        }
        experiment_type = type_mapping.get(chaos_type, "PodChaos")

        # 解析 selector (target_selector)
        selector = spec.get("selector", {})
        target_selector = {}
        if selector:
            target_selector = {
                "namespaces": selector.get("namespaces", []),
                "labelSelectors": selector.get("labelSelectors", {}),
                "expressionSelectors": selector.get("expressionSelectors", []),
            }

        # 解析 action
        action = spec.get("action", "")

        # 解析 duration
        duration = spec.get("duration", "")

        # 解析 schedule (如果有)
        schedule = spec.get("scheduler", {}).get("cron", "")

        # 解析 status
        experiment_status = status.get("experiment", {}).get("phase", "")
        if not experiment_status:
            # 兼容不同版本的 status 结构
            experiment_status = status.get("conditions", [{}])[-1].get("type", "") if status.get("conditions") else ""

        # 解析时间戳
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(metadata["creationTimestamp"].replace("Z", "+00:00"))

        last_run_time = None
        if status.get("experiment", {}).get("startTime"):
            last_run_time = datetime.fromisoformat(status["experiment"]["startTime"].replace("Z", "+00:00"))

        return ChaosExperimentRecord(
            experiment_id=metadata.get("uid", ""),
            experiment_name=metadata.get("name", ""),
            experiment_type=experiment_type,
            namespace=metadata.get("namespace", ""),
            target_selector=target_selector,
            action=action,
            duration=duration,
            schedule=schedule,
            status=experiment_status,
            create_time=create_time,
            last_run_time=last_run_time,
        )

    @staticmethod
    def _parse_chaos_schedule(schedule_obj: dict) -> ChaosScheduleRecord:
        """解析 Chaos Mesh 调度记录"""
        metadata = schedule_obj.get("metadata", {})
        spec = schedule_obj.get("spec", {})
        status = schedule_obj.get("status", {})

        # 解析 schedule 类型和 cron 表达式
        schedule_type = spec.get("type", "Cron")
        cron_expression = spec.get("schedule", "")

        # 解析关联的实验
        experiments = []
        if spec.get("type") in ["PodChaos", "NetworkChaos", "IOChaos", "StressChaos", 
                                "TimeChaos", "KernelChaos", "DNSChaos", "HTTPChaos"]:
            experiments.append({
                "type": spec.get("type", ""),
                "spec": spec.get(spec.get("type", "").lower(), {}),
            })

        # 解析是否启用
        enabled = not spec.get("paused", False)

        # 解析创建时间
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(metadata["creationTimestamp"].replace("Z", "+00:00"))

        return ChaosScheduleRecord(
            schedule_id=metadata.get("uid", ""),
            schedule_name=metadata.get("name", ""),
            namespace=metadata.get("namespace", ""),
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            experiments=experiments,
            enabled=enabled,
            create_time=create_time,
        )

    @staticmethod
    def _parse_chaos_workflow(workflow_obj: dict) -> ChaosWorkflowRecord:
        """解析 Chaos Mesh 工作流"""
        metadata = workflow_obj.get("metadata", {})
        spec = workflow_obj.get("spec", {})
        status = workflow_obj.get("status", {})

        # 解析 entry 节点
        entry = spec.get("entry", "")

        # 解析 templates
        templates = spec.get("templates", [])

        # 解析 status
        workflow_status = status.get("phase", "")
        if not workflow_status:
            workflow_status = status.get("conditions", [{}])[-1].get("type", "") if status.get("conditions") else ""

        # 解析时间戳
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(metadata["creationTimestamp"].replace("Z", "+00:00"))

        last_run_time = None
        if status.get("startTime"):
            last_run_time = datetime.fromisoformat(status["startTime"].replace("Z", "+00:00"))

        return ChaosWorkflowRecord(
            workflow_id=metadata.get("uid", ""),
            workflow_name=metadata.get("name", ""),
            namespace=metadata.get("namespace", ""),
            entry=entry,
            templates=templates,
            status=workflow_status,
            create_time=create_time,
            last_run_time=last_run_time,
        )

    @staticmethod
    def _parse_chaos_experiment_runs(chaos_obj: dict) -> list[ChaosExperimentRunRecord]:
        """
        从混沌实验对象的 status 中提取执行记录
        
        Chaos Mesh 会在实验对象的 status 中记录执行历史和当前状态
        """
        metadata = chaos_obj.get("metadata", {})
        status = chaos_obj.get("status", {})
        
        runs = []
        experiment_id = metadata.get("uid", "")
        
        # 提取当前执行状态（如果正在运行）
        experiment_status = status.get("experiment", {})
        if experiment_status:
            phase = experiment_status.get("phase", "")
            
            # 如果有当前执行状态，创建一个执行记录
            if phase:
                start_time = None
                if experiment_status.get("startTime"):
                    start_time = datetime.fromisoformat(
                        experiment_status["startTime"].replace("Z", "+00:00")
                    )
                
                end_time = None
                if experiment_status.get("endTime"):
                    end_time = datetime.fromisoformat(
                        experiment_status["endTime"].replace("Z", "+00:00")
                    )
                
                # 提取受影响的 Pods
                affected_pods = []
                records = experiment_status.get("records", [])
                for record in records:
                    pod_name = record.get("id", "")
                    if pod_name:
                        affected_pods.append(pod_name)
                
                # 构建事件列表
                events = []
                conditions = status.get("conditions", [])
                for condition in conditions:
                    events.append({
                        "type": condition.get("type", ""),
                        "status": condition.get("status", ""),
                        "reason": condition.get("reason", ""),
                        "message": condition.get("message", ""),
                        "time": condition.get("lastTransitionTime", ""),
                    })
                
                # 生成 run_id (使用实验ID + 时间戳)
                run_id = f"{experiment_id}-{start_time.timestamp() if start_time else 'current'}"
                
                # 状态映射
                status_mapping = {
                    "Running": "Running",
                    "Paused": "Paused",
                    "Failed": "Failed",
                    "Finished": "Finished",
                }
                run_status = status_mapping.get(phase, phase)
                
                # 生成结果摘要
                result_summary = ""
                if run_status == "Finished":
                    result_summary = f"实验成功完成，影响了 {len(affected_pods)} 个 Pod"
                elif run_status == "Failed":
                    result_summary = f"实验失败，影响了 {len(affected_pods)} 个 Pod"
                elif run_status == "Running":
                    result_summary = f"实验正在执行中，当前影响 {len(affected_pods)} 个 Pod"
                
                run_record = ChaosExperimentRunRecord(
                    experiment_id=experiment_id,
                    run_id=run_id,
                    status=run_status,
                    start_time=start_time,
                    end_time=end_time,
                    affected_pods=affected_pods,
                    events=events,
                    result_summary=result_summary,
                )
                runs.append(run_record)
        
        # Note: Chaos Mesh 不会在 CRD 中保留完整的历史执行记录
        # 完整的历史记录需要：
        # 1. 查询 Kubernetes Events (已有的 Event 收集会包含部分信息)
        # 2. 或者通过 Chaos Dashboard API 获取
        # 3. 或者从监控/日志系统中聚合
        
        return runs

    @staticmethod
    def _parse_kyverno_policy(policy_obj: dict, is_cluster_policy: bool) -> KyvernoPolicyRecord:
        """解析 Kyverno Policy 或 ClusterPolicy"""
        metadata = policy_obj.get("metadata", {})
        spec = policy_obj.get("spec", {})
        status = policy_obj.get("status", {})

        # 解析基本信息
        name = metadata.get("name", "")
        namespace = metadata.get("namespace", "") if not is_cluster_policy else ""
        policy_type = "ClusterPolicy" if is_cluster_policy else "Policy"

        # 解析运行模式
        background = spec.get("background", True)

        # 解析失败动作
        validation_failure_action = spec.get("validationFailureAction", "Audit")

        # 解析规则列表
        rules = []
        for rule in spec.get("rules", []):
            rule_info = {
                "name": rule.get("name", ""),
                "match": rule.get("match", {}),
                "exclude": rule.get("exclude", {}),
            }
            # 规则类型：validation/mutation/generation
            if rule.get("validate"):
                rule_info["type"] = "validation"
                rule_info["validate"] = rule.get("validate")
            elif rule.get("mutate"):
                rule_info["type"] = "mutation"
            elif rule.get("generate"):
                rule_info["type"] = "generation"
            rules.append(rule_info)

        # 解析状态
        policy_status = ""
        ready = False
        if status:
            ready = status.get("ready", False)
            policy_status = "Ready" if ready else "Not Ready"

        # 解析违规计数（从 status 中获取）
        violations_count = 0
        if status.get("rulecount", {}).get("validate"):
            # 某些版本的 Kyverno 会在 status 中记录违规统计
            violations_count = status.get("rulecount", {}).get("fail", 0)

        # 解析创建时间
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(
                metadata["creationTimestamp"].replace("Z", "+00:00")
            )

        return KyvernoPolicyRecord(
            name=name,
            policy_type=policy_type,
            namespace=namespace,
            background=background,
            validation_failure_action=validation_failure_action,
            rules=rules,
            status=policy_status,
            violations_count=violations_count,
            create_time=create_time,
        )

    @staticmethod
    def _parse_kyverno_policy_violations(report_obj: dict) -> list[KyvernoPolicyViolationRecord]:
        """从 Kyverno PolicyReport 中提取违规记录"""
        metadata = report_obj.get("metadata", {})
        results = report_obj.get("results", [])

        violations = []
        for result in results:
            # 只记录失败的结果（违规）
            if result.get("result") not in ["fail", "error"]:
                continue

            # 解析资源信息
            resources = result.get("resources", [])
            for resource in resources:
                # 解析时间戳
                timestamp = None
                if result.get("timestamp"):
                    try:
                        timestamp = datetime.fromisoformat(
                            result["timestamp"].replace("Z", "+00:00")
                        )
                    except:
                        pass

                violation = KyvernoPolicyViolationRecord(
                    policy_name=result.get("policy", ""),
                    rule_name=result.get("rule", ""),
                    resource_kind=resource.get("kind", ""),
                    resource_namespace=resource.get("namespace", ""),
                    resource_name=resource.get("name", ""),
                    message=result.get("message", ""),
                    action=result.get("result", "").upper(),  # FAIL/ERROR -> Blocked
                    timestamp=timestamp,
                )
                violations.append(violation)

        return violations

    @staticmethod
    def _parse_opa_constraint_template(template_obj: dict) -> OpaConstraintTemplateRecord:
        """解析 OPA Gatekeeper ConstraintTemplate"""
        metadata = template_obj.get("metadata", {})
        spec = template_obj.get("spec", {})
        status = template_obj.get("status", {})

        # 解析基本信息
        name = metadata.get("name", "")

        # 解析 CRD 定义
        crd = spec.get("crd", {})
        crd_spec = crd.get("spec", {})
        crd_names = crd_spec.get("names", {})
        crd_kind = crd_names.get("kind", "")

        # 解析 Rego 代码
        rego_code = ""
        targets = spec.get("targets", [])
        if targets:
            # 通常只有一个 target (admission.k8s.gatekeeper.sh)
            first_target = targets[0]
            rego = first_target.get("rego", "")
            rego_code = rego

        # 解析状态
        template_status = ""
        if status:
            created = status.get("created", False)
            template_status = "Ready" if created else "Not Ready"

        # 解析创建时间
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(
                metadata["creationTimestamp"].replace("Z", "+00:00")
            )

        return OpaConstraintTemplateRecord(
            name=name,
            crd_kind=crd_kind,
            rego_code=rego_code,
            targets=targets,
            status=template_status,
            create_time=create_time,
        )

    @staticmethod
    def _parse_opa_constraint(constraint_obj: dict, constraint_kind: str) -> OpaConstraintRecord:
        """解析 OPA Gatekeeper Constraint"""
        metadata = constraint_obj.get("metadata", {})
        spec = constraint_obj.get("spec", {})
        status = constraint_obj.get("status", {})

        # 解析基本信息
        name = metadata.get("name", "")

        # 解析执行动作
        enforcement_action = spec.get("enforcementAction", "deny")

        # 解析匹配规则
        match = spec.get("match", {})

        # 解析参数
        parameters = spec.get("parameters", {})

        # 解析违规计数
        violations_count = 0
        if status.get("violations"):
            violations_count = len(status.get("violations", []))
        elif status.get("totalViolations"):
            violations_count = status.get("totalViolations", 0)

        # 解析状态
        constraint_status = ""
        if status:
            # 检查是否有 byPod 状态（表示已同步）
            by_pod = status.get("byPod", [])
            if by_pod:
                constraint_status = "Synced"
            else:
                constraint_status = "NotSynced"

        # 解析创建时间
        create_time = None
        if metadata.get("creationTimestamp"):
            create_time = datetime.fromisoformat(
                metadata["creationTimestamp"].replace("Z", "+00:00")
            )

        return OpaConstraintRecord(
            name=name,
            constraint_kind=constraint_kind,
            enforcement_action=enforcement_action,
            match=match,
            parameters=parameters,
            violations_count=violations_count,
            status=constraint_status,
            create_time=create_time,
        )

    @staticmethod
    def _parse_opa_violations(constraint_obj: dict, constraint_kind: str) -> list[OpaViolationRecord]:
        """从 OPA Gatekeeper Constraint 的 status 中提取违规记录"""
        metadata = constraint_obj.get("metadata", {})
        spec = constraint_obj.get("spec", {})
        status = constraint_obj.get("status", {})

        constraint_name = metadata.get("name", "")
        enforcement_action = spec.get("enforcementAction", "deny")

        violations = []
        violation_list = status.get("violations", [])

        for violation in violation_list:
            # 解析时间戳
            timestamp = None
            # OPA Gatekeeper 的违规记录通常没有时间戳，使用当前时间
            timestamp = datetime.now()

            violation_record = OpaViolationRecord(
                constraint_name=constraint_name,
                constraint_kind=constraint_kind,
                resource_kind=violation.get("kind", ""),
                resource_namespace=violation.get("namespace", ""),
                resource_name=violation.get("name", ""),
                message=violation.get("message", ""),
                enforcement_action=enforcement_action,
                timestamp=timestamp,
            )
            violations.append(violation_record)

        return violations

    @staticmethod
    def _parse_kyverno_policy_simplified(policy_obj: dict, is_cluster_policy: bool) -> K8sKyvernoPolicyRecord:
        """解析 Kyverno Policy 或 ClusterPolicy（简化版，用于 k8s schema）"""
        metadata = policy_obj.get("metadata", {})
        spec = policy_obj.get("spec", {})
        status = policy_obj.get("status", {})

        # 解析基本信息
        name = metadata.get("name", "")
        namespace = metadata.get("namespace", "") if not is_cluster_policy else ""
        policy_type = "ClusterPolicy" if is_cluster_policy else "Policy"

        # 解析运行模式
        background = spec.get("background", True)

        # 解析失败动作
        validation_failure_action = spec.get("validationFailureAction", "audit")

        # 解析规则列表（简化版，只保留基本信息）
        rules = []
        for rule in spec.get("rules", []):
            rule_info = {
                "name": rule.get("name", ""),
                "match": rule.get("match", {}),
            }
            rules.append(rule_info)

        # 解析状态
        ready = False
        message = ""
        if status:
            ready = status.get("ready", False)
            # 从 conditions 中提取消息
            conditions = status.get("conditions", [])
            if conditions:
                message = conditions[0].get("message", "")

        return K8sKyvernoPolicyRecord(
            namespace=namespace,
            name=name,
            policy_type=policy_type,
            validation_failure_action=validation_failure_action,
            background=background,
            rules=rules,
            ready=ready,
            message=message,
        )

    @staticmethod
    def _parse_opa_constraint_simplified(constraint_obj: dict, constraint_kind: str) -> K8sGatekeeperConstraintRecord:
        """解析 OPA Gatekeeper Constraint（简化版，用于 k8s schema）"""
        metadata = constraint_obj.get("metadata", {})
        spec = constraint_obj.get("spec", {})
        status = constraint_obj.get("status", {})

        # 解析基本信息
        name = metadata.get("name", "")
        # OPA Gatekeeper Constraint 通常是集群级别资源，但可能在某些命名空间中
        namespace = metadata.get("namespace", "")

        # 解析执行动作
        enforcement_action = spec.get("enforcementAction", "deny")

        # 解析匹配规则
        match = spec.get("match", {})

        # 解析参数
        parameters = spec.get("parameters", {})

        # 解析违规计数
        violations_count = 0
        if status.get("violations"):
            violations_count = len(status.get("violations", []))
        elif status.get("totalViolations"):
            violations_count = status.get("totalViolations", 0)

        # 解析状态
        constraint_status = ""
        if status:
            # 检查是否有 byPod 状态（表示已同步）
            by_pod = status.get("byPod", [])
            if by_pod:
                constraint_status = "Synced"
            else:
                constraint_status = "NotSynced"

        return K8sGatekeeperConstraintRecord(
            namespace=namespace,
            name=name,
            kind=constraint_kind,
            enforcement_action=enforcement_action,
            match=match,
            parameters=parameters,
            violations_count=violations_count,
            status=constraint_status,
        )
