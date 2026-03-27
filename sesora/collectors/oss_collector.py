import logging
from datetime import datetime
from typing import List, Optional

import oss2
from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema.rds_oss import (
    OssBucketRecord,
    OssBucketLifecycleRecord,
)

logger = logging.getLogger(__name__)


class OSSCollector(CollectorBase):
    def __init__(
        self, context: AssessmentContext, bucket_names: Optional[List[str]] = None
    ):
        self.context = context
        self.bucket_names = bucket_names
        self.client = self._create_client()
        # 缓存 Bucket 所在地域，用于后续操作
        self._bucket_locations: dict[str, str] = {}

    def _create_client(self):
        creds = self.context.aliyun_credentials
        auth = oss2.Auth(creds.get_access_key_id(), creds.get_access_key_secret())
        endpoint = f"oss-{self.context.region}.aliyuncs.com"
        return oss2.Service(auth, endpoint)

    def _get_bucket_names(self) -> List[str]:
        # 优先使用传入的 bucket_names
        if self.bucket_names:
            return self.bucket_names

        # 其次使用 context 中的 oss_bucket_names 列表
        if self.context.oss_bucket_names:
            return self.context.oss_bucket_names

        return []

    def name(self) -> str:
        return "oss_collector"

    def _collect(self) -> List:
        records: List = []

        bucket_names = self._get_bucket_names()

        if not bucket_names:
            # 采集所有 Bucket
            logger.info("开始采集所有 OSS Bucket...")
            bucket_names = self._collect_all_bucket_names()
        for bucket_name in bucket_names:
            bucket_record = self._collect_bucket_detail(bucket_name)
            records.append(bucket_record)
            logger.info(f"采集 Bucket: {bucket_name}")

            # 采集生命周期规则
            lifecycle_records = self._collect_bucket_lifecycle(bucket_name)
            if lifecycle_records:
                records.extend(lifecycle_records)
                logger.info(
                    f"采集生命周期规则: {bucket_name} ({len(lifecycle_records)} 条)"
                )

        bucket_count = sum(1 for r in records if isinstance(r, OssBucketRecord))
        lifecycle_count = sum(
            1 for r in records if isinstance(r, OssBucketLifecycleRecord)
        )
        logger.info(
            f"总计采集到 {bucket_count} 个 Bucket, {lifecycle_count} 条生命周期规则"
        )

        return records

    def _collect_all_bucket_names(self) -> List[str]:
        buckets = self.client.list_buckets()
        return [bucket.name for bucket in list(buckets.buckets)]

    def _get_bucket_endpoint(self, location: str) -> str:
        return f"{location}.aliyuncs.com"

    # TODO: remove these exceptions handling
    def _collect_bucket_detail(self, bucket_name: str) -> OssBucketRecord:
        # TODO: remove this duplicate auth
        creds = self.context.aliyun_credentials
        auth = oss2.Auth(creds.get_access_key_id(), creds.get_access_key_secret())

        # 首先使用默认 endpoint 获取 Bucket 信息（包含真实地域）
        default_endpoint = f"oss-{self.context.region}.aliyuncs.com"

        bucket = oss2.Bucket(auth, default_endpoint, bucket_name)

        # 获取 Bucket 信息
        try:
            bucket_info = bucket.get_bucket_info()
        except oss2.exceptions.AccessDenied as e:
            # 可能是跨区域访问，尝试从错误信息中提取正确的 endpoint
            error_details = getattr(e, "details", {}) or {}
            correct_endpoint = error_details.get("Endpoint", "")
            if correct_endpoint:
                logger.info(
                    f"检测到 Bucket 位于其他区域，切换到 endpoint: {correct_endpoint}"
                )
                bucket = oss2.Bucket(auth, correct_endpoint, bucket_name)
                bucket_info = bucket.get_bucket_info()
            else:
                raise

        # 使用 Bucket 实际所在地域构建 endpoint
        bucket_location = bucket_info.location  # 如: oss-cn-hangzhou
        endpoint = self._get_bucket_endpoint(bucket_location)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)

        # 获取版本控制状态
        versioning_status = "Suspended"
        try:
            versioning_result = bucket.get_bucket_versioning()
            versioning_status = versioning_result.status or "Suspended"
        except Exception as error:
            logger.debug(f"获取版本控制状态失败 ({bucket_name}): {error}")
            pass

        # 获取加密配置
        encryption_enabled = False
        try:
            encryption_result = bucket.get_bucket_encryption()
            encryption_enabled = encryption_result.status == "Enabled"
        except Exception:
            # 加密配置不存在是正常的，静默处理
            pass

        # 获取标签
        tags = {}
        try:
            tag_result = bucket.get_bucket_tagging()
            # tag_set 是 TaggingRule 对象，tagging_rule 是字典
            if tag_result.tag_set and hasattr(tag_result.tag_set, "tagging_rule"):
                tags = tag_result.tag_set.tagging_rule
        except Exception:
            pass

        self._bucket_locations[bucket_name] = bucket_info.location

        return OssBucketRecord(
            bucket_name=bucket_name,
            location=bucket_info.location,
            storage_class=bucket_info.storage_class,
            acl=bucket_info.acl.grant if bucket_info.acl else "private",
            versioning_status=versioning_status,
            redundancy_type=bucket_info.data_redundancy_type or "LRS",
            encryption_enabled=encryption_enabled,
            tags=tags,
        )

    def _collect_bucket_lifecycle(
        self, bucket_name: str
    ) -> List[OssBucketLifecycleRecord]:
        records: List[OssBucketLifecycleRecord] = []

        try:
            creds = self.context.aliyun_credentials
            auth = oss2.Auth(creds.get_access_key_id(), creds.get_access_key_secret())

            # 使用缓存的地域信息，如果没有则使用默认地域
            bucket_location = self._bucket_locations.get(bucket_name)
            if bucket_location:
                endpoint = self._get_bucket_endpoint(bucket_location)
            else:
                endpoint = f"oss-{self.context.region}.aliyuncs.com"

            bucket = oss2.Bucket(auth, endpoint, bucket_name)

            lifecycle_result = bucket.get_bucket_lifecycle()

            for rule in lifecycle_result.rules:
                transitions = []
                if rule.transition:
                    for t in rule.transition:
                        transitions.append(
                            {"days": t.days, "storage_class": t.storage_class}
                        )

                record = OssBucketLifecycleRecord(
                    bucket_name=bucket_name,
                    rule_id=rule.id,
                    status=rule.status,
                    prefix=rule.prefix or "",
                    expiration_days=rule.expiration.days if rule.expiration else 0,
                    transitions=transitions,
                    abort_multipart_upload_days=(
                        rule.abort_multipart_upload.days
                        if rule.abort_multipart_upload
                        else 0
                    ),
                    noncurrent_version_expiration_days=(
                        rule.noncurrent_version_expiration.noncurrent_days
                        if rule.noncurrent_version_expiration
                        else 0
                    ),
                )
                records.append(record)

            return records

        except oss2.exceptions.NoSuchLifecycle:
            return []
