"""
Automation 维度 - 基础设施即代码 (IaC) 分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)             | 分值 | 评分标准                                      |
| ------------------------ | ---- | --------------------------------------------- |
| provisioning_automation  | 5    | 使用工具 (如 Terraform/Pulumi) 自动创建云资源 |
| configuration_management | 5    | 使用工具 (如 Ansible/Salt) 自动配置 OS/中间件 |
| policy_as_code           | 5    | 基础设施合规性策略代码化 (如 OPA/Sentinel)    |
| drift_detection          | 5    | 能自动检测并告警实际环境与代码定义的偏差      |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.codeup import CodeupRepoFileTreeRecord
from ...schema.ros import RosStackRecord, RosStackDriftRecord
from ...schema.ecs import EcsInstanceRecord
from ...schema.rds_oss import RdsInstanceRecord, OssBucketRecord
from ...schema.k8s import K8sGatekeeperConstraintRecord, K8sKyvernoPolicyRecord
from ...schema.cms import CmsAlarmHistoryRecord
import datetime


class ProvisioningAutomationAnalyzer(Analyzer):
    """
    资源供给自动化分析器
    
    评估标准：使用工具 (如 Terraform/Pulumi) 自动创建云资源
    
    数据来源：
    - 各云资源产品 Tag API：检查 ECS、RDS、OSS 等资源的标签中是否存在 
      managedBy: terraform 或 CreatedBy: ROS 等 IaC 工具打上的标签
    - 资源编排 ROS：Stack 列表 API，检查是否有存活的 Stack 资源
    """

    def key(self) -> str:
        return "provisioning_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "基础设施即代码"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "ros.stack.list",
            "ecs.instance.list",
            "rds.instance.list",
            "oss.bucket.list"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []

        has_iac_infra = False
        active_stack_count = 0

        if store.available("ros.stack.list"):
            stacks: list[RosStackRecord] = store.get("ros.stack.list")
            active_statuses = {
                "CREATE_COMPLETE", "UPDATE_COMPLETE", "ROLLBACK_COMPLETE",
                "CREATE_ROLLBACK_COMPLETE", "IMPORT_CREATE_COMPLETE",
                "IMPORT_UPDATE_COMPLETE", "CHECK_COMPLETE", "REVIEW_COMPLETE",
                "DELETE_FAILED"
            }
            active_stacks = [s for s in stacks if s.status in active_statuses]
            active_stack_count = len(active_stacks)

            if active_stacks:
                has_iac_infra = True
                evidence.append(f"检测到 {active_stack_count} 个活跃的 ROS Stack")

        def is_tagged_as_iac(tags_dict):
            if not tags_dict:
                return False

            keys = []
            if isinstance(tags_dict, dict):
                keys = tags_dict.keys()
            elif isinstance(tags_dict, list):
                keys = [item.get('Key', '') for item in tags_dict if isinstance(item, dict)]

            iac_keys = ["managedby", "managed-by", "managed_by", "createdby", "created-by", "created_by"]
            for k in keys:
                if k.lower() in iac_keys:
                    return True
                val = ""
                if isinstance(tags_dict, dict): val = tags_dict.get(k, "")
                if val.lower() in ["terraform", "pulumi", "ros", "cloudformation"]:
                    return True
            return False

        total_resources = 0
        tagged_iac_count = 0

        def process_resources(resource_list, resource_type_name):
            nonlocal total_resources, tagged_iac_count
            if not resource_list:
                return

            count = len(resource_list)
            total_resources += count

            iac_items = [r for r in resource_list if is_tagged_as_iac(r.tags)]
            if iac_items:
                tagged_iac_count += len(iac_items)
                if not has_iac_infra:
                    evidence.append(f"{resource_type_name} 标签标识 IaC: {len(iac_items)}/{count}")

        if store.available("ecs.instance.list"):
            ecs_instances: list[EcsInstanceRecord] = store.get("ecs.instance.list")
            process_resources(ecs_instances, "ECS")
        if store.available("rds.instance.list"):
            rds_instances: list[RdsInstanceRecord] = store.get("rds.instance.list")
            process_resources(rds_instances, "RDS")
        if store.available("oss.bucket.list"):
            oss_instances: list[OssBucketRecord] = store.get("oss.bucket.list")
            process_resources(oss_instances, "OSS")

        if not has_iac_infra and tagged_iac_count == 0:
            return self._not_scored("未检测到使用 IaC 工具管理的云资源 (无 ROS Stack 且无资源标签)", evidence)

        if has_iac_infra:
            coverage = tagged_iac_count / total_resources if total_resources > 0 else 0

            if active_stack_count >= 3 and coverage >= 0.7:
                score = 5
                reason = "深度使用 ROS 资源编排服务管理基础设施 (多 Stack + 高覆盖率)"
            elif active_stack_count >= 2 or coverage >= 0.5:
                score = 4
                reason = "使用 ROS 资源编排服务管理基础设施 (架构层面已 IaC 化)"
            else:
                score = 3
                reason = "初步使用 ROS 资源编排服务管理基础设施"

            if total_resources > 0 and tagged_iac_count == 0:
                evidence.append("提示: 建议在具体资源上也添加标签以便细粒度识别")
            if coverage > 0:
                evidence.insert(0, f"IaC 标签覆盖率: {coverage * 100:.1f}%")
            return self._scored(score, reason, evidence)

        if total_resources == 0:
            return self._not_evaluated("未获取到任何云资源数据")

        coverage = tagged_iac_count / total_resources
        evidence.insert(0, f"IaC 标签覆盖率: {coverage * 100:.1f}%")

        if coverage >= 0.9:
            return self._scored(5, "绝大部分云资源通过标签标识为 IaC 管理", evidence)
        elif coverage >= 0.7:
            return self._scored(4, "大部分云资源通过标签标识为 IaC 管理", evidence)
        elif coverage >= 0.5:
            return self._scored(3, "半数以上云资源通过标签标识为 IaC 管理", evidence)
        elif coverage >= 0.3:
            return self._scored(2, "部分云资源通过标签标识为 IaC 管理", evidence)
        else:
            return self._scored(1, "仅少量云资源通过标签标识为 IaC 管理", evidence)


class ConfigurationManagementAnalyzer(Analyzer):
    """
    配置管理自动化分析器
    
    评估标准：使用工具 (如 Ansible/Salt) 自动配置 OS/中间件
    
    数据来源：
    - 云效 Codeup：仓库文件树 API，扫描是否存在 Ansible playbook（.yml）、
      Salt state（.sls）、Chef（.rb）、Puppet（.pp）等配置管理文件
    """

    def key(self) -> str:
        return "configuration_management"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "基础设施即代码"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["codeup.repo.file_tree"]

    def analyze(self, store) -> ScoreResult:
        file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

        if not file_tree:
            return self._not_evaluated("未获取到仓库文件树信息")

        config_mgmt_patterns = {
            "ansible": {
                "key_files": ["playbook.yml", "playbook.yaml", "site.yml", "site.yaml", "ansible.cfg"],
                "strong_dirs": ["roles", "playbooks", "group_vars", "host_vars", "collections"],
                "weak_dirs": ["ansible"],
                "extensions": []
            },
            "salt": {
                "key_files": ["top.sls", "minion", "master"],
                "strong_dirs": ["salt", "pillar", "states", "saltstack"],
                "weak_dirs": [],
                "extensions": [".sls"]
            },
            "chef": {
                "key_files": ["metadata.rb", "Berksfile", "Policyfile.rb", "knife.rb"],
                "strong_dirs": ["cookbooks", "recipes", "attributes", "chef"],
                "weak_dirs": [],
                "extensions": []
            },
            "puppet": {
                "key_files": ["Puppetfile", "environment.conf"],
                "strong_dirs": ["manifests", "modules", "puppet"],
                "weak_dirs": [],
                "extensions": [".pp"]
            }
        }

        found_tools = {}

        def has_dir_segment(file_path, dir_name):
            parts = file_path.replace('\\', '/').split('/')
            return dir_name in parts

        for file_record in file_tree:
            full_path = file_record.path
            full_path_lower = full_path.lower()
            file_name = file_record.name.lower()

            matched_tools = set()

            for tool, patterns in config_mgmt_patterns.items():
                score_added = 0

                if file_name in [f.lower() for f in patterns["key_files"]]:
                    score_added += 2
                    matched_tools.add(tool)

                for dir_name in patterns["strong_dirs"]:
                    if has_dir_segment(full_path_lower, dir_name):
                        score_added += 1
                        matched_tools.add(tool)
                        break

                for ext in patterns["extensions"]:
                    if file_name.endswith(ext):
                        if tool == "chef" and score_added == 0:
                            continue

                        if score_added == 0:
                            score_added += 0.5
                        matched_tools.add(tool)

                if score_added > 0:
                    found_tools[tool] = found_tools.get(tool, 0) + score_added

        evidence = []

        MAX_TOOL_WEIGHT = 3.0
        capped_tool_weights = {}
        for tool, weight in found_tools.items():
            capped_weight = min(weight, MAX_TOOL_WEIGHT)
            capped_tool_weights[tool] = capped_weight
            if weight > MAX_TOOL_WEIGHT:
                evidence.append(
                    f"{tool.capitalize()}: 检测到强相关特征 (权重 {weight:.1f}, 封顶 {MAX_TOOL_WEIGHT:.0f})")
            else:
                evidence.append(f"{tool.capitalize()}: 检测到强相关特征 (权重 {weight:.1f})")

        total_score_weight = sum(capped_tool_weights.values())
        tool_count = len(capped_tool_weights)

        if not found_tools:
            return self._not_scored(
                "未检测到配置管理工具特征",
                ["扫描了文件树", "未发现 Ansible, Salt, Chef, Puppet 的典型结构"]
            )

        if total_score_weight >= 4 or (total_score_weight >= 3 and tool_count >= 2):
            reason = "深度使用配置管理工具 (Ansible/Salt/Chef/Puppet) 自动化运维"
            if tool_count > 1:
                reason += f" (混合使用 {tool_count} 种工具)"
            return self._scored(5, reason, evidence)
        elif total_score_weight >= 3:
            return self._scored(4, "较深入使用配置管理工具进行自动化配置", evidence)
        elif total_score_weight >= 2:
            return self._scored(3, "使用配置管理工具进行部分自动化配置", evidence)
        elif total_score_weight >= 1:
            return self._scored(2, "初步使用配置管理工具，使用规模有限", evidence)
        else:
            return self._scored(1, "检测到配置管理工具痕迹，但使用非常有限", evidence)


class PolicyAsCodeAnalyzer(Analyzer):
    """
    策略即代码分析器
    
    评估标准：基础设施合规性策略代码化 (如 OPA/Sentinel)
    
    数据来源：
    - ACK API：检查集群中是否安装了 OPA Gatekeeper 或 Kyverno，
      以及是否存在 ClusterPolicy 资源
    - 云效 Flow：流水线执行日志，检查是否有因策略违规而被阻断的记录
    """

    def key(self) -> str:
        return "policy_as_code"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "基础设施即代码"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "k8s.gatekeeper.constraint.list",
            "k8s.kyverno.policy.list"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        has_policy_engine = False
        policy_count = 0
        enforced_count = 0
        audit_count = 0

        # 1. 检查 OPA Gatekeeper
        if store.available("k8s.gatekeeper.constraint.list"):
            constraints: list[K8sGatekeeperConstraintRecord] = store.get("k8s.gatekeeper.constraint.list")
            if constraints:
                has_policy_engine = True
                enforced = [c for c in constraints if c.enforcement_action == "deny"]
                audit = [c for c in constraints if c.enforcement_action in ["dryrun", "warn"]]
                policy_count += len(constraints)
                enforced_count += len(enforced)
                audit_count += len(audit)
                evidence.append(
                    f"OPA Gatekeeper: 总计 {len(constraints)}, 强制执行 {len(enforced)}, 审计/警告 {len(audit)}")

        # 2. 检查 Kyverno
        if store.available("k8s.kyverno.policy.list"):
            policies: list[K8sKyvernoPolicyRecord] = store.get("k8s.kyverno.policy.list")
            if policies:
                has_policy_engine = True
                enforced = [p for p in policies if p.validation_failure_action == "enforce"]
                audit = [p for p in policies if p.validation_failure_action == "audit"]
                policy_count += len(policies)
                enforced_count += len(enforced)
                audit_count += len(audit)
                evidence.append(f"Kyverno: 总计 {len(policies)}, 强制执行 {len(enforced)}, 审计 {len(audit)}")

        if not has_policy_engine:
            return self._not_evaluated("未获取到策略引擎 (OPA Gatekeeper/Kyverno) 数据")

        if policy_count == 0:
            return self._not_scored("策略引擎已安装，但未配置任何策略约束", evidence)

        enforcement_ratio = enforced_count / policy_count if policy_count > 0 else 0
        evidence.insert(0, f"策略强制执行率: {enforcement_ratio * 100:.1f}% ({enforced_count}/{policy_count})")

        if enforced_count >= 5 and enforcement_ratio >= 0.5:
            return self._scored(5, "基础设施合规性策略完善且主要处于强制执行模式", evidence)
        elif enforced_count >= 3 and enforcement_ratio >= 0.4:
            return self._scored(4, "基础设施合规性策略较完善，强制执行比例良好", evidence)
        elif enforced_count >= 2:
            if enforcement_ratio >= 0.3:
                return self._scored(4, "基础设施合规性策略已代码化并部分强制执行", evidence)
            else:
                return self._scored(3, "已实施策略即代码，但强制执行比例较低，风险敞口较大", evidence)
        elif enforced_count >= 1:
            return self._scored(2, "初步实施策略即代码，仅个别策略强制执行", evidence)
        elif policy_count >= 5:
            return self._scored(2, "已配置较多策略但均未强制执行 (全审计模式)", evidence)
        elif policy_count >= 2:
            return self._scored(1, "策略即代码实施有限，全审计模式", evidence)
        else:
            return self._scored(1, "策略即代码实施非常有限", evidence)


class DriftDetectionAnalyzer(Analyzer):
    """
    漂移检测分析器
    
    评估标准：能自动检测并告警实际环境与代码定义的偏差
    
    数据来源：
    - ROS：Stack Drift Detection API
    - 云监控 CMS：告警历史 API，搜索包含"基础设施漂移"关键词的告警记录
    """

    def key(self) -> str:
        return "drift_detection"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "基础设施即代码"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "ros.stack.drift",
            "cms.alarm.history"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        warnings = []

        has_detection_capability = False
        drift_found = False
        coverage_ratio = 0.0
        unknown_risk_count = 0

        ros_drifted_count = 0
        ros_total_count = 0
        ros_checked_count = 0

        if store.available("ros.stack.drift"):
            drift_records: list[RosStackDriftRecord] = store.get("ros.stack.drift")

            if drift_records:
                has_detection_capability = True
                ros_total_count = len(drift_records)

                in_sync = [d for d in drift_records if d.drift_status == "IN_SYNC"]
                drifted = [d for d in drift_records if d.drift_status == "DRIFTED"]
                not_checked = [d for d in drift_records if d.drift_status == "NOT_CHECKED"]
                failed_check = [d for d in drift_records if d.drift_status == "CHECK_FAILED"]

                ros_drifted_count = len(drifted)
                ros_checked_count = len(in_sync) + len(drifted)
                unknown_risk_count = len(not_checked) + len(failed_check)

                if ros_total_count > 0:
                    coverage_ratio = ros_checked_count / ros_total_count

                evidence.append(f"ROS Stack 总数: {ros_total_count}")
                evidence.append(f"已执行漂移检测: {ros_checked_count} ({coverage_ratio:.0%})")

                if unknown_risk_count > 0:
                    warnings.append(f"{unknown_risk_count} 个 Stack 未检测或检测失败 (状态未知)，存在潜在漂移风险")
                    evidence.append(f"⚠ 未检测/失败: {unknown_risk_count}")

                if drifted:
                    drift_found = True
                    critical_drifted = [d for d in drifted if
                                        'prod' in d.stack_name.lower() or 'db' in d.stack_name.lower()]
                    display_list = critical_drifted[:3] if critical_drifted else drifted[:3]
                    names_str = ', '.join([d.stack_name for d in display_list])
                    suffix = '...' if len(drifted) > 3 else ''
                    evidence.append(f"  ⚠ 发现 {len(drifted)} 个 Stack 存在漂移: {names_str}{suffix}")
                elif ros_checked_count > 0:
                    evidence.append("  ✓ 所有已检测 Stack 均处于同步状态")
                else:
                    evidence.append("  ℹ️ 暂无成功执行的检测记录")

        cms_drift_alerts = []
        if store.available("cms.alarm.history"):
            alarm_history: list[CmsAlarmHistoryRecord] = store.get("cms.alarm.history")

            drift_keywords = ["漂移", "drift", "资源不一致", "deviation", "template mismatch"]

            cutoff_days = 30
            recent_alerts = []

            for a in alarm_history:
                is_recent = True
                if a.timestamp:
                    try:
                        t = a.timestamp
                        if (datetime.datetime.now(tz=t.tzinfo) - t).days > cutoff_days:
                            is_recent = False
                    except:
                        pass

                if is_recent:
                    msg_content = f"{a.alarm_name} {a.message}"
                    if any(kw in msg_content.lower() for kw in drift_keywords):
                        recent_alerts.append(a)

            cms_drift_alerts = recent_alerts

            if cms_drift_alerts:
                has_detection_capability = True
                evidence.append(f"☁️ 云监控捕获近期漂移相关告警: {len(cms_drift_alerts)} 条 (近{cutoff_days}天)")

        if not has_detection_capability:
            if not store.available("ros.stack.drift") and not store.available("cms.alarm.history"):
                return self._not_scored("未获取到任何漂移检测相关数据 (ROS/CMS)", evidence)
            reasons = []
            if ros_total_count > 0 and ros_checked_count == 0:
                reasons.append("ROS 未执行任何检测")
            if not cms_drift_alerts and store.available("cms.alarm.history"):
                reasons.append("CMS 无相关告警")
            return self._not_scored(f"已接入数据源但未发现有效检测记录: {'; '.join(reasons)}", evidence)

        if coverage_ratio >= 0.9:
            if unknown_risk_count == 0 and not drift_found:
                final_score = 5
                final_msg = "漂移检测全覆盖且当前环境一致"
            elif drift_found:
                if ros_drifted_count >= 5:
                    final_score = 3
                    final_msg = f"检测机制完善，但发现大量资源漂移 ({ros_drifted_count}个Stack，需紧急修复)"
                elif ros_drifted_count >= 2:
                    final_score = 4
                    final_msg = f"检测机制完善，但检测到资源漂移 ({ros_drifted_count}个Stack，需修复)"
                else:
                    final_score = 4
                    final_msg = "检测机制完善，但检测到资源漂移 (需修复)"
            elif unknown_risk_count > 0:
                final_score = 4
                final_msg = "检测覆盖率高，但存在部分未检测资源"
                warnings.append("剩余未检测资源可能导致盲区")
            elif cms_drift_alerts and not drift_found:
                final_score = 4
                final_msg = "检测机制完善，近期曾有告警 (建议核查)"
            else:
                final_score = 5
                final_msg = "漂移检测机制完善"

        elif coverage_ratio >= 0.7:
            if drift_found:
                final_score = 3
                final_msg = "漂移检测覆盖良好，但检测到资源漂移"
            else:
                final_score = 4
                final_msg = "漂移检测覆盖良好，当前环境一致"

        elif coverage_ratio >= 0.5:
            final_score = 3
            msg_parts = ["部分资源启用漂移检测"]
            if drift_found:
                msg_parts.append("且检测到漂移")
            if unknown_risk_count > 0:
                msg_parts.append(f"另有 {unknown_risk_count} 个资源状态未知")
            final_msg = "，".join(msg_parts)

        elif coverage_ratio >= 0.3:
            if ros_checked_count > 0:
                final_score = 2
                final_msg = f"漂移检测覆盖范围有限 ({coverage_ratio:.0%})"
            else:
                final_score = 2
                final_msg = "仅依赖云监控告警，缺乏系统性漂移检测"

        else:
            if cms_drift_alerts and ros_total_count == 0:
                # 纯被动检测，覆盖率低
                final_score = 2
                final_msg = "依赖云监控告警进行被动检测 (缺乏 ROS 主动全量扫描)"
            elif ros_checked_count > 0:
                final_score = 1
                final_msg = f"漂移检测覆盖范围很低 ({coverage_ratio:.0%})"
            else:
                final_score = 1
                final_msg = "仅依赖云监控告警，缺乏系统性漂移检测"

        if warnings:
            evidence.extend([f"⚠ {w}" for w in warnings])

        return self._scored(final_score, final_msg, evidence)


# 导出所有分析器
IAC_ANALYZERS = [
    ProvisioningAutomationAnalyzer(),
    ConfigurationManagementAnalyzer(),
    PolicyAsCodeAnalyzer(),
    DriftDetectionAnalyzer(),
]
