from datetime import datetime
from typing import List

from alibabacloud_cr20181201 import models as cr_models
from alibabacloud_cr20181201.client import Client as CRClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.context import AssessmentContext
from sesora.core.dataitem import DataSource
from sesora.schema.acr import (
    AcrRepositoryRecord,
    AcrImageRecord,
    AcrScanResultRecord,
)


class ACRCollector:
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.instance_ids = context.acr_instance_ids
        self.otel_only = context.otel_only
        self.client = self._create_client()

    def _create_client(self) -> CRClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint=f"cr.{self.context.region}.aliyuncs.com",
            protocol="https",
        )
        return CRClient(config)

    def _get_instance_ids(self) -> List[str]:
        if self.instance_ids:
            return self.instance_ids
        print("未配置 ACR 实例 ID，尝试通过 ListInstance API 自动获取...")
        return self._list_instances_via_api()

    def _list_instances_via_api(self) -> List[str]:
        instance_ids: List[str] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.list_instance(
                cr_models.ListInstanceRequest(
                    instance_status="RUNNING",
                    page_size=page_size,
                    page_no=page_no,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.is_success:
                raise Exception("ListInstance API 调用失败")

            for instance in body.instances:
                instance_id = instance.instance_id
                instance_ids.append(instance_id)
                print(f"  获取到 ACR 实例 ID: {instance_id}")

            total_count = body.total_count
            if len(instance_ids) >= total_count:
                break
            page_no += 1

        return instance_ids

    def collect(self) -> DataSource:
        records: List = []

        instance_ids = self._get_instance_ids()

        if not instance_ids:
            return DataSource(
                collector="acr_collector",
                collected_at=datetime.now(),
                status="not_configured",
                records=[],
            )

        for instance_id in instance_ids:
            print(f"\n开始采集 ACR 实例: {instance_id}")
            instance_records = self._collect_instance(instance_id)
            records.extend(instance_records)

        print(f"\n总计采集到 {len(records)} 条记录")

        return DataSource(
            collector="acr_collector",
            collected_at=datetime.now(),
            status="ok",
            records=records,
        )

    def _collect_instance(self, instance_id: str) -> List:
        records: List = []

        repositories = self._collect_repositories(instance_id)
        records.extend(repositories)
        print(f"  采集到 {len(repositories)} 个镜像仓库")

        for repo in repositories:
            repo_id = repo.repo_id
            repo_name = repo.repo_name

            images = self._collect_images(instance_id, repo_id, repo_name)
            records.extend(images)

            for image in images:  # TODO: remove this limit?
                print(f"    仓库 {repo_name}: 采集镜像 {image.tag}")
                scan_result = self._collect_scan_result(instance_id, repo_id, image.tag)
                records.append(scan_result)

        return records

    def _collect_repositories(self, instance_id: str) -> List[AcrRepositoryRecord]:
        total_records = 0  # TODO: remove this
        records: List[AcrRepositoryRecord] = []
        page_no = 1
        page_size = 100

        while True:
            response = self.client.list_repository(
                cr_models.ListRepositoryRequest(
                    instance_id=instance_id, page_size=page_size, page_no=page_no
                )
            )
            body = response.body
            if response.status_code != 200 or not body.is_success:
                raise Exception("ListRepository API 调用失败")

            for repo in body.repositories:
                record = self._parse_repository(repo)
                # TODO: remove this
                if any(
                    keyword in repo.repo_name for keyword in ["otel", "opentelemetry"]
                ):
                    records.append(record)
                total_records += 1

            total_count = body.total_count

            if total_records >= int(total_count):
                break

            page_no += 1

        return records

    def _parse_repository(
        self,
        repo: cr_models.ListRepositoryResponseBodyRepositories,
    ) -> AcrRepositoryRecord:
        return AcrRepositoryRecord(
            instance_id=repo.instance_id,
            repo_id=repo.repo_id,
            repo_name=repo.repo_name,
            repo_namespace=repo.repo_namespace_name,
            repo_type=repo.repo_type,
            summary=repo.summary,
            create_time=datetime.fromtimestamp(int(repo.create_time) / 1000),
            update_time=datetime.fromtimestamp(int(repo.modified_time) / 1000),
        )

    def _collect_images(
        self, instance_id: str, repo_id: str, repo_name: str
    ) -> List[AcrImageRecord]:
        records: List[AcrImageRecord] = []

        page_no = 1
        page_size = 100
        while True:
            response = self.client.list_repo_tag(
                cr_models.ListRepoTagRequest(
                    instance_id=instance_id,
                    repo_id=repo_id,
                    page_size=page_size,
                    page_no=page_no,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.is_success:
                raise Exception("ListRepoTag API 调用失败")

            for image in response.body.images:
                record = self._parse_image(image, instance_id, repo_id)
                records.append(record)

            total_count = body.total_count
            if len(records) >= int(total_count):
                break
            page_no += 1

        return records

    def _parse_image(
        self,
        image: cr_models.ListRepoTagResponseBodyImages,
        instance_id: str,
        repo_id: str,
    ) -> AcrImageRecord:
        return AcrImageRecord(
            instance_id=instance_id,
            repo_id=repo_id,
            image_id=image.image_id,
            digest=image.digest,
            tag=image.tag,
            size=image.image_size,
            push_time=datetime.fromtimestamp(int(image.image_create) / 1000),
        )

    def _collect_scan_result(
        self,
        instance_id: str,
        repo_id: str,
        tag: str,
    ) -> AcrScanResultRecord:
        high_count = 0
        medium_count = 0
        low_count = 0
        unknown_count = 0
        vulnerabilities_num = 0

        page_no = 1
        page_size = 100
        while True:
            response = self.client.list_repo_tag_scan_result(
                cr_models.ListRepoTagScanResultRequest(
                    instance_id=instance_id,
                    repo_id=repo_id,
                    tag=tag,
                    page_size=page_size,
                    page_no=page_no,
                )
            )
            body = response.body
            if response.status_code != 200 or not body.is_success:
                print(f"ListRepoTagScanResult API 调用失败")
                # TODO: better way?
                break  # Internal server error may happen, just skip 

            for vuln in body.vulnerabilities:
                severity = vuln.severity.lower()
                if severity == "high":
                    high_count += 1
                elif severity == "medium":
                    medium_count += 1
                elif severity == "low":
                    low_count += 1
                else:
                    unknown_count += 1

            vulnerabilities_num += len(body.vulnerabilities)
            total_count = body.total_count or 0  # total_count may be None
            if vulnerabilities_num >= total_count:
                break

            page_no += 1

        return AcrScanResultRecord(
            instance_id=instance_id,
            repo_id=repo_id,
            tag=tag,
            high_severity_count=high_count,
            medium_severity_count=medium_count,
            low_severity_count=low_count,
            unknown_severity_count=unknown_count,
        )
