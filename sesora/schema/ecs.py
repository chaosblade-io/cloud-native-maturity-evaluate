"""
ECS (云服务器) 相关 DataItem Record 类型定义
数据来源：阿里云 ECS
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass
class EcsInstanceRecord:
    """ECS 实例记录"""
    instance_id: str
    instance_name: str
    instance_type: str  # ecs.g7.xlarge 等
    status: str  # Running/Stopped/Starting/Stopping
    region_id: str
    zone_id: str
    vpc_id: str = ""
    vswitch_id: str = ""
    private_ip: str = ""
    public_ip: str = ""
    cpu: int = 0
    memory: int = 0  # MB
    os_name: str = ""
    os_type: str = "linux"  # linux/windows
    image_id: str = ""
    instance_charge_type: str = "PostPaid"  # PrePaid/PostPaid
    internet_charge_type: str = ""
    internet_max_bandwidth_out: int = 0
    internet_max_bandwidth_in: int = 0
    creation_time: Optional[datetime] = None
    expired_time: Optional[datetime] = None
    tags: dict[str, str] = field(default_factory=dict)
    security_group_ids: list[str] = field(default_factory=list)


@dataclass
class EcsSecurityGroupRecord:
    """ECS 安全组记录"""
    security_group_id: str
    security_group_name: str
    vpc_id: str = ""
    description: str = ""
    security_group_type: str = "normal"  # normal/enterprise
    create_time: Optional[datetime] = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class EcsSecurityGroupRuleRecord:
    """ECS 安全组规则记录"""
    security_group_id: str
    direction: Literal["ingress", "egress"]
    ip_protocol: str  # TCP/UDP/ICMP/GRE/ALL
    port_range: str  # 1/65535 或 22/22
    source_cidr_ip: str = ""
    dest_cidr_ip: str = ""
    source_group_id: str = ""
    dest_group_id: str = ""
    policy: str = "accept"  # accept/drop
    priority: int = 1
    nic_type: str = "intranet"  # internet/intranet
    description: str = ""
