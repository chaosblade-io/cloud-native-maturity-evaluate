# SESORA - 云原生架构成熟度评估系统

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/chaosblade-io/cloud-native-maturity-evaluate/stargazers"><img src="https://img.shields.io/github/stars/chaosblade-io/cloud-native-maturity-evaluate?style=flat&logo=github" alt="GitHub Stars"></a>
  <a href="https://github.com/chaosblade-io/cloud-native-maturity-evaluate/network/members"><img src="https://img.shields.io/github/forks/chaosblade-io/cloud-native-maturity-evaluate?style=flat&logo=github" alt="GitHub Forks"></a>
  <a href="https://github.com/chaosblade-io/cloud-native-maturity-evaluate/issues"><img src="https://img.shields.io/github/issues/chaosblade-io/cloud-native-maturity-evaluate" alt="GitHub Issues"></a>
  <a href="https://github.com/chaosblade-io/cloud-native-maturity-evaluate/commits/main"><img src="https://img.shields.io/github/last-commit/chaosblade-io/cloud-native-maturity-evaluate" alt="Last Commit"></a>
  <a href="https://github.com/chaosblade-io/cloud-native-maturity-evaluate"><img src="https://img.shields.io/github/repo-size/chaosblade-io/cloud-native-maturity-evaluate" alt="Repo Size"></a>
</p>

<p align="center">
  <strong>Serverless | Elasticity | Service Architecture | Observability | Resilience | Automation</strong>
</p>

SESORA 是一个基于阿里云的云原生架构成熟度评估工具，通过自动化数据采集和智能分析，从六个维度全面评估您的云原生架构成熟度水平。

## 特性

- **六维度评估模型**：覆盖 Automation、Elasticity、Observability、Resilience、Serverless、Service Architecture 六大云原生核心能力
- **自动化数据采集**：支持 19+ 阿里云产品的数据自动采集
- **60+ 评估指标**：细粒度的评分标准，提供可操作的改进建议
- **三态评分机制**：区分"已评估"、"条件不满足"、"数据不足"三种状态
- **增量采集支持**：支持分阶段采集数据，逐步完善评估
- **平台无关数据层**：规范化的数据模型，便于扩展其他云平台

## 架构概览

```
┌─────────────────────────────────────────┐
│         分析评分层 (Scoring Layer)        │
│  AnalyzerRegistry + 60+ 独立 Analyzer    │
└────────────────┬────────────────────────┘
                 │ 查询 DataStore
┌────────────────▼────────────────────────┐
│      平台无关数据层 (Neutral Data Layer)  │
│   DataStore (SQLite) + DataItem Schema   │
└────────────────┬────────────────────────┘
                 │ 写入
┌────────────────▼────────────────────────┐
│     平台相关数据采集层 (Platform Layer)   │
│         19+ 个 Collector 实现            │
└─────────────────────────────────────────┘
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/chaosblade-io/cloud-native-maturity-evaluate.git
cd cloud-native-maturity-evaluate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入您的阿里云凭证和资源信息
```

核心配置项：

```bash
# 阿里云基础凭证（必填）
ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key_id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_access_key_secret
ALIBABA_CLOUD_REGION=cn-hangzhou

# ACK 容器服务
ACK_CLUSTER_ID=your_cluster_id
KUBECONFIG_PATHS='["/path/to/kubeconfig"]'

# ARMS APM
ARMS_WORKSPACE_ID=your_workspace_id

# SLS 日志服务
SLS_PROJECT=your_project_name
SLS_REGION=cn-hangzhou

# 云效 Codeup（CI/CD 评估）
YUNXIAO_TOKEN=your_token
CODEUP_ORG_ID=your_org_id
CODEUP_PIPELINE_IDS='["pipeline_id_1", "pipeline_id_2"]'
```

### 3. 运行评估

#### 方式一：完整流程（采集 + 分析）

```bash
python run_pipeline/main.py
```

#### 方式二：分步执行

```bash
# 步骤 1：数据采集
python run_pipeline/collect_data.py

# 步骤 2：运行分析
python run_pipeline/run_analyzer.py data/sesora.db
```

#### 方式三：运行指定分析器

```bash
# 使用配置文件指定分析器
python run_pipeline/run_analyzer.py data/sesora.db --config run_pipeline/run_cases.json

# 或直接指定 key
python run_pipeline/run_analyzer.py data/sesora.db --key ha_redundancy,mon_metrics_depth
```

## 评估维度

### 1. Automation（自动化）

| 子类 | 评估内容 |
|------|---------|
| CI/CD 流水线 | 构建自动化、测试自动化、部署自动化、发布管理、流水线即代码 |
| 基础设施即代码 (IaC) | 资源自动创建、配置管理、策略代码化、漂移检测 |
| 运维自动化 | 故障自动发现、自动扩缩容、备份自动化、安全自动化 |
| GitOps | ArgoCD/Flux 部署、配置即代码 |

### 2. Elasticity（弹性）

| 子类 | 评估内容 |
|------|---------|
| 水平扩展 (HPA) | HPA 配置覆盖率、扩缩容指标多样性 |
| 垂直扩展 (VPA) | VPA 部署、资源推荐 |
| 负载均衡 | 入口负载均衡、服务网格负载均衡 |
| 资源管理 | 命名空间资源配额、节点资源管理 |

### 3. Observability（可观测性）

| 子类 | 评估内容 |
|------|---------|
| 监控能力 | 指标收集深度、告警规则、告警通道、工具链集成 |
| 日志能力 | 日志收集覆盖率、日志结构化程度、关联分析 |
| 链路追踪 | 追踪覆盖率、采样配置、端到端追踪 |
| 可视化 | Dashboard 覆盖率、自定义仪表板 |

### 4. Resilience（韧性）

| 子类 | 评估内容 |
|------|---------|
| 高可用性 | 冗余设计、多可用区部署、负载均衡、全球分布 |
| 容错能力 | 熔断、限流、重试、超时配置 |
| 灾难恢复 | 备份策略、恢复演练、RTO/RPO |
| 健康管理 | 存活探针、就绪探针配置 |

### 5. Serverless（无服务器）

| 子类 | 评估内容 |
|------|---------|
| FaaS 函数计算 | 函数计算使用覆盖率、版本管理 |
| 事件驱动 (EDA) | EventBridge 配置、事件路由 |
| 数据服务 | 云原生数据服务使用 |

### 6. Service Architecture（服务架构）

| 子类 | 评估内容 |
|------|---------|
| API 管理 | API 网关配置、版本管理 |
| 服务通信 | 服务网格 Istio、gRPC 配置 |
| 数据管理 | 数据库架构、缓存、消息队列 |

## 数据采集器

SESORA 支持以下阿里云产品的数据自动采集：

| 采集器 | 采集内容 |
|--------|---------|
| **ACK Collector** | Kubernetes Deployment、StatefulSet、Pod、HPA、VPA、Service、Ingress、CronJob、Event、ResourceQuota、Istio 资源 |
| **ARMS Collector** | APM 服务列表、服务拓扑、外部依赖、链路追踪配置 |
| **CMS Collector** | 告警规则、联系人、联系组、告警历史、事件触发器 |
| **SLS Collector** | Logstore 列表、日志样本、索引配置、存档策略 |
| **Codeup Collector** | 流水线运行记录、代码仓库、提交记录、分支信息 |
| **FC Collector** | 函数列表、别名、版本信息 |
| **ROS Collector** | 资源栈列表、漂移检测信息 |
| **RDS Collector** | 数据库实例、备份策略、代理配置 |
| **OSS Collector** | Bucket 信息、生命周期规则 |
| **ACR Collector** | 镜像仓库、镜像列表、扫描结果 |
| **ALB Collector** | 监听器配置 |
| **ECS Collector** | 实例信息、安全组及规则 |
| **EventBridge Collector** | 事件总线、事件规则 |
| **ArgoCD Collector** | Application 资源 |
| **GTM Collector** | 全局流量管理配置 |

## 输出报告

### 评估报告结构

```
评估报告
├── 任务信息 (task_id, 执行时间)
├── 汇总统计
│   ├── 总分 / 满分
│   ├── 成熟度百分比
│   ├── 评估覆盖率
│   └── 各维度得分
└── 维度详情
    ├── Automation (子类 × N)
    ├── Elasticity (子类 × N)
    ├── Observability (子类 × N)
    ├── Resilience (子类 × N)
    ├── Serverless (子类 × N)
    └── Service Architecture (子类 × N)
```

### 输出格式

- **CSV 文件**：便于数据分析和报表生成
- **文本报告**：便于阅读的成熟度评分报告
- **JSON 格式**：便于集成到其他系统

## 项目结构

```
sesora/
├── sesora/                    # 核心库
│   ├── core/                  # 核心抽象
│   │   ├── analyzer.py        # 分析器基类
│   │   ├── collector.py       # 采集器基类
│   │   ├── context.py         # 评估上下文
│   │   ├── dataitem.py        # 数据项定义
│   │   └── report.py          # 报告结构
│   ├── analyzers/             # 分析器实现（六维度）
│   │   ├── automation/        # 自动化维度
│   │   ├── elasticity/        # 弹性维度
│   │   ├── observability/     # 可观测性维度
│   │   ├── resilience/        # 韧性维度
│   │   ├── serverless/        # Serverless 维度
│   │   └── service_arch/      # 服务架构维度
│   ├── collectors/            # 数据采集器
│   ├── schema/                # 数据模型定义
│   ├── store/                 # 数据存储（SQLite）
│   └── engine.py              # 评估引擎
├── run_pipeline/              # 运行脚本
│   ├── main.py                # 主入口
│   ├── collect_data.py        # 数据采集脚本
│   └── run_analyzer.py        # 分析运行脚本
├── examples/                  # 示例代码
├── data/                      # 数据存储目录
└── results/                   # 评估结果输出
```

## 三态评分机制

SESORA 采用三态评分机制，清晰区分不同评估状态：

| 状态 | 说明 | 计入得分 |
|------|------|---------|
| **SCORED** | 分析已执行，得到具体分数 | ✓ |
| **NOT_SCORED** | 条件不满足，得 0 分 | ✓ |
| **NOT_EVALUATED** | 数据不足，无法评估 | ✗ |

这种机制确保了：
- 数据不足时不影响已评估项的得分计算
- 清晰展示评估覆盖率
- 指导用户补充缺失的数据采集

## 配置详解

完整配置项请参考 [.env.example](.env.example)，主要包括：

| 配置类别 | 说明 |
|---------|------|
| 阿里云凭证 | AccessKey ID/Secret、Region |
| ACK 配置 | 集群 ID、kubeconfig 路径、命名空间 |
| ARMS 配置 | 工作空间 ID |
| SLS 配置 | Project、Logstore、Region |
| Codeup 配置 | Token、组织 ID、仓库 ID、流水线 ID |
| ROS 配置 | 资源栈名称、Region |
| FC 配置 | 函数名称列表 |
| RDS 配置 | 实例 ID 列表 |
| OSS 配置 | Bucket 名称列表 |
| ACR 配置 | 实例 ID 列表 |
| ALB 配置 | 负载均衡器 ID 列表 |
| ArgoCD 配置 | Server 地址、Token |

## 常见问题

### 1. 如何只运行部分分析器？

使用 `--key` 参数指定要运行的分析器：

```bash
python run_pipeline/run_analyzer.py data/sesora.db --key ha_redundancy,mon_metrics_depth
```

或编辑 `run_pipeline/run_cases.json` 配置文件。

### 2. 如何查看数据采集状态？

```bash
python run_pipeline/run_analyzer.py data/sesora.db --verbose
```

将显示数据库中所有 DataItem 及各分析器的数据需求满足情况。

### 3. 如何扩展新的分析器？

1. 在 `sesora/analyzers/` 对应维度目录下创建分析器
2. 继承 `Analyzer` 基类，实现必要方法
3. 在 `__init__.py` 中注册新分析器

### 4. 如何支持新的云产品采集？

1. 在 `sesora/schema/` 中定义数据模型
2. 在 `sesora/collectors/` 中实现采集器
3. 在 `run_pipeline/collect_data.py` 中注册采集器

## 依赖项

- Python 3.10+
- 阿里云 SDK（alibabacloud-*）
- Kubernetes Python Client
- SQLite3（Python 标准库）

详见 [requirements.txt](requirements.txt)

## 贡献

欢迎提交 Issue 和 Pull Request！

---

**SESORA** - 让云原生架构评估更简单、更专业
