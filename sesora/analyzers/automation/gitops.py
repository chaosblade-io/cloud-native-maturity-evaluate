"""
Automation 维度 - GitOps 实践分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)              | 分值 | 评分标准                                                  |
| ------------------------- | ---- | --------------------------------------------------------- |
| declarative_configuration | 6    | 系统期望状态完全通过声明式文件 (YAML/Helm/Kustomize) 描述 |
| version_control           | 6    | 所有配置变更必须通过 Git PR/MR 流程，禁止直接修改集群     |
| automated_reconciliation  | 6    | 控制器持续监控并自动将实际状态调谐至 Git 定义的状态       |
| environment_separation    | 6    | 不同环境 (Dev/Test/Prod) 通过 Git 分支或目录严格隔离      |
"""
import os

from ...core.analyzer import Analyzer, ScoreResult
from ...schema.k8s import ArgoAppRecord, K8sDeploymentRecord
from ...schema.codeup import (
    CodeupRepoFileTreeRecord, CodeupCommitRecord,
    CodeupBranchRecord
)


class DeclarativeConfigurationAnalyzer(Analyzer):
    """
    声明式配置分析器
    
    评估标准：系统期望状态完全通过声明式文件 (YAML/Helm/Kustomize) 描述
    
    数据来源：
    - 云效 Codeup：仓库内容 API，扫描是否存在 K8s YAML、Helm Chart、Kustomize 配置文件，
      且不存在直接执行 kubectl run 的 Shell 脚本
    - ACK API：检查工作负载是否通过 GitOps 控制器（ArgoCD Application）管理
    """

    def key(self) -> str:
        return "declarative_configuration"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "GitOps实践"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["codeup.repo.file_tree"]

    def optional_data(self) -> list[str]:
        return ["k8s.argocd.app.list"]

    def analyze(self, store) -> ScoreResult:
        file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

        if not file_tree:
            return self._not_evaluated("未获取到仓库文件树信息")

        evidence = []
        score = 0

        # 声明式配置文件特征
        declarative_patterns = {
            "K8s YAML": {
                "files": {"deployment.yaml", "service.yaml", "configmap.yaml",
                          "ingress.yaml", "secret.yaml", "namespace.yaml"},
                "dirs": {"k8s/", "kubernetes/", "manifests/", "deploy/", "base/", "overlays/"}
            },
            "Helm": {
                "files": {"chart.yaml", "values.yaml"},
                "dirs": {"charts/", "helm/", "templates/"}
            },
            "Kustomize": {
                "files": {"kustomization.yaml", "kustomization.yml"},
                "dirs": {"kustomize/", "overlays/", "base/"}
            }
        }

        found_types: set[str] = set()
        suspicious_scripts: list[str] = []

        for file_record in file_tree:
            file_path = (file_record.path or "").lower()
            file_name = (file_record.name or "").lower()

            # 1. 检查声明式配置 (使用集合去重，避免重复计数)
            for config_type, patterns in declarative_patterns.items():
                is_match = False

                if file_name in patterns["files"]:
                    is_match = True

                if not is_match:
                    for dir_pattern in patterns["dirs"]:
                        if dir_pattern in file_path:
                            is_match = True
                            break

                if is_match:
                    found_types.add(config_type)

            # Todo: 当前仅关注可能涉及部署的脚本，排除 build/test 等常见命名，未来可以将它复杂化一些
            if file_name.endswith(".sh"):
                deploy_keywords = ["deploy", "install", "apply", "run", "create", "launch"]
                if any(kw in file_name for kw in deploy_keywords):
                    suspicious_scripts.append(file_record.name)

        if found_types:
            type_count = len(found_types)
            if type_count >= 3:
                type_score = 4
            elif type_count >= 2:
                type_score = 3
            else:
                type_score = 2
            score += type_score

            type_list = ", ".join(sorted(list(found_types)))
            evidence.append(f"✅ 发现声明式配置: {type_list} ({type_count}种)")
        else:
            return self._not_scored(
                "未检测到声明式配置文件",
                [f"扫描了 {len(file_tree)} 个文件", "未发现 K8s YAML、Helm Chart 或 Kustomize 配置"]
            )

        # ArgoCD 评分：根据应用数量细化
        if store.available("k8s.argocd.app.list"):
            apps: list[ArgoAppRecord] = store.get("k8s.argocd.app.list")
            if apps:
                app_count = len(apps)
                if app_count >= 10:
                    argocd_score = 2
                    evidence.append(f" GitOps 管理: ArgoCD 纳管 {app_count} 个应用 (覆盖完善)")
                elif app_count >= 3:
                    argocd_score = 1.5
                    evidence.append(f" GitOps 管理: ArgoCD 纳管 {app_count} 个应用")
                else:
                    argocd_score = 1
                    evidence.append(f" GitOps 管理: ArgoCD 纳管 {app_count} 个应用 (初步覆盖)")
                score += argocd_score

                synced = [a for a in apps if a.sync_status == "Synced"]
                if len(synced) == len(apps):
                    evidence.append("  所有应用同步状态健康")
                else:
                    evidence.append(f"  同步状态: {len(synced)}/{len(apps)} 已同步")

        if suspicious_scripts:
            script_count = len(suspicious_scripts)
            if script_count >= 5:
                score -= 1
                evidence.append(f"⚠️ 警告: 发现 {script_count} 个疑似命令式部署脚本，建议迁移到声明式配置")
            elif script_count >= 2:
                score -= 0.5
                evidence.append(
                    f"⚠️ 注意: 发现 {script_count} 个疑似命令式部署脚本 ({', '.join(suspicious_scripts[:3])}...)")
            else:
                evidence.append(f"ℹ️ 提示: 发现 {script_count} 个脚本，建议确认是否用于生产部署")

        score = min(score, 6)

        if score >= 5.5:
            return self._scored(6, "系统期望状态完全通过声明式文件及 GitOps 自动化管理", evidence)
        elif score >= 4.5:
            return self._scored(5, "主要配置采用声明式管理，GitOps 自动化程度较高", evidence)
        elif score >= 3.5:
            return self._scored(4, "声明式配置覆盖良好，具备较好的可维护性", evidence)
        elif score >= 2.5:
            return self._scored(3, "声明式配置初步建立，GitOps 自动化程度有待提升", evidence)
        elif score >= 1.5:
            return self._scored(2, "声明式配置覆盖有限，存在较多手动操作", evidence)
        else:
            return self._scored(1, "声明式配置覆盖非常有限，主要依赖命令式部署", evidence)


class VersionControlAnalyzer(Analyzer):
    """
    版本控制分析器
    
    评估标准：所有配置变更必须通过 Git PR/MR 流程，禁止直接修改集群
    
    数据来源：
    - 云效 Codeup：Commit 历史 API，随机抽取 5 次近期变更，检查是否有对应的 PR/MR
    - K8s Audit Log：检查生产集群的 Deployment 修改操作，user.username 是否为 
      GitOps 控制器账号，排除人工直接操作
    """

    def key(self) -> str:
        return "version_control"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "GitOps实践"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["codeup.commit.list"]

    def optional_data(self) -> list[str]:
        return ["k8s.deployment.list"]

    def analyze(self, store) -> ScoreResult:
        commits: list[CodeupCommitRecord] = store.get("codeup.commit.list")

        if not commits:
            return self._not_evaluated("未获取到提交历史数据")

        evidence = []

        recent_commits = commits[:30] if len(commits) > 30 else commits

        mr_commits = [c for c in recent_commits if c.has_merge_request]
        direct_commits = [c for c in recent_commits if not c.has_merge_request]

        evidence.append(f"近期提交采样: {len(recent_commits)} 次 (总历史: {len(commits)})")
        evidence.append(f"  通过 MR/PR: {len(mr_commits)} 次")
        evidence.append(f"  直接提交: {len(direct_commits)} 次")

        mr_ratio = len(mr_commits) / len(recent_commits)

        # 2. 检查 K8s 工作负载是否由 GitOps 控制器管理
        gitops_managed_ratio = 0.0

        if store.available("k8s.deployment.list"):
            deployments: list[K8sDeploymentRecord] = store.get("k8s.deployment.list")

            if deployments:
                gitops_managed_count = 0
                for d in deployments:
                    is_managed = False
                    labels = d.labels
                    annotations = d.annotations

                    if labels.get('app.kubernetes.io/managed-by') in ['argocd', 'flux', 'kustomize']:
                        is_managed = True
                    elif annotations.get('argocd.argoproj.io/tracking-id'):
                        is_managed = True
                    elif annotations.get('fluxcd.io/sync-checksum'):
                        is_managed = True

                    if not is_managed:
                        all_text = str(labels) + str(annotations)
                        if any(keyword in all_text for keyword in
                               ["argocd.argoproj.io", "fluxcd.io", "kustomize.toolkit.fluxcd.io"]):
                            is_managed = True

                    if is_managed:
                        gitops_managed_count += 1

                gitops_managed_ratio = gitops_managed_count / len(deployments)
                gitops_details = f"{gitops_managed_count}/{len(deployments)}"
                evidence.append(f"K8s 工作负载 GitOps 管理覆盖率: {gitops_details}")
            else:
                evidence.append("K8s 部署列表为空")
        else:
            evidence.append("无法访问 K8s 部署数据，跳过 GitOps 检查")

        if mr_ratio >= 0.9:
            mr_score = 4
        elif mr_ratio >= 0.8:
            mr_score = 3.5
        elif mr_ratio >= 0.7:
            mr_score = 3
        elif mr_ratio >= 0.5:
            mr_score = 2
        elif mr_ratio >= 0.3:
            mr_score = 1
        else:
            mr_score = 0.5

        gitops_score = 0
        if gitops_managed_ratio >= 0.8:
            gitops_score = 2
        elif gitops_managed_ratio >= 0.5:
            gitops_score = 1.5
        elif gitops_managed_ratio >= 0.3:
            gitops_score = 1
        elif gitops_managed_ratio > 0:
            gitops_score = 0.5

        total_score = mr_score + gitops_score

        if total_score >= 5.5:
            return self._scored(6, "变更全链路 GitOps 化 (高 MR 比例 + 高 GitOps 覆盖率)", evidence)
        elif total_score >= 4.5:
            return self._scored(5, "绝大部分变更通过 PR/MR，GitOps 覆盖率良好", evidence)
        elif total_score >= 3.5:
            return self._scored(4, "变更主要通过 PR/MR 流程，GitOps 覆盖率一般", evidence)
        elif total_score >= 2.5:
            return self._scored(3, "部分变更通过 PR/MR 流程，GitOps 初步覆盖", evidence)
        elif total_score >= 1.5:
            return self._scored(2, "变更部分通过 PR/MR，GitOps 覆盖有限", evidence)
        elif mr_ratio > 0:
            return self._scored(1, "仅有少量变更通过 PR/MR 流程，GitOps 覆盖薄弱", evidence)
        else:
            return self._scored(1, "所有变更均为直接提交，未通过 PR/MR 流程", evidence)


class AutomatedReconciliationAnalyzer(Analyzer):
    """
    自动调谐分析器
    
    评估标准：控制器持续监控并自动将实际状态调谐至 Git 定义的状态
    
    数据来源：
    - ArgoCD API（若使用 ACK GitOps）：GET /api/v1/applications
      检查所有 Application 的 sync.status 是否为 Synced，health.status 是否为 Healthy
    """

    def key(self) -> str:
        return "automated_reconciliation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "GitOps实践"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return ["k8s.argocd.app.list"]

    def analyze(self, store) -> ScoreResult:
        apps: list[ArgoAppRecord] = store.get("k8s.argocd.app.list")

        if not apps:
            return self._not_evaluated("未获取到 ArgoCD 应用数据")

        total_count = len(apps)
        evidence = [f"ArgoCD 应用总数: {total_count}"]

        synced_count = 0
        out_of_sync_count = 0
        healthy_count = 0
        degraded_count = 0
        auto_sync_count = 0
        self_heal_count = 0

        for a in apps:
            sync_status = a.sync_status
            health_status = a.health_status
            is_auto_sync = a.auto_sync_enabled
            is_self_heal = a.self_heal_enabled

            if sync_status == "Synced":
                synced_count += 1
            elif sync_status == "OutOfSync":
                out_of_sync_count += 1

            if health_status == "Healthy":
                healthy_count += 1
            elif health_status == "Degraded":
                degraded_count += 1

            # 统计自动化配置
            if is_auto_sync:
                auto_sync_count += 1
            if is_self_heal:
                self_heal_count += 1

        unknown_sync_count = total_count - synced_count - out_of_sync_count
        progressing_count = total_count - healthy_count - degraded_count

        evidence.append(f"同步状态: Synced={synced_count}, OutOfSync={out_of_sync_count}, 其他={unknown_sync_count}")
        evidence.append(
            f"健康状态: Healthy={healthy_count}, Degraded={degraded_count}, 其他/Progressing={progressing_count}")
        evidence.append(
            f"自动同步 (Auto Sync) 启用率: {auto_sync_count}/{total_count} ({auto_sync_count / total_count:.1%})")
        evidence.append(
            f"自愈 (Self Heal) 启用率: {self_heal_count}/{total_count} ({self_heal_count / total_count:.1%})")

        sync_ratio = synced_count / total_count
        health_ratio = healthy_count / total_count
        auto_ratio = auto_sync_count / total_count
        self_heal_ratio = self_heal_count / total_count

        full_auto_count = sum(
            1 for a in apps if a.auto_sync_enabled and a.self_heal_enabled)
        full_auto_ratio = full_auto_count / total_count
        if full_auto_count > 0:
            evidence.append(f"完全自动化 (Sync+Heal) 应用数: {full_auto_count}/{total_count}")

        # 综合评分：同步率 + 健康率 + 自动同步率 + 自愈率
        # 计算各维度得分
        sync_score = 0
        if sync_ratio >= 0.9:
            sync_score = 2.5
        elif sync_ratio >= 0.8:
            sync_score = 2
        elif sync_ratio >= 0.6:
            sync_score = 1.5
        elif sync_ratio >= 0.4:
            sync_score = 1
        elif sync_ratio >= 0.2:
            sync_score = 0.5
        else:
            sync_score = 0.2

        health_score = 0
        if health_ratio >= 0.9:
            health_score = 1.5
        elif health_ratio >= 0.7:
            health_score = 1
        elif health_ratio >= 0.5:
            health_score = 0.5
        else:
            health_score = 0.2

        auto_score = 0
        if auto_ratio >= 0.8:
            auto_score = 1.5
        elif auto_ratio >= 0.5:
            auto_score = 1
        elif auto_ratio >= 0.3:
            auto_score = 0.5
        else:
            auto_score = 0.2

        self_heal_score = 0
        if self_heal_ratio >= 0.8:
            self_heal_score = 1
        elif self_heal_ratio >= 0.5:
            self_heal_score = 0.5
        else:
            self_heal_score = 0.2

        total_score = sync_score + health_score + auto_score + self_heal_score

        # 评分判断 - 6分制平滑档位
        if total_score >= 5.5:
            return self._scored(6, "控制器持续监控并自动调谐至 Git 定义的状态 (含自愈)", evidence)
        elif total_score >= 4.5:
            return self._scored(5, "GitOps 自动调谐运行良好，自愈能力覆盖较好", evidence)
        elif total_score >= 3.5:
            return self._scored(4, "GitOps 自动调谐运行较好，部分能力有待提升", evidence)
        elif total_score >= 2.5:
            return self._scored(3, "GitOps 部分应用实现自动调谐", evidence)
        elif total_score >= 1.5:
            return self._scored(2, "GitOps 控制器已安装但调谐能力有限", evidence)
        else:
            return self._scored(1, "GitOps 调谐能力薄弱，建议检查控制器配置", evidence)


class EnvironmentSeparationAnalyzer(Analyzer):
    """
    环境隔离分析器
    
    评估标准：不同环境 (Dev/Test/Prod) 通过 Git 分支或目录严格隔离
    
    数据来源：
    - 云效 Codeup：仓库目录树 API，检查是否存在 /dev、/staging、/prod 等目录，
      或 dev、main 等分支，并检查各分支/目录的访问控制配置
    """

    def key(self) -> str:
        return "environment_separation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "GitOps实践"

    def max_score(self) -> int:
        return 6

    def required_data(self) -> list[str]:
        return []

    def optional_data(self) -> list[str]:
        return [
            "codeup.repo.file_tree",
            "codeup.branch.list"
        ]

    def analyze(self, store) -> ScoreResult:
        evidence = []
        env_dirs_found = []
        env_branches_found = []

        env_keywords = {
            "dev": ["dev", "develop", "development"],
            "test": ["test", "testing", "qa", "sit"],
            "staging": ["staging", "stage", "pre", "uat"],
            "prod": ["prod", "production", "main", "master", "release"]
        }

        # 1. 检查目录结构
        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

            for file_record in file_tree:
                file_path = (file_record.path or "").lower()
                dir_path = os.path.dirname(file_path) if file_path else ""

                for env, keywords in env_keywords.items():
                    if any(kw in dir_path for kw in keywords):
                        if env not in env_dirs_found:
                            env_dirs_found.append(env)

            if env_dirs_found:
                evidence.append(f"环境目录: {', '.join(env_dirs_found)}")

        # 2. 检查分支结构
        if store.available("codeup.branch.list"):
            branches: list[CodeupBranchRecord] = store.get("codeup.branch.list")

            for branch in branches:
                branch_name = branch.branch_name.lower()

                for env, keywords in env_keywords.items():
                    if any(kw == branch_name or branch_name.startswith(kw) for kw in keywords):
                        if env not in env_branches_found:
                            env_branches_found.append(env)

            if env_branches_found:
                evidence.append(f"环境分支: {', '.join(env_branches_found)}")

                protected_branches = [b for b in branches if b.is_protected]
                if protected_branches:
                    evidence.append(f"受保护分支: {len(protected_branches)} 个")

        if not store.available("codeup.repo.file_tree") and not store.available("codeup.branch.list"):
            return self._not_evaluated("未获取到仓库目录或分支信息")

        all_envs = set(env_dirs_found + env_branches_found)

        if not all_envs:
            return self._not_scored(
                "未检测到环境隔离配置",
                ["未发现 dev/test/staging/prod 等环境目录或分支"]
            )

        has_dev = "dev" in all_envs
        has_test = "test" in all_envs or "staging" in all_envs
        has_prod = "prod" in all_envs

        env_count = sum([has_dev, has_test, has_prod])

        if env_count >= 3:
            base_score = 4
        elif env_count == 2:
            base_score = 2.5
        else:
            base_score = 1

        bonus_score = 0
        if env_dirs_found and env_branches_found:
            bonus_score += 1
            evidence.append("同时使用目录和分支进行环境隔离")

        protected_bonus = 0
        if store.available("codeup.branch.list"):
            branches: list[CodeupBranchRecord] = store.get("codeup.branch.list")
            protected_branches = [b for b in branches if b.is_protected]
            if len(protected_branches) >= 2:
                protected_bonus = 1
                evidence.append(f"受保护分支: {len(protected_branches)} 个 (规范完善)")
            elif len(protected_branches) == 1:
                protected_bonus = 0.5
                evidence.append(f"受保护分支: 1 个")

        total_score = base_score + bonus_score + protected_bonus

        if total_score >= 5.5:
            return self._scored(6, "不同环境通过 Git 分支或目录严格隔离，规范完善", evidence)
        elif total_score >= 4.5:
            return self._scored(5, "环境隔离配置良好，多种隔离方式配合使用", evidence)
        elif total_score >= 3.5:
            return self._scored(4, "环境隔离配置较好，覆盖主要环境", evidence)
        elif total_score >= 2.5:
            return self._scored(3, "部分环境通过 Git 隔离，配置有待完善", evidence)
        elif total_score >= 1.5:
            return self._scored(2, "环境隔离不完善，仅覆盖少量环境", evidence)
        else:
            return self._scored(1, "环境隔离配置薄弱，建议建立规范的环境管理", evidence)


# 导出所有分析器
GITOPS_ANALYZERS = [
    DeclarativeConfigurationAnalyzer(),
    VersionControlAnalyzer(),
    AutomatedReconciliationAnalyzer(),
    EnvironmentSeparationAnalyzer(),
]
