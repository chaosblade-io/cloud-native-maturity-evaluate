"""
Automation 维度 - CI/CD 流水线自动化分析器

评估项与分值（来自 SESORA 成熟度评分细则）：
| 评估项 (Key)          | 分值 | 评分标准                                        |
| --------------------- | ---- | ----------------------------------------------- |
| build_automation      | 4    | 代码提交后自动触发构建，无需人工干预            |
| test_automation       | 5    | 构建过程中自动运行单元测试/集成测试，失败即阻断 |
| deployment_automation | 5    | 测试通过后自动部署至目标环境（非手动点击）      |
| release_management    | 4    | 具备版本打标、发布审批流、回滚机制的管理能力    |
| pipeline_as_code      | 4    | 流水线定义存储在代码库中，随代码版本管理        |
"""
from ...core.analyzer import Analyzer, ScoreResult
from ...schema.codeup import (
    CodeupPipelineRunRecord,
    CodeupPipelineStageRecord, CodeupRepoFileTreeRecord,
    CodeupRepoTagRecord, CodeupCommitRecord, CodeupFileCommitRecord
)


class BuildAutomationAnalyzer(Analyzer):
    """
    构建自动化分析器
    
    评估标准：代码提交后自动触发构建，无需人工干预
    
    数据来源：
    - 云效 Flow：ListPipelineRuns API，查询最近 10 次流水线执行记录中的 triggerMode 字段
    - 云效 Codeup：检查根目录下是否存在 .pipeline.yml 且配置了 push/merge_request 事件触发
    """

    def key(self) -> str:
        return "build_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "CI/CD流水线自动化"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["codeup.pipeline.runs"]

    def optional_data(self) -> list[str]:
        return ["codeup.repo.file_tree"]

    def analyze(self, store) -> ScoreResult:
        runs: list[CodeupPipelineRunRecord] = store.get("codeup.pipeline.runs")

        if not runs:
            return self._not_evaluated("未获取到流水线执行记录")

        recent_runs = runs[:30] if len(runs) >= 30 else runs

        auto_triggered = [r for r in recent_runs if r.trigger_type in ("WEBHOOK", "SCHEDULE", "PUSH", "PIPELINE")]
        manual_triggered = [r for r in recent_runs if r.trigger_type == "MANUAL"]

        evidence = [
            f"最近 {len(recent_runs)} 次执行中:",
            f"  自动触发: {len(auto_triggered)} 次",
            f"  手动触发: {len(manual_triggered)} 次"
        ]

        if store.available("codeup.repo.file_tree"):
            file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")
            pipeline_files = [
                f for f in file_tree
                if f.path and any(keyword.lower() in f.path.lower() for keyword in (
                    ".pipeline.yml", ".pipeline.yaml", "pipeline.yml",
                    ".github/workflows", ".gitlab-ci.yml", ".aone/pipeline.yml"
                ))
            ]
            if pipeline_files:
                evidence.append(f"检测到流水线定义文件: {len(pipeline_files)} 个")

        auto_ratio = len(auto_triggered) / len(recent_runs)

        if auto_ratio >= 0.9:
            return self._scored(4, "代码提交后自动触发构建，无需人工干预", evidence)
        elif auto_ratio >= 0.7:
            return self._scored(3, "大部分构建自动触发，少量需人工干预", evidence)
        elif auto_ratio >= 0.5:
            return self._scored(2, "部分构建自动触发，仍有人工干预", evidence)
        elif auto_ratio >= 0.3:
            return self._scored(1, "少量构建自动触发，主要依赖人工", evidence)
        else:
            return self._not_scored("构建主要依赖人工触发", evidence)


class TestAutomationAnalyzer(Analyzer):
    """
    测试自动化分析器
    
    评估标准：构建过程中自动运行单元测试/集成测试，失败即阻断
    
    数据来源：
    - 云效 Flow：流水线阶段定义 API，检查是否存在 test 类型阶段
    - 检查该阶段的 onFailure 策略是否为 block（失败阻断）
    """

    def key(self) -> str:
        return "test_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "CI/CD流水线自动化"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["codeup.pipeline.stages"]

    def analyze(self, store) -> ScoreResult:
        stages: list[CodeupPipelineStageRecord] = store.get("codeup.pipeline.stages")

        if not stages:
            return self._not_evaluated("未获取到流水线阶段信息")

        test_stages = [s for s in stages if s.has_test_step]

        if not test_stages:
            return self._not_scored("流水线中不包含测试阶段", [f"共 {len(stages)} 个阶段，无测试阶段"])

        evidence = [f"检测到测试阶段: {len(test_stages)} 个"]

        blocking_stages = [s for s in test_stages if s.on_failure == "block"]
        non_blocking_stages = [s for s in test_stages if s.on_failure != "block"]

        evidence.append(f"失败阻断: {len(blocking_stages)} 个")
        evidence.append(f"失败继续: {len(non_blocking_stages)} 个")

        blocking_ratio = len(blocking_stages) / len(test_stages)

        if blocking_ratio == 1.0:
            return self._scored(5, "构建过程中自动运行测试，失败即阻断", evidence)
        elif blocking_ratio >= 0.7:
            return self._scored(4, "大部分测试阶段配置失败阻断", evidence)
        elif blocking_ratio >= 0.4:
            return self._scored(3, "部分测试阶段配置失败阻断", evidence)
        elif blocking_ratio > 0:
            return self._scored(2, "少量测试阶段配置失败阻断", evidence)
        else:
            return self._scored(1, "有自动化测试，但失败不阻断流水线", evidence)


class DeploymentAutomationAnalyzer(Analyzer):
    """
    部署自动化分析器
    
    评估标准：测试通过后自动部署至目标环境（非手动点击）

    数据来源：
    - 云效 Flow：流水线部署阶段定义，检查是否包含 kubectl apply 或 helm upgrade 步骤
    - 检查该步骤前是否无 ManualGate（人工审批门禁）
    """

    def key(self) -> str:
        return "deployment_automation"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "CI/CD流水线自动化"

    def max_score(self) -> int:
        return 5

    def required_data(self) -> list[str]:
        return ["codeup.pipeline.stages"]

    def analyze(self, store) -> ScoreResult:
        stages: list[CodeupPipelineStageRecord] = store.get("codeup.pipeline.stages")

        if not stages:
            return self._not_evaluated("未获取到流水线阶段信息")

        pipelines = {}

        deploy_stages = []

        for stage in stages:
            if stage.pipeline_id not in pipelines:
                pipelines[stage.pipeline_id] = []
            pipelines[stage.pipeline_id].append(stage)

        for _, stages in pipelines.items():
            stages = sorted(stages, key=lambda s: s.stage_order)
            for stage in stages:
                if stage.has_deploy_step:
                    deploy_stages.append(stage)

        if not deploy_stages:
            return self._not_scored("流水线不包含部署阶段", [f"共 {len(stages)} 个阶段，无部署阶段"])

        evidence = [f"检测到部署阶段: {len(deploy_stages)} 个"]

        auto_deploy_stages = []
        manual_deploy_stages = []

        for _, stages in pipelines.items():
            stages = sorted(stages, key=lambda s: s.stage_order)
            has_manual_gate = False
            for stage in stages:
                if stage.has_manual_gate:
                    has_manual_gate = True
                if stage.has_deploy_step:
                    if has_manual_gate:
                        manual_deploy_stages.append(stage)
                    else:
                        auto_deploy_stages.append(stage)

        evidence.append(f"自动部署阶段（无人工门禁）: {len(auto_deploy_stages)} 个")
        evidence.append(f"需审批的部署阶段: {len(manual_deploy_stages)} 个")

        auto_ratio = len(auto_deploy_stages) / len(deploy_stages)

        if auto_ratio == 1.0:
            return self._scored(5, "测试通过后自动部署至目标环境，无需人工干预", evidence)
        elif auto_ratio >= 0.7:
            return self._scored(4, "大部分环境自动部署，少量需人工审批", evidence)
        elif auto_ratio >= 0.4:
            return self._scored(3, "部分环境自动部署，部分需人工审批", evidence)
        elif auto_ratio > 0:
            return self._scored(2, "少量环境自动部署，主要依赖人工审批", evidence)
        else:
            return self._scored(1, "所有部署均需人工审批", evidence)


class ReleaseManagementAnalyzer(Analyzer):
    """
    发布管理分析器
    
    评估标准：具备版本打标、发布审批流、回滚机制的管理能力
    
    数据来源：
    - 云效 Codeup：Tag API，检查近 30 天是否有符合 SemVer 规范的 Git Tag
    - 云效 Flow：检查生产环境流水线中是否配置了 ManualGate（审批节点）
    """

    def key(self) -> str:
        return "release_management"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "CI/CD流水线自动化"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["codeup.repo.tags"]

    def optional_data(self) -> list[str]:
        return ["codeup.pipeline.stages"]

    def analyze(self, store) -> ScoreResult:
        tags: list[CodeupRepoTagRecord] = store.get("codeup.repo.tags")

        if not tags:
            return self._not_evaluated("未获取到仓库标签信息")

        evidence = []
        score = 0

        # 1. 版本规范评估（0-2分）
        semver_tags = [t for t in tags if t.is_semver]
        semver_ratio = len(semver_tags) / len(tags) if tags else 0

        evidence.append(f"Git Tags 总数: {len(tags)}")
        evidence.append(f"符合 SemVer 规范: {len(semver_tags)} 个 ({semver_ratio:.0%})")

        if semver_ratio >= 0.8:
            score += 2
            evidence.append("✓ 版本规范执行良好")
        elif semver_ratio >= 0.5:
            score += 1
            evidence.append("△ 版本规范部分执行")
        else:
            evidence.append("✗ 版本规范执行较差")

        # 2. 发布审批评估（0-2分）
        if store.available("codeup.pipeline.stages"):
            stages: list[CodeupPipelineStageRecord] = store.get("codeup.pipeline.stages")

            deploy_stages = [s for s in stages if s.has_deploy_step]
            approval_deploy_stages = [s for s in deploy_stages if s.has_manual_gate]

            if deploy_stages:
                approval_ratio = len(approval_deploy_stages) / len(deploy_stages)
                evidence.append(f"部署阶段: {len(deploy_stages)} 个，含审批: {len(approval_deploy_stages)} 个")

                if approval_ratio >= 0.8:
                    score += 2
                    evidence.append("✓ 发布审批覆盖完善")
                elif approval_ratio >= 0.5:
                    score += 1
                    evidence.append("△ 发布审批部分覆盖")
                else:
                    evidence.append("✗ 发布审批覆盖不足")
            else:
                evidence.append("✗ 未检测到部署阶段")

        # 评分映射到 0-4 分制
        if score >= 4:
            return self._scored(4, "具备完善的版本管理和发布控制机制", evidence)
        elif score == 3:
            return self._scored(3, "版本管理和发布控制较为完善", evidence)
        elif score == 2:
            return self._scored(2, "具备基本的发布管理能力", evidence)
        elif score == 1:
            return self._scored(1, "发布管理能力有限", evidence)
        else:
            return self._not_scored("缺乏规范的发布管理实践", evidence)


class PipelineAsCodeAnalyzer(Analyzer):
    """
    流水线即代码分析器
    
    评估标准：流水线定义存储在代码库中，随代码版本管理
    
    数据来源：
    - 云效 Codeup：文件树 API，检查仓库根目录或特定目录下是否存在流水线定义文件
    - 云效 Codeup：Commits API，检查该文件的变更历史是否经过 PR/MR Code Review 流程
    """

    def key(self) -> str:
        return "pipeline_as_code"

    def dimension(self) -> str:
        return "Automation"

    def category(self) -> str:
        return "CI/CD流水线自动化"

    def max_score(self) -> int:
        return 4

    def required_data(self) -> list[str]:
        return ["codeup.repo.file_tree", "codeup.file.commits"]

    def analyze(self, store) -> ScoreResult:
        file_tree: list[CodeupRepoFileTreeRecord] = store.get("codeup.repo.file_tree")

        if not file_tree:
            return self._not_evaluated("未获取到仓库文件树信息")

        pipeline_patterns = [
            ".pipeline.yml", ".pipeline.yaml", "pipeline.yml", "pipeline.yaml",
            ".gitlab-ci.yml", ".gitlab-ci.yaml",
            "Jenkinsfile",
            ".travis.yml",
            "azure-pipelines.yml",
            ".circleci/config.yml",
            ".aone/pipeline.yml", ".aone/pipeline.yaml",
        ]

        evidence = []
        found_pipeline_files = []

        for file_record in file_tree:
            if file_record.type != "file":
                continue

            file_path = file_record.path.lower() if file_record.path else file_record.name.lower()
            file_name = file_record.name.lower()

            for pattern in pipeline_patterns:
                if file_path.endswith(pattern.lower()) or file_name == pattern.lower():
                    found_pipeline_files.append(file_record)
                    break

            if "/.github/workflows/" in file_path and file_name.endswith((".yml", ".yaml")):
                found_pipeline_files.append(file_record)

        if not found_pipeline_files:
            return self._not_scored(
                "代码库中未找到流水线定义文件",
                [f"扫描了 {len(file_tree)} 个文件/目录",
                 "未检测到 .pipeline.yml, Jenkinsfile, .gitlab-ci.yml 等文件"]
            )

        evidence.append(f"检测到流水线定义文件: {len(found_pipeline_files)} 个")
        for pf in found_pipeline_files[:5]:
            evidence.append(f"  - {pf.path or pf.name}")

        score = 0

        # 1. 代码化管理覆盖率（0-2分）
        if len(found_pipeline_files) >= 3:
            score += 2
            evidence.append("✓ 多个流水线纳入代码管理")
        elif len(found_pipeline_files) >= 1:
            score += 1
            evidence.append("△ 流水线代码化管理覆盖有限")

        # 2. 版本控制规范性（0-2分）
        if store.available("codeup.file.commits"):
            file_last_commits: list[CodeupFileCommitRecord] = store.get("codeup.file.commits")
            pipeline_file_paths = {pf.path for pf in found_pipeline_files if pf.path}

            pipeline_commits = [c for c in file_last_commits if c.file_path in pipeline_file_paths]

            if pipeline_commits:
                reviewed_count = sum(1 for c in pipeline_commits if c.has_merge_request)
                review_ratio = reviewed_count / len(pipeline_commits)

                evidence.append(
                    f"流水线文件提交: {len(pipeline_commits)} 个，经 MR/PR: {reviewed_count} 个 ({review_ratio:.0%})")

                if review_ratio >= 0.8:
                    score += 2
                    evidence.append("✓ 流水线变更严格遵循 Code Review")
                elif review_ratio >= 0.5:
                    score += 1
                    evidence.append("△ 大部分流水线变更经过 Code Review")
                else:
                    evidence.append("✗ 流水线变更未经过 Code Review")
            else:
                evidence.append("△ 未获取到流水线文件提交记录")

        if score >= 4:
            return self._scored(4, "流水线全面代码化，变更严格遵循 Code Review", evidence)
        elif score == 3:
            return self._scored(3, "流水线代码化管理良好，变更基本经过审核", evidence)
        elif score == 2:
            return self._scored(2, "流水线已实现代码化管理", evidence)
        elif score == 1:
            return self._scored(1, "流水线代码化管理初步建立", evidence)
        else:
            return self._not_scored("流水线代码化管理不完善", evidence)


# 导出所有分析器
CICD_ANALYZERS = [
    BuildAutomationAnalyzer(),
    TestAutomationAnalyzer(),
    DeploymentAutomationAnalyzer(),
    ReleaseManagementAnalyzer(),
    PipelineAsCodeAnalyzer(),
]
