from datetime import datetime, timedelta
from typing import List, Optional

from sesora.core.context import AssessmentContext
from sesora.core.dataitem import DataSource
from sesora.schema.codeup import (
    CodeupPipelineRecord,
    CodeupPipelineMetricsRecord,
    CodeupPipelineConfigRecord,
    CodeupPipelineStageRecord,
    CodeupPipelineRunRecord,
    CodeupRepoRecord,
    CodeupRepoFileTreeRecord,
    CodeupRepoTagRecord,
    CodeupCommitRecord,
    CodeupBranchRecord,
    CodeupFileCommitRecord,
)

from alibabacloud_devops20210625.client import Client as DevOpsClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_devops20210625 import models as devops_models
import json
import re
import yaml


class CodeupCollector:
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.token = self.context.yunxiao_token
        self.domain = "openapi-rdc.aliyuncs.com"
        # TODO: remove this project filter
        self.project = context.codeup_project_name
        self.client = self._create_client()

    def _create_client(self) -> DevOpsClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            protocol="https",
            endpoint=f"devops.cn-hangzhou.aliyuncs.com",
        )
        return DevOpsClient(config)

    def collect(self) -> DataSource:
        records: List = []
        status = "ok"

        # 检查 Token 是否配置
        if not self.token:
            print("错误: 未配置云效 Token，请设置 YUNXIAO_TOKEN 环境变量")
            return DataSource(
                collector="codeup_collector",
                collected_at=datetime.now(),
                status="not_configured",
                records=[],
            )

        try:
            # 获取组织 ID 列表
            org_ids = self._get_organization_ids()

            if not org_ids:
                print("警告: 未配置组织 ID，请设置 codeup_org_id 或 CODEUP_ORG_ID")
                return DataSource(
                    collector="codeup_collector",
                    collected_at=datetime.now(),
                    status="not_configured",
                    records=[],
                )

            # 为每个组织采集代码仓库
            for org_id in org_ids:
                print(f"正在采集组织 {org_id} 的代码仓库信息...")
                repos = self._collect_repos(org_id, self.project)
                records.extend(repos)

                for repo in repos:
                    print(f"正在采集仓库 {repo.repo_name} 的信息...")
                    file_tree = self._collect_repo_file_tree(
                        org_id, repo.repo_id, repo.repo_name
                    )
                    records.extend(file_tree)

                    print(f"正在采集仓库 {repo.repo_name} 的文件提交信息...")
                    file_commits = []
                    for file_tree_record in file_tree:
                        file_commit = self._calculate_file_last_commit(
                            file_tree_record.path, org_id, repo.repo_id
                        )
                        file_commits.append(file_commit)
                    records.extend(file_commits)

                    print(f"正在采集仓库 {repo.repo_name} 的标签信息...")
                    tags = self._collect_repo_tags(org_id, repo.repo_id)
                    records.extend(tags)
                    print(f"    采集到仓库 {repo.repo_name} 的 {len(tags)} 个标签")

                    print(f"正在采集仓库 {repo.repo_name} 的分支信息...")
                    branches = self._collect_repo_branches(org_id, repo.repo_id)
                    records.extend(branches)
                    print(f"    采集到仓库 {repo.repo_name} 的 {len(branches)} 个分支")

                    print(f"正在采集仓库 {repo.repo_name} 的提交信息...")
                    commits = self._collect_repo_commits(org_id, repo.repo_id)
                    records.extend(commits)
                    print(
                        f"    采集到仓库 {repo.repo_name} 的 {len(commits)} 条提交记录"
                    )

                print(f"正在采集组织 {org_id} 的流水线信息...")
                pipelines = self._collect_pipelines(org_id)
                records.extend(pipelines)
                print(f"  采集到 {len(pipelines)} 条流水线")

                # 采集流水线配置详情
                for pipeline in pipelines:
                    config_records = self._collect_pipeline_config(
                        org_id, pipeline.pipeline_id
                    )
                    records.extend(config_records)
                    print(f"    采集到流水线 {pipeline.name} 的配置信息")

                # 采集流水线运行记录和指标
                for pipeline in pipelines:
                    run_records = self._collect_pipeline_runs(
                        org_id, pipeline.pipeline_id, pipeline.name
                    )
                    records.extend(run_records)
                    print(
                        f"    采集到流水线 {pipeline.name} 的 {len(run_records)} 条运行记录"
                    )

        except Exception as e:
            status = "error"
            print(f"Codeup 采集失败: {e}")

        return DataSource(
            collector="codeup_collector",
            collected_at=datetime.now(),
            status=status,
            records=records,
        )

    def _get_organization_ids(self) -> List[str]:
        org_ids = []

        # 从 context 获取
        if self.context.codeup_org_id:
            # 支持逗号分隔的多个组织 ID
            org_ids = [
                oid.strip()
                for oid in self.context.codeup_org_id.split(",")
                if oid.strip()
            ]

        return org_ids

    def _collect_repos(self, org_id: str, repo_name: str) -> List[CodeupRepoRecord]:
        records: List[CodeupRepoRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.list_repositories(
                devops_models.ListRepositoriesRequest(
                    access_token=self.token,
                    organization_id=org_id,
                    page=page_no,
                    per_page=page_size,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取仓库列表失败 (org_id={org_id}, page={page_no})")

            repos = body.result
            for repo in repos:
                record = self._collect_repo_info(org_id, str(repo.id))
                if record.repo_name != repo_name:  # TODO: remove this
                    continue
                records.append(record)

            if page_no * page_size >= body.total:
                break
            page_no += 1

        return records

    def _collect_repo_info(self, org_id: str, repo_id: str) -> CodeupRepoRecord:
        response = self.client.get_repository(
            devops_models.GetRepositoryRequest(
                access_token=self.token,
                identity=repo_id,
                organization_id=org_id,
            ),
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            raise Exception(f"获取仓库信息失败 (repo_id={repo_id})")

        repo = body.repository
        return self._parse_repository(repo)

    def _parse_repository(
        self, repo: devops_models.GetRepositoryResponseBodyRepository
    ) -> CodeupRepoRecord:
        create_time = datetime.fromisoformat(repo.created_at.replace("Z", "+00:00"))
        visibility = "private" if repo.visibility_level == 0 else "public"
        return CodeupRepoRecord(
            repo_id=str(repo.id),
            repo_name=repo.name,
            namespace=repo.namespace.name,
            default_branch=repo.default_branch,
            visibility=visibility,
            create_time=create_time,
        )

    def _collect_repo_file_tree(
        self, org_id: str, repo_id: str, repo_name: str, path: str = "", ref: str = ""
    ) -> List[CodeupRepoFileTreeRecord]:
        records: List[CodeupRepoFileTreeRecord] = []

        response = self.client.list_repository_tree(
            repo_id,
            devops_models.ListRepositoryTreeRequest(
                access_token=self.token,
                organization_id=org_id,
                type="RECURSIVE",
            ),
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            raise Exception(f"获取文件树失败 (repo_id={repo_id}, path={path})")

        files = body.result
        for file in files:
            record = self._parse_file_tree_item(file, repo_name)
            records.append(record)

        return records

    def _parse_file_tree_item(
        self,
        file_info: devops_models.ListRepositoryTreeResponseBodyResult,
        repo_name: str,
    ) -> Optional[CodeupRepoFileTreeRecord]:
        return CodeupRepoFileTreeRecord(
            repo_id=file_info.id,
            repo_name=repo_name,
            path=file_info.path,
            type="file" if file_info.type == "blob" else "directory",
            name=file_info.name,
        )

    def _collect_repo_tags(
        self, org_id: str, repo_id: str
    ) -> List[CodeupRepoTagRecord]:
        records: List[CodeupRepoTagRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.list_repository_tags(
                repo_id,
                devops_models.ListRepositoryTagsRequest(
                    access_token=self.token,
                    organization_id=org_id,
                    page=page_no,
                    page_size=page_size,
                ),
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取标签列表失败 (repo_id={repo_id}, page={page_no})")

            tags = body.result
            for tags in tags:
                record = self._parse_tag(tags, repo_id)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_tag(
        self,
        tag: devops_models.ListRepositoryTagsResponseBodyResult,
        repo_id: str,
    ) -> CodeupRepoTagRecord:
        tag_name = tag.name

        # 获取提交信息
        commit_info = tag.commit
        commit_id = commit_info.id

        # 解析标签消息
        message = tag.message

        # 检查是否符合 SemVer 规范（简化检查）
        is_semver = self._is_semver_tag(tag_name)

        # 解析创建时间
        create_time = datetime.fromisoformat(
            commit_info.committed_date.replace("Z", "+00:00")
        )

        # 获取创建者
        created_by = commit_info.committer_name

        return CodeupRepoTagRecord(
            repo_id=repo_id,
            tag_name=tag_name,
            commit_id=commit_id,
            message=message,
            is_semver=is_semver,
            create_time=create_time,
            created_by=created_by,
        )

    def _is_semver_tag(self, version: str) -> bool:
        # 移除可能的前缀（如 v, release- 等）
        for prefix in ["v", "V", "release-", "RELEASE-"]:
            if version.startswith(prefix):
                version = version[len(prefix) :]
                break
        # SemVer 正则: major.minor.patch[-prerelease][+build]
        semver_pattern = r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
        return bool(re.match(semver_pattern, version))

    def _collect_repo_branches(
        self, org_id: str, repo_id: str
    ) -> List[CodeupBranchRecord]:
        records: List[CodeupBranchRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.list_repository_branches(
                repo_id,
                devops_models.ListRepositoryBranchesRequest(
                    access_token=self.token,
                    organization_id=org_id,
                    page=page_no,
                    page_size=page_size,
                ),
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取分支列表失败 (repo_id={repo_id}, page={page_no})")

            branches = body.result
            for branch in branches:
                record = self._parse_branch(branch, repo_id)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_branch(
        self,
        branch: devops_models.ListRepositoryBranchesResponseBodyResult,
        repo_id: str,
    ) -> CodeupBranchRecord:
        branch_name = branch.name

        # 获取是否为默认分支和保护分支
        is_protected = branch.protected == "true"

        # 获取最近一次提交信息
        commit_info = branch.commit
        commit_id = commit_info.id

        # 解析提交时间
        commit_time = datetime.fromisoformat(
            commit_info.committed_date.replace("Z", "+00:00")
        )

        return CodeupBranchRecord(
            repo_id=str(repo_id),
            branch_name=branch_name,
            is_protected=is_protected,
            commit_id=commit_id,
            commit_time=commit_time,
        )

    def _collect_repo_commits(
        self,
        org_id: str,
        repo_id: str,
    ) -> List[CodeupCommitRecord]:
        records: List[CodeupCommitRecord] = []

        page_no = 1
        page_size = 100

        while True:
            response = self.client.list_repository_commits(
                repo_id,
                devops_models.ListRepositoryCommitsRequest(
                    access_token=self.token,
                    organization_id=org_id,
                    page=page_no,
                    page_size=page_size,
                    ref_name="main",  # TODO: get default branch from repo info
                ),
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取提交记录失败 (repo_id={repo_id}, page={page_no})")

            commits = body.result
            for commit in commits:
                record = self._parse_commit(commit, repo_id)
                records.append(record)

            total_count = body.total
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _calculate_file_last_commit(
        self, file_path: str, org_id: str, repo_id: str
    ) -> CodeupFileCommitRecord:
        response = self.client.get_file_last_commit(
            repo_id,
            devops_models.GetFileLastCommitRequest(
                access_token=self.token,
                file_path=file_path,
                organization_id=org_id,
                sha="main",  # TODO: get default branch from repo info
            ),
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            raise Exception(
                f"获取文件最后一次提交失败 (repo_id={repo_id}, file_path={file_path})"
            )

        result = body.result
        return CodeupFileCommitRecord(
            repo_id=repo_id,
            file_path=file_path,
            commit_id=result.id,
            author_name=result.author_name,
            author_email=result.author_email,
            commit_message=result.message,
            commit_time=datetime.fromisoformat(
                result.committed_date.replace("Z", "+00:00")
            ),
            # TODO: this check is incorrect, need to rafactor
            has_merge_request=len(result.parent_ids) > 1,
        )

    @staticmethod
    def _parse_commit(
        commit: devops_models.ListRepositoryCommitsResponseBodyResult, repo_id: str
    ) -> CodeupCommitRecord:
        commit_id = commit.id

        # 获取提交信息
        message = commit.message
        title = commit.title

        # 获取作者信息
        author_name = commit.author.name
        author_email = commit.author.email

        # 获取提交者信息
        committer_name = commit.committer.name
        committer_email = commit.committer.email

        # 解析时间
        author_time = datetime.fromisoformat(
            commit.authored_date.replace("Z", "+00:00")
        )
        commit_time = datetime.fromisoformat(
            commit.committed_date.replace("Z", "+00:00")
        )

        # 获取父提交 ID
        parent_ids = commit.parent_ids

        # 判断是否通过 MR 流程（简化判断：有多个父提交可能是 MR）
        # TODO: this check is incorrect, need to rafactor
        has_merge_request = len(parent_ids) > 1  # TODO:

        return CodeupCommitRecord(
            repo_id=repo_id,
            commit_id=commit_id,
            message=message or title,  # TODO: 区分两者
            author_name=author_name,
            author_email=author_email,
            author_time=author_time,
            committer_name=committer_name,
            committer_email=committer_email,
            commit_time=commit_time,
            parent_ids=parent_ids,
            has_merge_request=has_merge_request,
        )

    def _collect_pipelines(self, org_id: str) -> List[CodeupPipelineRecord]:
        records: List[CodeupPipelineRecord] = []

        next_token = None
        while True:
            response = self.client.list_pipelines(
                org_id,
                devops_models.ListPipelinesRequest(
                    max_results=100,
                    next_token=next_token,
                ),
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(f"获取流水线列表失败 (org_id={org_id})")

            for pipeline in body.pipelines:
                record = self._parse_pipeline(pipeline)
                if self.project:
                    pipeline_id = pipeline.pipeline_id
                    if not self._is_pipeline_in_project(org_id, str(pipeline_id)):
                        continue
                records.append(record)

            next_token = body.next_token
            if not next_token:
                break

        return records

    def _parse_pipeline(
        self, pipeline: devops_models.ListPipelinesResponseBodyPipelines
    ) -> CodeupPipelineRecord:
        create_time = datetime.fromtimestamp(pipeline.create_time / 1000)
        return CodeupPipelineRecord(
            pipeline_id=str(pipeline.pipeline_id),
            name=pipeline.pipeline_name,
            repo_id="unknown",  # TODO: 需要通过 GetPipeline API 获取关联的 repo_id，目前列表接口没有返回
            create_time=create_time,
        )

    def _is_pipeline_in_project(self, org_id: str, pipeline_id: str) -> bool:
        # TODO: 此方法是临时实现，后续需要优化为更通用的过滤机制

        response = self.client.get_pipeline(
            org_id,
            pipeline_id,
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            print(f"获取流水线详情失败 (pipeline_id={pipeline_id})")
            return False

        data = body.pipeline
        sources = data.pipeline_config.sources
        for source in sources:
            source_data = source.data
            repo_url = source_data.repo

            # 从 repo URL 中提取 project/namespace
            # URL 格式: https://codeup.aliyun.com/{namespace}/{repo_name}.git
            if repo_url:
                # 移除 .git 后缀并分割路径
                repo_path = repo_url.replace(".git", "")
                parts = repo_path.split("/")
                if len(parts) >= 2:
                    namespace = parts[-1]
                    if namespace == self.project:
                        return True

        return False

    def _collect_pipeline_config(self, org_id: str, pipeline_id: str) -> List:
        response = self.client.get_pipeline(
            org_id,
            pipeline_id,
        )
        body = response.body
        if response.status_code != 200 or not body.success:
            raise Exception(
                f"获取流水线配置失败 (org_id={org_id}, pipeline_id={pipeline_id})"
            )

        return self._parse_pipeline_config(body.pipeline, pipeline_id)

    def _parse_pipeline_config(
        self,
        pipeline_data: devops_models.GetPipelineResponseBodyPipeline,
        pipeline_id: str,
    ) -> List:
        records = []

        pipeline_name = pipeline_data.name

        # 解析 pipelineConfig 获取触发器和阶段信息
        pipeline_config = pipeline_data.pipeline_config

        # 解析代码源信息获取 repo_id
        repo_id = ""
        sources = pipeline_config.sources
        for source in sources:
            source_data = source.data
            repo_url = source_data.repo
            # TODO: maybe we need to keep the whole repo URL
            # 格式如: https://codeup.aliyun.com/xxx/xxx.git
            repo_id = repo_url.split("/")[-1].replace(".git", "")

        # 解析触发器类型
        trigger_type = "manual"  # 默认手动触发
        trigger_config = {}
        auto_trigger_enabled = False

        for source in sources:
            source_data = source.data
            is_trigger = source_data.is_trigger
            events = source_data.events
            if is_trigger:
                auto_trigger_enabled = True
                if "push" in events:
                    trigger_type = "push"
                    trigger_config["push"] = {"branches": source_data.trigger_filter}
                # TODO: 可以扩展支持其他触发类型：mr, tag, schedule

        # 解析阶段定义（从 flow YAML 或配置中）
        flow_yaml = pipeline_config.flow
        records.extend(self._parse_stages_from_flow_detailed(flow_yaml, pipeline_id))

        # 解析环境变量
        env_vars = {}
        settings_str = pipeline_config.settings
        settings = json.loads(settings_str)
        env_vars = settings.get("env", {})

        # 解析创建时间和更新时间
        create_time = datetime.fromtimestamp(pipeline_data.create_time / 1000)
        update_time = datetime.fromtimestamp(pipeline_data.update_time / 1000)

        records.append(
            CodeupPipelineConfigRecord(
                pipeline_id=pipeline_id,
                pipeline_name=pipeline_name,
                repo_id=repo_id,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                auto_trigger_enabled=auto_trigger_enabled,
                env_vars=env_vars,
                create_time=create_time,
                update_time=update_time,
            )
        )

        return records

    def _parse_stages_from_flow_detailed(
        self, flow_yaml: str, pipeline_id: str
    ) -> List[CodeupPipelineStageRecord]:
        stages = []

        # 解析 YAML
        config = yaml.safe_load(flow_yaml)

        if not config or not isinstance(config, dict):
            return stages

        # 获取 pipeline 列表
        pipeline_stage_groups = config.get("pipeline", [])

        for order, stage_group in enumerate(pipeline_stage_groups):
            if not isinstance(stage_group, dict):
                continue

            stage_name = stage_group.get("name", f"Stage {order}")

            # 推断阶段类型
            stage_type = self._infer_stage_type(stage_group)

            # 检查各种步骤类型
            has_test_step = "test" in stage_type
            has_deploy_step = "deploy" in stage_type
            has_manual_gate = "manual_gate" in stage_type
            has_security_scan = "security_scan" in stage_type

            commands = [
                str([command["reconstructed_command"], command["raw_command"]])
                for command in self.extract_all_commands(stage_group)
            ]

            record = CodeupPipelineStageRecord(
                pipeline_id=str(pipeline_id),
                stage_name=stage_name,
                stage_type=stage_type,
                stage_order=order,
                commands=commands,
                has_test_step=has_test_step,
                has_deploy_step=has_deploy_step,
                has_manual_gate=has_manual_gate,
                has_security_scan=has_security_scan,
            )
            stages.append(record)

        return stages

    def _infer_stage_type(self, stage: dict) -> list[str]:
        """
        推断阶段类型
        """
        stage_group_name = stage.get("name", "").lower()

        stage_names = [
            job["displayName"].lower()
            for s in stage.get("stages", [])
            for job in s.get("jobs", [])
            if "displayName" in job
        ]
        stage_names.append(stage_group_name)

        types = set()
        for stage_name in stage_names:
            if any(
                keyword in stage_name
                for keyword in ["build", "构建", "编译", "package"]
            ):
                types.add("build")
            elif any(
                keyword in stage_name
                for keyword in ["test", "测试", "unittest", "pytest"]
            ):
                types.add("test")
            elif any(
                keyword in stage_name
                for keyword in ["deploy", "部署", "release", "发布", "helm"]
            ):
                types.add("deploy")
            elif any(
                keyword in stage_name
                for keyword in ["security", "安全", "scan", "扫描", "sonar"]
            ):
                types.add("security_scan")
            elif any(
                keyword in stage_name for keyword in ["gate", "审批", "manual", "人工"]
            ):
                types.add("manual_gate")

        return list(types)

    def extract_all_commands(self, stage_group):
        """
        遍历 stage_group 中的所有 jobs 和 steps，提取所有执行命令。
        """
        commands_log = []

        # 1. 遍历结构: stage_group -> stages -> jobs -> steps
        # 注意：根据你的数据结构，stage_group 直接包含 'stages' 列表，或者它本身就是 stages 列表
        stages_list = (
            stage_group.get("stages", [])
            if isinstance(stage_group, dict)
            else stage_group
        )

        for stage_idx, stage in enumerate(stages_list):
            jobs = stage.get("jobs", [])

            for job in jobs:
                job_name = job.get("displayName", "Unknown Job")
                params = job.get("params", {})
                steps = params.get("steps", [])

                if not steps:
                    continue

                for step in steps:
                    step_type = step.get("stepType", "Unknown")
                    step_name = step.get("name", "Unknown Step")

                    raw_cmd = None
                    reconstructed_cmd = None

                    # --- 情况 A: 显式的 Shell/Script 命令 ---
                    # 常见字段: command, script, inputs.script
                    if "command" in step:
                        raw_cmd = step["command"]
                    elif "script" in step:
                        raw_cmd = step["script"]
                    elif "inputs" in step and isinstance(step["inputs"], dict):
                        if "script" in step["inputs"]:
                            raw_cmd = step["inputs"]["script"]
                        elif "command" in step["inputs"]:
                            raw_cmd = step["inputs"]["command"]

                    # --- 情况 B: 插件类任务 (如 DockerBuildPushACREE_production) ---
                    # 这类任务没有直接的 "docker build" 字符串，需要 reconstruct (还原)
                    if not raw_cmd and step_type:
                        reconstructed_cmd = self._reconstruct_plugin_command(
                            step_type, step
                        )

                    # 记录结果
                    if raw_cmd or reconstructed_cmd:
                        commands_log.append(
                            {
                                "job": job_name,
                                "step": step_name,
                                "type": step_type,
                                "raw_command": raw_cmd,
                                "reconstructed_command": reconstructed_cmd,
                                "display_command": (
                                    raw_cmd if raw_cmd else reconstructed_cmd
                                ),
                            }
                        )

        return commands_log

    def _reconstruct_plugin_command(self, step_type, step_params):
        """
        根据 stepType 和参数，还原出大致的 Shell 命令。
        这是一个启发式函数，可以根据你的具体插件文档扩展。
        """
        cmd_parts = []

        # 示例：处理 Docker 构建插件
        if "DockerBuild" in step_type or "DockerPush" in step_type:
            docker_file = step_params.get("DOCKER_FILE_PATH", "Dockerfile")
            context = step_params.get("CONTEXT_PATH", ".")
            tag = step_params.get("DOCKER_TAG", "latest")
            namespace = step_params.get("DOCKER_NAMESPACE", "")
            repo = step_params.get("DOCKER_REPO", "")
            region = step_params.get("DOCKER_REGION", "cn-hangzhou")
            options = step_params.get("options", "")

            # 构造镜像地址 (假设阿里云 ACR 格式)
            # 实际地址逻辑可能需要根据 SERVICE_CONNECTION_ID 查询，这里做通用假设
            image_addr = f"{namespace}/{repo}:{tag}"
            if region:
                # 简化处理，实际需映射 region 到 registry 域名
                registry_domain = f"registry.cn-hangzhou.cr.aliyuncs.com"
                image_addr = f"{registry_domain}/{image_addr}"

            # 构建 build 命令
            build_cmd = (
                f"docker build -t {image_addr} -f {docker_file} {options} {context}"
            )
            cmd_parts.append(build_cmd)

            # 构建 push 命令 (如果插件包含 Push)
            if "Push" in step_type:
                cmd_parts.append(f"docker push {image_addr}")

            return " && ".join(cmd_parts)

        # 示例：处理 Helm 部署插件
        elif "Helm" in step_type:
            action = step_params.get("action", "upgrade")  # 假设有个 action 字段
            release_name = step_params.get("releaseName", "my-release")
            chart_path = step_params.get("chartPath", ".")
            values = step_params.get("valuesFile", "")

            cmd = f"helm {action} {release_name} {chart_path}"
            if values:
                cmd += f" -f {values}"
            return cmd

        # 其他未知插件，返回提示
        return f"[Plugin: {step_type}] Command logic not fully reconstructed. Check params: {list(step_params.keys())}"

    def _has_step_type(self, stage: list[str], keywords: List[str]) -> bool:
        """
        检查阶段是否包含特定类型的步骤

        Args:
            stage: 阶段类型列表
            keywords: 关键词列表

        Returns:
            bool: 是否包含
        """
        stages_list = stage.get("stages", [])

        for s in stages_list:
            jobs = s.get("jobs", [])
            for job in jobs:
                # 检查 task 名称
                task = job.get("task", "").lower()
                if any(kw in task for kw in keywords):
                    return True

                # 检查 steps 中的 stepType
                params = job.get("params", {})
                steps = params.get("steps", [])
                for step in steps:
                    step_type = step.get("stepType", "").lower()
                    step_name = step.get("name", "").lower()
                    if any(kw in step_type or kw in step_name for kw in keywords):
                        return True

        return False

    def _has_manual_gate(self, stage: dict) -> bool:
        """
        检查阶段是否包含人工审批

        Args:
            stage: 阶段配置字典

        Returns:
            bool: 是否包含人工审批
        """
        stages_list = stage.get("stages", [])

        for s in stages_list:
            # 检查 driven 类型
            driven = s.get("driven", "").upper()
            if driven == "MANUAL":
                return True

            # 检查 jobs
            jobs = s.get("jobs", [])
            for job in jobs:
                task = job.get("task", "").lower()
                if "gate" in task or "approve" in task or "manual" in task:
                    return True

        return False

    def _collect_pipeline_runs(
        self, org_id: str, pipeline_id: str, pipeline_name: str = ""
    ) -> List:
        records = []

        end_time = datetime.now()
        start_time = end_time - timedelta(days=30)
        end_time = int(end_time.timestamp() * 1000)
        start_time = int(start_time.timestamp() * 1000)

        next_token = None
        while True:
            response = self.client.list_pipeline_runs(
                org_id,
                pipeline_id,
                devops_models.ListPipelineRunsRequest(
                    start_time=start_time,
                    end_time=end_time,
                    max_results=30,
                    next_token=next_token,
                ),
            )
            body = response.body
            if response.status_code != 200 or not body.success:
                raise Exception(
                    f"获取流水线运行记录失败 (org_id={org_id}, pipeline_id={pipeline_id})"
                )

            for run in body.pipeline_runs:
                record = self._parse_pipeline_run(run, pipeline_id, pipeline_name)
                records.append(record)

            next_token = body.next_token
            if not next_token:
                break

        metrics = self._calculate_metrics(records, pipeline_id, pipeline_name)
        records.append(metrics)

        return records

    def _parse_pipeline_run(
        self,
        run: devops_models.ListPipelineRunsResponseBodyPipelineRuns,
        pipeline_id: str,
        pipeline_name: str,
    ) -> CodeupPipelineRunRecord:
        run_id = run.pipeline_run_id
        # 解析状态
        status_map = {
            "SUCCESS": "SUCCESS",
            "FAIL": "FAILED",
            "RUNNING": "RUNNING",
            "CANCEL": "CANCELLED",
            "WAITING": "PENDING",
        }
        raw_status = run.status
        status = status_map.get(raw_status, "PENDING")
        # 解析触发类型
        trigger_mode = run.trigger_mode
        trigger_type_map = {
            1: "MANUAL",
            2: "SCHEDULE",
            3: "WEBHOOK",
            5: "PIPELINE",
            6: "WEBHOOK",
        }
        trigger_type = trigger_type_map.get(trigger_mode, "MANUAL")
        # 解析时间
        start_time = datetime.fromtimestamp(run.start_time / 1000)
        end_time = datetime.fromtimestamp(run.end_time / 1000)
        duration_ms = run.end_time - run.start_time
        # 获取触发用户
        trigger_user = run.creator_account_id
        return CodeupPipelineRunRecord(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            run_id=str(run_id),
            status=status,
            trigger_type=trigger_type,
            trigger_user=trigger_user,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
        )

    def _calculate_metrics(
        self, runs: List[CodeupPipelineRunRecord], pipeline_id: str, pipeline_name: str
    ) -> CodeupPipelineMetricsRecord:
        run_count = len(runs)
        success_count = 0
        failure_count = 0
        total_duration_ms = 0
        valid_duration_count = 0

        for run in runs:
            # 统计成功/失败次数
            status = run.status
            if status == "SUCCESS":
                success_count += 1
            elif status == "FAIL":
                failure_count += 1

            # 计算耗时
            start_time = run.start_time
            end_time = run.end_time
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds() * 1000
                if duration > 0:
                    total_duration_ms += duration
                    valid_duration_count += 1

        # 计算平均耗时和成功率
        avg_duration_ms = (
            int(total_duration_ms / valid_duration_count)
            if valid_duration_count > 0
            else 0
        )
        success_rate = (success_count / run_count * 100) if run_count > 0 else 0.0

        return CodeupPipelineMetricsRecord(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            run_count_30d=run_count,
            success_count_30d=success_count,
            failure_count_30d=failure_count,
            avg_duration_ms=avg_duration_ms,
            success_rate=round(success_rate, 2),
        )
