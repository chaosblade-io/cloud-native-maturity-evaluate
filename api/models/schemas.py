"""
Pydantic 数据模型定义

定义 API 请求和响应的数据结构
"""
from typing import Optional, Any
from pydantic import BaseModel, Field


# ============================================
# 通用响应模型
# ============================================

class BaseResponse(BaseModel):
    """通用响应基类"""
    success: bool = True
    message: str = ""
    

class DataResponse(BaseResponse):
    """带数据的响应"""
    data: Any = None


class KnowledgeDoc(BaseModel):
    """知识库文档"""
    id: str
    name: str
    title: str
    tags: list[str] = []
    size: int = 0
    created_at: str = ""
    updated_at: str = ""


class KnowledgeDocTagsRequest(BaseModel):
    """知识库文档标签更新请求"""
    tags: list[str] = Field(default=[], description="文档标签列表")


class KnowledgeDocsResponse(BaseResponse):
    """知识库文档列表响应"""
    docs: list[KnowledgeDoc] = []


class KnowledgeDocResponse(BaseResponse):
    """单个知识库文档响应"""
    doc: Optional[KnowledgeDoc] = None


# ============================================
# 配置相关模型
# ============================================

class ConfigItem(BaseModel):
    """单个配置项"""
    key: str
    value: str = ""
    description: str = ""
    required: bool = False
    group: str = "其他"


class ConfigGroup(BaseModel):
    """配置分组"""
    name: str
    description: str = ""
    items: list[ConfigItem] = []


class ConfigData(BaseModel):
    """完整配置数据"""
    # 阿里云基础凭证
    ALIBABA_CLOUD_ACCESS_KEY_ID: str = ""
    ALIBABA_CLOUD_ACCESS_KEY_SECRET: str = ""
    ALIBABA_CLOUD_ACCOUNT_ID: str = ""
    ALIBABA_CLOUD_SECURITY_TOKEN: str = ""
    ALIBABA_CLOUD_REGION: str = "cn-hongkong"
    
    # ACK 容器服务配置
    ACK_CLUSTER_ID: str = ""
    ACK_NAMESPACES: str = ""
    KUBECONFIG_PATHS: str = ""
    KUBECONFIG_CONTEXT: str = ""
    
    # ARMS APM 配置
    ARMS_WORKSPACE_ID: str = ""
    
    # ROS 资源编排配置
    ROS_STACK_NAME: str = ""
    ROS_REGION: str = ""
    
    # SLS 日志服务配置
    SLS_PROJECT: str = ""
    SLS_LOGSTORES: str = ""
    SLS_REGION: str = ""
    
    # 云效 Codeup 配置
    YUNXIAO_TOKEN: str = ""
    CODEUP_ORG_ID: str = ""
    CODEUP_REPO_IDS: str = ""
    CODEUP_PIPELINE_IDS: str = ""
    CODEUP_PROJECT_NAME: str = ""
    
    # 函数计算 FC 配置
    FC_FUNCTION_NAMES: str = ""
    
    # EventBridge 配置
    EVENTBRIDGE_BUS_NAMES: str = ""
    
    # RDS 数据库配置
    RDS_INSTANCE_IDS: str = ""
    RDS_REGION: str = ""
    
    # OSS 对象存储配置
    OSS_BUCKET_NAMES: str = ""
    OSS_REGION: str = ""
    
    # ACR 容器镜像服务配置
    ACR_INSTANCE_IDS: str = ""
    ACR_OTEL_ONLY: str = "true"
    
    # ALB 应用负载均衡配置
    ALB_LOAD_BALANCER_IDS: str = ""
    
    # ECS 云服务器配置
    ECS_REGION: str = ""
    
    # GTM 全局流量管理配置
    GTM_INSTANCE_ID: str = ""
    
    # Grafana 配置
    GRAFANA_WORKSPACE_ID: str = ""
    GRAFANA_URL: str = ""
    GRAFANA_API_TOKEN: str = ""
    GRAFANA_FOLDER_IDS: str = ""
    GRAFANA_TAGS: str = ""
    
    # Tair/Redis 配置
    TAIR_INSTANCE_IDS: str = ""


class ConfigCheckResponse(BaseResponse):
    """配置检查响应"""
    exists: bool = False
    has_credentials: bool = False


class ConfigResponse(BaseResponse):
    """配置响应"""
    config: Optional[ConfigData] = None
    groups: list[ConfigGroup] = []


# ============================================
# Mock 数据相关模型
# ============================================

class MockUploadResponse(BaseResponse):
    """Mock 数据上传响应"""
    items_count: int = 0
    records_count: int = 0
    items: dict[str, int] = {}  # DataItem名称 -> 记录数


# ============================================
# 数据采集相关模型
# ============================================

class CollectorInfo(BaseModel):
    """采集器信息"""
    name: str
    label: str
    description: str = ""
    requires_config: list[str] = []


class CollectRequest(BaseModel):
    """采集请求"""
    collectors: list[str] = Field(default=[], description="要执行的采集器列表，空列表表示全部")


class CollectResult(BaseModel):
    """单个采集器结果"""
    collector: str
    success: bool
    records_count: int = 0
    message: str = ""
    elapsed_seconds: float = 0


class CollectResponse(BaseResponse):
    """采集响应"""
    results: list[CollectResult] = []
    total_success: int = 0
    total_failed: int = 0


# ============================================
# 分析评估相关模型
# ============================================

class AnalyzerInfo(BaseModel):
    """分析器信息"""
    key: str
    dimension: str
    category: str
    max_score: int
    required_data: list[str] = []
    optional_data: list[str] = []


class AnalyzeRequest(BaseModel):
    """分析请求"""
    keys: list[str] = Field(default=[], description="要执行的分析器 key 列表，空列表表示全部")
    agent_assist: bool = Field(default=False, description="是否启用 Agent 辅助评估")
    agent_assist_keys: list[str] = Field(default=[], description="启用 Agent 辅助的 key 列表，空列表表示不额外限定")
    agent_assist_temperature: Optional[float] = Field(default=None, description="Agent 辅助评估温度参数")
    incremental: bool = Field(default=False, description="是否启用增量评估模式")


class AnalyzeResult(BaseModel):
    """单个分析结果"""
    key: str
    dimension: str
    category: str
    state: str  # scored, not_scored, not_evaluated
    score: int
    max_score: int
    percentage: float
    reason: str
    evidence: list[str] = []
    ai_assisted: bool = False


class DimensionSummary(BaseModel):
    """维度汇总"""
    dimension: str
    score: int
    max_score: int
    percentage: float
    maturity_level: str
    count: int


class IncrementalInfo(BaseModel):
    """增量评估信息"""
    mode: str = "full"  # full | incremental
    dirty_dataitems: list[str] = []
    recomputed_keys: list[str] = []
    cached_keys: list[str] = []


class AnalyzeResponse(BaseResponse):
    """分析响应"""
    results: list[AnalyzeResult] = []
    summary: list[DimensionSummary] = []
    total_score: int = 0
    total_max_score: int = 0
    total_percentage: float = 0
    overall_maturity: str = ""
    incremental_info: Optional[IncrementalInfo] = None


class GuidanceRequest(BaseModel):
    """初始改进建议请求"""
    keys: list[str] = Field(default=[], description="要纳入建议生成的分析器 key 列表，空列表表示全部")
    focus_keys: list[str] = Field(default=[], description="显式指定首轮聚焦的评估项 key 列表")
    max_focus: int = Field(default=6, description="每轮最多聚焦的评估项数量")
    max_dataitems: int = Field(default=12, description="每轮最多附带的数据项数量")
    max_records: int = Field(default=3, description="每个数据项最多附带的样本记录数")
    temperature: float = Field(default=0.1, description="建议生成温度参数")
    api_key: Optional[str] = Field(default=None, description="覆盖环境变量 API_KEY")
    base_url: Optional[str] = Field(default=None, description="覆盖环境变量 BASE_URL")
    model_name: Optional[str] = Field(default=None, description="覆盖环境变量 MODEL_NAME")
    agent_assist: bool = Field(default=False, description="是否启用 Agent 辅助评估")
    agent_assist_keys: list[str] = Field(default=[], description="启用 Agent 辅助的 key 列表")
    agent_assist_temperature: Optional[float] = Field(default=None, description="Agent 辅助评估温度参数")
    knowledge_doc_ids: list[str] = Field(default=[], description="知识库文档 ID 列表")
    external_knowledge_max_chars: int = Field(default=12000, description="每轮外部知识总字符上限")
    external_knowledge_max_chunks: int = Field(default=12, description="每轮外部知识最大片段数")
    external_knowledge_chunk_chars: int = Field(default=800, description="单个外部知识片段字符上限")


class GuidanceRefineRequest(BaseModel):
    """改进建议 refinement 请求"""
    session: dict[str, Any] = Field(default_factory=dict, description="前一轮 guidance session")
    feedback: str = Field(default="", description="用户反馈")
    db_name: Optional[str] = Field(default=None, description="覆盖 session 中的数据库名称")
    max_focus: Optional[int] = Field(default=None, description="覆盖 session 的聚焦项数量")
    max_dataitems: Optional[int] = Field(default=None, description="覆盖 session 的数据项数量")
    max_records: Optional[int] = Field(default=None, description="覆盖 session 的样本记录数量")
    temperature: Optional[float] = Field(default=None, description="覆盖 session 的温度参数")
    api_key: Optional[str] = Field(default=None, description="覆盖环境变量 API_KEY")
    base_url: Optional[str] = Field(default=None, description="覆盖环境变量 BASE_URL")
    model_name: Optional[str] = Field(default=None, description="覆盖环境变量 MODEL_NAME")
    knowledge_doc_ids: Optional[list[str]] = Field(default=None, description="覆盖 session 的知识库文档 ID 列表")
    external_knowledge_max_chars: Optional[int] = Field(default=None, description="覆盖 session 的外部知识总字符上限")
    external_knowledge_max_chunks: Optional[int] = Field(default=None, description="覆盖 session 的外部知识最大片段数")
    external_knowledge_chunk_chars: Optional[int] = Field(default=None, description="覆盖 session 的单片段字符上限")


class GuidanceResponse(BaseResponse):
    """改进建议响应"""
    session: dict[str, Any] = Field(default_factory=dict)
    current_turn: dict[str, Any] = Field(default_factory=dict)


class DataItemStatus(BaseModel):
    """数据项状态"""
    name: str
    available: bool
    records_count: int = 0


class DataStatusResponse(BaseResponse):
    """数据状态响应"""
    items: list[DataItemStatus] = []
    required: list[DataItemStatus] = []
    optional: list[DataItemStatus] = []


__all__ = [
    "BaseResponse",
    "DataResponse",
    "KnowledgeDoc",
    "KnowledgeDocTagsRequest",
    "KnowledgeDocsResponse",
    "KnowledgeDocResponse",
    "ConfigItem",
    "ConfigGroup",
    "ConfigData",
    "ConfigCheckResponse",
    "ConfigResponse",
    "MockUploadResponse",
    "CollectorInfo",
    "CollectRequest",
    "CollectResult",
    "CollectResponse",
    "AnalyzerInfo",
    "AnalyzeRequest",
    "AnalyzeResult",
    "DimensionSummary",
    "AnalyzeResponse",
    "GuidanceRequest",
    "GuidanceRefineRequest",
    "GuidanceResponse",
    "DataItemStatus",
    "DataStatusResponse",
]
