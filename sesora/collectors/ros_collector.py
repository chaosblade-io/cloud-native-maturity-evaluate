from datetime import datetime
from typing import List

from alibabacloud_ros20190910.client import Client as RosClient
from alibabacloud_tea_openapi import models as open_api_models

from sesora.core.context import AssessmentContext
from sesora.core.collector import CollectorBase
from sesora.core.dataitem import DataSource
from sesora.schema import RosStackRecord, RosStackDriftRecord
from alibabacloud_ros20190910 import models as ros_models


class ROSCollector(CollectorBase):
    def __init__(self, context: AssessmentContext):
        self.context = context
        self.ros_stack_name = context.ros_stack_name
        self.ros_region = context.ros_region or context.region
        self.client = self._create_client()

    def _create_client(self) -> RosClient:
        creds = self.context.aliyun_credentials
        config = open_api_models.Config(
            credential=creds,
            endpoint="ros.aliyuncs.com",
            protocol="https",
        )
        return RosClient(config)

    def name(self) -> str:
        return "ros_collector"

    def _collect(self) -> List:
        records: List = []

        stacks = self._collect_stacks()
        records.extend(stacks)
        print(f"\n总计采集到 {len(stacks)} 个 ROS 资源栈")

        # 采集漂移检测信息
        print("\n开始采集漂移检测信息...")
        for stack in stacks:
            if stack.drift_status != "NOT_CHECKED":
                drift_record = self._collect_stack_drift(stack, stack.stack_name)
                records.append(drift_record)
                print(
                    f"  采集漂移信息: {stack.stack_name} - {drift_record.drift_status}"
                )

        return records

    def _collect_stacks(self) -> List[RosStackRecord]:
        records: List[RosStackRecord] = []

        page_no = 1
        page_size = 50

        while True:
            response = self.client.list_stacks(
                ros_models.ListStacksRequest(
                    region_id=self.ros_region,
                    stack_name=self.ros_stack_name,
                    page_number=page_no,
                    page_size=page_size,
                )
            )
            body = response.body
            if response.status_code != 200:
                raise Exception(f"ListStacks API 调用失败: {response.status_code}")
            for stack in body.stacks:
                record = self._parse_stack(stack)
                records.append(record)
                print(f"  采集资源栈: {record.stack_name} - 状态: {record.status}")

            total_count = body.total_count
            if len(records) >= total_count:
                break
            page_no += 1

        return records

    def _parse_stack(
        self, stack: ros_models.ListStacksResponseBodyStacks
    ) -> RosStackRecord:
        # 获取资源栈ID和名称
        stack_id = stack.stack_id
        stack_name = stack.stack_name

        # 解析创建时间
        create_time = datetime.fromisoformat(stack.create_time.replace("Z", "+00:00"))

        # 解析更新时间
        update_time = (
            datetime.fromisoformat(stack.update_time.replace("Z", "+00:00"))
            if stack.update_time
            else None
        )

        # 解析漂移检测时间
        drift_detection_time = (
            datetime.fromisoformat(stack.drift_detection_time.replace("Z", "+00:00"))
            if stack.drift_detection_time
            else None
        )

        # 解析标签
        tags = {}
        tags_data = stack.tags
        for tag in tags_data:
            tags[tag.key] = tag.value

        drift_status = stack.stack_drift_status or "NOT_CHECKED"

        return RosStackRecord(
            stack_id=stack_id,
            stack_name=stack_name,
            status=stack.status,
            create_time=create_time,
            update_time=update_time,
            timeout_in_minutes=stack.timeout_in_minutes,
            disable_rollback=stack.disable_rollback,
            deletion_protection=stack.deletion_protection,
            drift_detection_time=drift_detection_time,
            drift_status=drift_status,
            tags=tags,
        )

    def _collect_stack_drift(
        self, stack: RosStackRecord, stack_name: str
    ) -> RosStackDriftRecord:
        # 获取漂移状态
        drift_status = stack.drift_status

        # 解析漂移检测时间
        drift_detection_time = stack.drift_detection_time

        response = self.client.list_stack_resources(
            ros_models.ListStackResourcesRequest(
                stack_id=stack.stack_id, region_id=self.ros_region
            )
        )
        body = response.body
        if response.status_code != 200:
            raise Exception(f"ListStackResources API 调用失败: {response.status_code}")

        # 获取漂移的资源信息
        drifted_resources = []
        for resource in body.resources:
            resource_drift_status = resource.resource_drift_status
            if resource_drift_status == "DRIFTED":
                resource_info = {
                    "resource_type": resource.resource_type,
                    "drift_status": resource_drift_status,
                }
                drifted_resources.append(resource_info)

        # 统计资源数量
        total_resources = len(body.resources)
        drifted_count = len(drifted_resources)

        return RosStackDriftRecord(
            stack_id=stack.stack_id,
            stack_name=stack_name,
            drift_status=drift_status,
            drift_detection_time=drift_detection_time,
            drifted_resources=drifted_resources,
            total_resources=total_resources,
            drifted_count=drifted_count,
        )
