<template>
  <div class="analyze-view">
    <el-row :gutter="24">
      <!-- 左侧：分析器选择 -->
      <el-col :span="10">
        <el-card class="selector-card" v-loading="loadingAnalyzers">
          <template #header>
            <div class="card-header">
              <div class="header-title">
                <el-icon class="header-icon"><Grid /></el-icon>
                <span>选择评估项</span>
              </div>
              <div class="header-actions">
                <el-button size="small" text @click="importConfig">
                  <el-icon><Upload /></el-icon>
                  导入配置
                </el-button>
                <el-button size="small" text @click="selectAll">全选</el-button>
                <el-button size="small" text @click="selectNone">清空</el-button>
              </div>
              <!-- 隐藏的文件输入框 -->
              <input
                ref="jsonFileInput"
                type="file"
                accept=".json,application/json"
                style="display: none"
                @change="handleJsonFileChange"
              />
            </div>
          </template>
          
          <!-- 按维度分组 -->
          <el-collapse v-model="expandedDimensions" class="dimension-collapse">
            <el-collapse-item
              v-for="(items, dimName) in analyzersByDimension"
              :key="dimName"
              :name="dimName"
            >
              <template #title>
                <div class="dim-title">
                  <el-checkbox
                    :model-value="isDimensionSelected(dimName)"
                    :indeterminate="isDimensionIndeterminate(dimName)"
                    @change="toggleDimension(dimName)"
                    @click.stop
                  />
                  <el-icon class="dim-icon" :style="{ color: getDimensionColor(dimName) }">
                    <component :is="getDimensionIcon(dimName)" />
                  </el-icon>
                  <span class="dim-name">{{ getDimensionLabel(dimName) }}</span>
                  <el-tag size="small" type="info" class="dim-count">
                    {{ getSelectedCount(dimName) }}/{{ items.length }}
                  </el-tag>
                </div>
              </template>
              
              <div class="analyzer-list">
                <div
                  v-for="analyzer in items"
                  :key="analyzer.key"
                  class="analyzer-item"
                  :class="{ active: selectedKeys.includes(analyzer.key) }"
                  @click="toggleAnalyzer(analyzer.key)"
                >
                  <el-checkbox
                    :model-value="selectedKeys.includes(analyzer.key)"
                    @change="toggleAnalyzer(analyzer.key)"
                  />
                  <div class="analyzer-info">
                    <div class="analyzer-key">{{ analyzer.key }}</div>
                    <div class="analyzer-meta">
                      <span>分类: {{ analyzer.category }}</span>
                      <span>满分: {{ analyzer.max_score }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
          
          <!-- 操作按钮 -->
          <div class="action-bar">
            <div class="assist-options">
              <el-switch
                v-model="agentAssistEnabled"
                inline-prompt
                active-text="AI辅助"
                inactive-text="规则"
              />
              <el-checkbox v-model="agentAssistOnlySelected" :disabled="!agentAssistEnabled">
                仅当前选中项
              </el-checkbox>
            </div>
            <el-button
              type="primary"
              size="large"
              :loading="analyzing"
              :disabled="selectedKeys.length === 0"
              @click="handleAnalyze"
              class="action-btn"
            >
              <el-icon><VideoPlay /></el-icon>
              运行评估 ({{ selectedKeys.length }})
            </el-button>
          </div>
        </el-card>
        
        <!-- 数据状态 -->
        <el-card class="status-card" v-if="dataStatus">
          <template #header>
            <div class="card-header">
              <div class="header-title">
                <el-icon class="header-icon"><Document /></el-icon>
                <span>数据就绪状态</span>
              </div>
              <el-button size="small" @click="checkDataStatus" :loading="checkingStatus">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>
          
          <div class="status-summary">
            <div class="status-item">
              <span class="status-label">必需数据</span>
              <span class="status-value" :class="{ warning: dataStatus.required.some(d => !d.available) }">
                {{ dataStatus.required.filter(d => d.available).length }}/{{ dataStatus.required.length }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-label">可选数据</span>
              <span class="status-value">
                {{ dataStatus.optional.filter(d => d.available).length }}/{{ dataStatus.optional.length }}
              </span>
            </div>
          </div>
          
          <el-alert
            v-if="dataStatus.required.some(d => !d.available)"
            type="warning"
            :closable="false"
            show-icon
            class="status-alert"
          >
            部分必需数据缺失，可能影响评估结果
          </el-alert>
        </el-card>
      </el-col>
      
      <!-- 右侧：评估结果 -->
      <el-col :span="14">
        <!-- 加载状态 -->
        <el-card v-if="analyzing" class="loading-card">
          <div class="loading-content">
            <div class="loading-animation">
              <el-icon class="is-loading" :size="64"><Loading /></el-icon>
            </div>
            <h2>正在进行评估分析</h2>
            <p>系统正在分析各项指标，请稍候...</p>
            <el-progress :percentage="analyzeProgress" :show-text="false" :stroke-width="8" class="loading-progress" />
          </div>
        </el-card>
        
        <!-- 评估结果 -->
        <template v-else-if="analyzeResult">
          <!-- 总分概览 -->
          <el-card class="overview-card">
            <div class="overview-content">
              <div class="score-section">
                <el-progress
                  type="dashboard"
                  :percentage="analyzeResult.total_percentage"
                  :stroke-width="12"
                  :color="getScoreColor(analyzeResult.total_percentage)"
                  :width="140"
                >
                  <template #default>
                    <div class="score-inner">
                      <span class="score-value">{{ analyzeResult.total_percentage }}%</span>
                      <span class="score-label">综合得分</span>
                    </div>
                  </template>
                </el-progress>
                <div class="maturity-badge" :class="getMaturityClass(analyzeResult.overall_maturity)">
                  {{ analyzeResult.overall_maturity }}
                </div>
              </div>
              <div class="stats-section">
                <div class="stat-item">
                  <span class="stat-value">{{ analyzeResult.total_score }}</span>
                  <span class="stat-label">得分</span>
                </div>
                <div class="stat-divider">/</div>
                <div class="stat-item">
                  <span class="stat-value">{{ analyzeResult.total_max_score }}</span>
                  <span class="stat-label">满分</span>
                </div>
                <div class="stat-item highlight">
                  <span class="stat-value">{{ analyzeResult.results?.length || 0 }}</span>
                  <span class="stat-label">评估项</span>
                </div>
                <div class="stat-item coverage">
                  <span class="stat-value">{{ overallCoverage }}%</span>
                  <span class="stat-label">覆盖率</span>
                </div>
              </div>
              <div class="action-section">
                <el-button @click="exportReport">
                  <el-icon><Download /></el-icon>
                  导出报告
                </el-button>
              </div>
            </div>
          </el-card>
          
          <!-- 维度汇总 -->
          <el-card class="summary-card">
            <template #header>
              <div class="card-header">
                <span>维度汇总</span>
              </div>
            </template>
            
            <div class="summary-grid">
              <div
                v-for="dim in analyzeResult.summary"
                :key="dim.dimension"
                class="summary-item"
                @click="showDimensionDetail(dim)"
              >
                <div class="summary-header">
                  <el-icon :style="{ color: getDimensionColor(dim.dimension) }">
                    <component :is="getDimensionIcon(dim.dimension)" />
                  </el-icon>
                  <span>{{ getDimensionLabel(dim.dimension) }}</span>
                </div>
                <div class="summary-score">
                  <span class="score-num">{{ dim.percentage }}%</span>
                  <el-tag size="small" :type="getMaturityType(dim.maturity_level)">
                    {{ dim.maturity_level }}
                  </el-tag>
                </div>
                <el-progress
                  :percentage="dim.percentage"
                  :stroke-width="6"
                  :show-text="false"
                  :color="getDimensionColor(dim.dimension)"
                />
                <div class="summary-meta">
                  {{ dim.score }}/{{ dim.max_score }} · {{ dim.count }}项
                </div>
                <div class="summary-meta coverage-meta">
                  覆盖率 {{ getDimensionCoverage(dim) }}%
                </div>
              </div>
            </div>
          </el-card>
          
          <!-- 详细结果 -->
          <el-card class="detail-card">
            <template #header>
              <div class="card-header">
                <span>评估详情</span>
                <el-input
                  v-model="searchKey"
                  placeholder="搜索..."
                  clearable
                  style="width: 200px"
                  size="small"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
              </div>
            </template>
            
            <el-table
              :data="filteredResults"
              :default-sort="{ prop: 'percentage', order: 'descending' }"
              class="result-table"
              max-height="400"
            >
              <el-table-column prop="key" label="评估项" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">
                  <div class="key-cell">
                    <el-icon :style="{ color: getDimensionColor(row.dimension) }">
                      <component :is="getDimensionIcon(row.dimension)" />
                    </el-icon>
                    <span>{{ row.key }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="dimension" label="维度" width="100">
                <template #default="{ row }">
                  {{ getDimensionLabel(row.dimension) }}
                </template>
              </el-table-column>
              <el-table-column prop="state" label="状态" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="getStateType(row.state)" size="small">
                    {{ getStateLabel(row.state) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="AI" width="70" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.ai_assisted" type="primary" size="small">AI</el-tag>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="percentage" label="得分" width="150" sortable>
                <template #default="{ row }">
                  <div class="score-cell">
                    <el-progress
                      :percentage="row.percentage"
                      :stroke-width="6"
                      :show-text="false"
                      :color="getScoreColor(row.percentage)"
                      style="width: 80px"
                    />
                    <span>{{ row.score }}/{{ row.max_score }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="原因" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="reason-text">{{ row.reason || '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card class="guidance-card">
            <template #header>
              <div class="card-header">
                <span>改进建议</span>
                <div class="header-actions">
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :disabled="!lastAnalysisRequest.keys.length"
                    :loading="generatingGuidance"
                    @click="handleGenerateGuidance"
                  >
                    生成建议
                  </el-button>
                  <el-button
                    size="small"
                    text
                    :disabled="!guidanceSession"
                    @click="clearGuidanceSession"
                  >
                    清空
                  </el-button>
                </div>
              </div>
            </template>

            <div v-if="!lastAnalysisRequest.keys.length" class="guidance-empty">
              <el-empty description="运行评估后可生成改进建议" />
            </div>

            <div v-else-if="!guidanceSession" class="guidance-empty">
              <el-empty description="当前还没有生成改进建议">
                <el-button type="primary" :loading="generatingGuidance" @click="handleGenerateGuidance">
                  生成首轮建议
                </el-button>
              </el-empty>
            </div>

            <div v-if="lastAnalysisRequest.keys.length" class="guidance-block guidance-config">
              <div class="guidance-title">外部知识文档（可选）</div>
              <div class="guidance-config-grid">
                <el-select
                  v-model="selectedKnowledgeDocIds"
                  multiple
                  filterable
                  clearable
                  placeholder="选择知识库文档"
                >
                  <el-option
                    v-for="doc in knowledgeDocs"
                    :key="doc.id"
                    :label="doc.title || doc.name || doc.id"
                    :value="doc.id"
                  >
                    <div class="knowledge-option">
                      <span>{{ doc.title || doc.name || doc.id }}</span>
                      <span class="knowledge-option-id">{{ doc.id }}</span>
                    </div>
                  </el-option>
                </el-select>
                <el-input-number v-model="guidanceExternalMaxChars" :min="1000" :max="120000" :step="1000" />
                <el-input-number v-model="guidanceExternalMaxChunks" :min="1" :max="100" />
                <el-input-number v-model="guidanceExternalChunkChars" :min="200" :max="5000" :step="100" />
              </div>
              <div class="guidance-config-hint">
                文档由服务端知识库统一维护，前端仅提交文档 ID。
              </div>
              <div class="guidance-config-hint">
                已选择 {{ selectedKnowledgeDocIds.length }} / {{ knowledgeDocs.length }} 份文档。
              </div>
            </div>

            <div v-if="currentGuidanceTurn" class="guidance-content">
              <div class="guidance-meta">
                <el-tag type="primary" effect="plain">
                  {{ currentGuidanceTurn.stage === 'initial_diagnosis' ? 'Initial Diagnosis' : 'Iterative Refinement' }}
                </el-tag>
                <el-tag type="info" effect="plain">
                  聚焦 {{ currentGuidanceTurn.focus_keys?.length || 0 }} 项
                </el-tag>
                <span class="guidance-model">模型: {{ guidanceSession.model }}</span>
              </div>

              <div class="guidance-block">
                <div class="guidance-title">诊断摘要</div>
                <div class="guidance-text">{{ currentGuidanceTurn.guidance?.diagnosis_summary || '-' }}</div>
              </div>

              <div class="guidance-block" v-if="currentGuidanceTurn.guidance?.focus_areas?.length">
                <div class="guidance-title">重点领域</div>
                <div class="tag-list">
                  <el-tag v-for="area in currentGuidanceTurn.guidance.focus_areas" :key="area" type="warning" effect="light">
                    {{ area }}
                  </el-tag>
                </div>
              </div>

              <div class="guidance-block" v-if="currentGuidanceTurn.guidance?.prioritized_recommendations?.length">
                <div class="guidance-title">优先建议</div>
                <div
                  v-for="(recommendation, index) in currentGuidanceTurn.guidance.prioritized_recommendations"
                  :key="`${recommendation.title}-${index}`"
                  class="recommendation-item"
                >
                  <div class="recommendation-header">
                    <div class="recommendation-name">
                      <el-tag size="small" type="danger">{{ recommendation.priority || 'P2' }}</el-tag>
                      <span>{{ recommendation.title || '未命名建议' }}</span>
                    </div>
                    <span class="recommendation-scope">{{ recommendation.scope || '-' }}</span>
                  </div>
                  <div class="recommendation-text">{{ recommendation.rationale || '-' }}</div>
                  <div class="recommendation-subtitle">建议动作</div>
                  <ul class="guidance-list">
                    <li v-for="(action, actionIndex) in recommendation.actions || []" :key="`${index}-action-${actionIndex}`">
                      {{ action }}
                    </li>
                  </ul>
                  <div class="recommendation-subtitle" v-if="recommendation.evidence?.length">关联证据</div>
                  <ul class="guidance-list compact" v-if="recommendation.evidence?.length">
                    <li v-for="(evidence, evidenceIndex) in recommendation.evidence" :key="`${index}-evidence-${evidenceIndex}`">
                      {{ evidence }}
                    </li>
                  </ul>
                </div>
              </div>

              <div class="guidance-block" v-if="currentGuidanceTurn.guidance?.data_gaps?.length">
                <div class="guidance-title">数据缺口</div>
                <div
                  v-for="(gap, index) in currentGuidanceTurn.guidance.data_gaps"
                  :key="`${gap.scope}-${index}`"
                  class="gap-item"
                >
                  <div class="gap-scope">{{ gap.scope || '-' }}</div>
                  <div class="gap-text">{{ gap.gap || '-' }}</div>
                  <div class="gap-hint">{{ gap.suggested_collection || '-' }}</div>
                </div>
              </div>

              <div class="guidance-block" v-if="currentGuidanceTurn.guidance?.follow_up_questions?.length">
                <div class="guidance-title">后续确认问题</div>
                <ul class="guidance-list compact">
                  <li v-for="(question, index) in currentGuidanceTurn.guidance.follow_up_questions" :key="`${question}-${index}`">
                    {{ question }}
                  </li>
                </ul>
              </div>

              <div class="guidance-block">
                <div class="guidance-title">继续完善建议</div>
                <el-input
                  v-model="guidanceFeedback"
                  type="textarea"
                  :rows="3"
                  resize="vertical"
                  placeholder="例如：先做低成本项；只关注可观测性；结合当前团队人力约束重排优先级"
                />
                <div class="guidance-actions">
                  <el-button
                    type="primary"
                    :loading="refiningGuidance"
                    :disabled="!guidanceFeedback.trim()"
                    @click="handleRefineGuidance"
                  >
                    基于反馈完善
                  </el-button>
                </div>
              </div>

              <div class="guidance-block" v-if="guidanceTurns.length > 1">
                <div class="guidance-title">历史轮次</div>
                <div class="history-list">
                  <div
                    v-for="(turn, index) in guidanceTurns"
                    :key="`${turn.stage}-${index}`"
                    class="history-item"
                  >
                    <div class="history-header">
                      <span>第 {{ index + 1 }} 轮</span>
                      <el-tag size="small" type="info" effect="plain">
                        {{ turn.stage === 'initial_diagnosis' ? 'Initial' : 'Refinement' }}
                      </el-tag>
                    </div>
                    <div class="history-feedback" v-if="turn.feedback">反馈: {{ turn.feedback }}</div>
                    <div class="history-summary">{{ turn.guidance?.diagnosis_summary || '-' }}</div>
                  </div>
                </div>
              </div>
            </div>
          </el-card>
        </template>
        
        <!-- 空状态 -->
        <el-card v-else class="empty-card">
          <el-empty description="选择评估项并点击运行评估">
            <template #image>
              <el-icon :size="80" class="empty-icon"><TrendCharts /></el-icon>
            </template>
          </el-empty>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- 维度详情弹窗 -->
    <el-drawer
      v-model="showDetail"
      :title="currentDimension ? getDimensionLabel(currentDimension.dimension) + ' 详情' : ''"
      size="550px"
      class="dimension-drawer"
    >
      <div v-if="currentDimension" class="drawer-content">
        <div class="drawer-score">
          <el-progress
            type="dashboard"
            :percentage="currentDimension.percentage"
            :stroke-width="8"
            :color="getDimensionColor(currentDimension.dimension)"
            :width="100"
          />
          <div class="drawer-meta">
            <span>{{ currentDimension.score }}/{{ currentDimension.max_score }}</span>
            <el-tag :type="getMaturityType(currentDimension.maturity_level)">
              {{ currentDimension.maturity_level }}
            </el-tag>
          </div>
        </div>
        
        <el-divider>评估项列表 ({{ dimensionResults.length }})</el-divider>
        
        <div class="indicator-list">
          <div
            v-for="result in dimensionResults"
            :key="result.key"
            class="indicator-item"
          >
            <div class="indicator-header">
              <span class="indicator-name">{{ result.key }}</span>
              <div class="indicator-tags">
                <el-tag :type="getStateType(result.state)" size="small">
                  {{ result.score }}/{{ result.max_score }}
                </el-tag>
                <el-tag v-if="result.ai_assisted" type="primary" size="small">AI辅助</el-tag>
              </div>
            </div>
            <el-progress
              :percentage="result.percentage"
              :stroke-width="4"
              :show-text="false"
              :color="getScoreColor(result.percentage)"
            />
            <div class="indicator-reason" v-if="result.reason">
              {{ result.reason }}
            </div>
            <div class="indicator-evidence" v-if="result.evidence?.length">
              <el-tag v-for="(ev, idx) in result.evidence.slice(0, 3)" :key="idx" size="small" type="info">
                {{ typeof ev === 'object' ? JSON.stringify(ev).slice(0, 30) : String(ev).slice(0, 30) }}...
              </el-tag>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAnalyzers, getDataStatus, getKnowledgeDocs, runAnalysis, generateGuidance, refineGuidance } from '../api'

// 状态
const loadingAnalyzers = ref(false)

// JSON 配置导入
const jsonFileInput = ref(null)

const importConfig = () => {
  jsonFileInput.value?.click()
}

const handleJsonFileChange = (event) => {
  const file = event.target.files?.[0]
  if (!file) return

  // 重置 input，允许重复选择同一文件
  event.target.value = ''

  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const parsed = JSON.parse(e.target.result)

      // 支持两种格式：{ keys: [...] } 或直接 ["key1", "key2", ...]
      let keys
      if (Array.isArray(parsed)) {
        keys = parsed
      } else if (parsed && Array.isArray(parsed.keys)) {
        keys = parsed.keys
      } else {
        ElMessage.error('JSON 格式不正确，应为 ["key1", ...] 或 { "keys": ["key1", ...] }')
        return
      }

      // 过滤出有效的分析器 key
      const validKeys = analyzers.value.map(a => a.key)
      const matched = keys.filter(k => validKeys.includes(k))
      const unmatched = keys.filter(k => !validKeys.includes(k))

      if (matched.length === 0) {
        ElMessage.warning('JSON 中的评估项 key 均无法匹配，请检查文件内容')
        return
      }

      selectedKeys.value = matched

      if (unmatched.length > 0) {
        ElMessage.warning(`已选中 ${matched.length} 项，${unmatched.length} 个 key 无法匹配（${unmatched.slice(0, 3).join(', ')}${unmatched.length > 3 ? '...' : ''}）`)
      } else {
        ElMessage.success(`已从配置文件选中 ${matched.length} 个评估项`)
      }
    } catch {
      ElMessage.error('JSON 解析失败，请检查文件格式')
    }
  }
  reader.readAsText(file)
}
const analyzing = ref(false)
const analyzeProgress = ref(0)
const checkingStatus = ref(false)
const agentAssistEnabled = ref(false)
const agentAssistOnlySelected = ref(true)
const generatingGuidance = ref(false)
const refiningGuidance = ref(false)

const analyzers = ref([])
const analyzersByDimension = ref({})
const expandedDimensions = ref([])  // 默认收起所有维度
const selectedKeys = ref([])

const dataStatus = ref(null)
const analyzeResult = ref(null)
const searchKey = ref('')
const guidanceSession = ref(null)
const guidanceFeedback = ref('')
const knowledgeDocs = ref([])
const selectedKnowledgeDocIds = ref([])
const guidanceExternalMaxChars = ref(12000)
const guidanceExternalMaxChunks = ref(12)
const guidanceExternalChunkChars = ref(800)
const lastAnalysisRequest = ref({
  keys: [],
  agentAssist: false,
  agentAssistKeys: [],
})

const showDetail = ref(false)
const currentDimension = ref(null)

// 维度标签映射
const dimensionLabels = {
  observability: '可观测性',
  elasticity: '弹性伸缩',
  resilience: '韧性容错',
  automation: '自动化',
  service_arch: '服务架构',
  serverless: '无服务器',
}

// 维度颜色映射
const dimensionColors = {
  observability: '#1677FF',
  elasticity: '#722ED1',
  resilience: '#0ABF5B',
  automation: '#FF7D00',
  service_arch: '#EB2F96',
  serverless: '#13C2C2',
}

// 维度图标映射
const dimensionIcons = {
  observability: 'View',
  elasticity: 'ScaleToOriginal',
  resilience: 'Shield',
  automation: 'SetUp',
  service_arch: 'Grid',
  serverless: 'Cloudy',
}

// 获取维度标签
const getDimensionLabel = (name) => dimensionLabels[name] || name
const getDimensionColor = (name) => dimensionColors[name] || '#1677FF'
const getDimensionIcon = (name) => dimensionIcons[name] || 'Document'

// 获取分数颜色
const getScoreColor = (score) => {
  if (score >= 75) return '#67c23a'
  if (score >= 50) return '#e6a23c'
  if (score >= 25) return '#f56c6c'
  return '#909399'
}

// 获取成熟度类型
const getMaturityType = (level) => {
  const types = { '全面': 'success', '高级': 'primary', '标准': 'warning', '基础': 'info', '无': 'danger' }
  return types[level] || 'info'
}

const getMaturityClass = (level) => {
  const classes = { '全面': 'excellent', '高级': 'good', '标准': 'fair', '基础': 'basic', '无': 'none' }
  return classes[level] || 'basic'
}

// 获取状态
const getStateType = (state) => {
  const types = { scored: 'success', not_scored: 'warning', skipped: 'info', error: 'danger' }
  return types[state] || 'info'
}

const getStateLabel = (state) => {
  const labels = { scored: '已评分', not_scored: '未评分', skipped: '跳过', error: '错误' }
  return labels[state] || state
}

const COVERED_STATES = new Set(['scored', 'not_scored'])

const calcCoverage = (results = []) => {
  if (!results.length) return 0
  const coveredCount = results.filter(r => COVERED_STATES.has(r.state)).length
  return Math.round((coveredCount / results.length) * 1000) / 10
}

// 维度选择状态
const isDimensionSelected = (dimName) => {
  const items = analyzersByDimension.value[dimName] || []
  return items.length > 0 && items.every(a => selectedKeys.value.includes(a.key))
}

const isDimensionIndeterminate = (dimName) => {
  const items = analyzersByDimension.value[dimName] || []
  const selectedCount = items.filter(a => selectedKeys.value.includes(a.key)).length
  return selectedCount > 0 && selectedCount < items.length
}

const getSelectedCount = (dimName) => {
  const items = analyzersByDimension.value[dimName] || []
  return items.filter(a => selectedKeys.value.includes(a.key)).length
}

// 切换维度
const toggleDimension = (dimName) => {
  const items = analyzersByDimension.value[dimName] || []
  const allSelected = isDimensionSelected(dimName)
  
  if (allSelected) {
    // 取消全部
    items.forEach(a => {
      const idx = selectedKeys.value.indexOf(a.key)
      if (idx !== -1) selectedKeys.value.splice(idx, 1)
    })
  } else {
    // 选择全部
    items.forEach(a => {
      if (!selectedKeys.value.includes(a.key)) {
        selectedKeys.value.push(a.key)
      }
    })
  }
}

// 切换单个分析器
const toggleAnalyzer = (key) => {
  const idx = selectedKeys.value.indexOf(key)
  if (idx === -1) {
    selectedKeys.value.push(key)
  } else {
    selectedKeys.value.splice(idx, 1)
  }
}

// 全选/清空
const selectAll = () => {
  selectedKeys.value = analyzers.value.map(a => a.key)
}

const selectNone = () => {
  selectedKeys.value = []
}

// 过滤结果
const filteredResults = computed(() => {
  if (!analyzeResult.value?.results) return []
  if (!searchKey.value) return analyzeResult.value.results
  
  const keyword = searchKey.value.toLowerCase()
  return analyzeResult.value.results.filter(r =>
    r.key.toLowerCase().includes(keyword) ||
    r.dimension.toLowerCase().includes(keyword) ||
    (r.reason && r.reason.toLowerCase().includes(keyword))
  )
})

const overallCoverage = computed(() => {
  const backendCoverage = analyzeResult.value?.coverage_ratio
  if (typeof backendCoverage === 'number') {
    return Math.round(backendCoverage * 10) / 10
  }
  return calcCoverage(analyzeResult.value?.results || [])
})

const getDimensionCoverage = (dim) => {
  if (typeof dim?.coverage_ratio === 'number') {
    return Math.round(dim.coverage_ratio * 10) / 10
  }
  const rows = (analyzeResult.value?.results || []).filter(r => r.dimension === dim.dimension)
  return calcCoverage(rows)
}

// 当前维度的结果
const dimensionResults = computed(() => {
  if (!currentDimension.value || !analyzeResult.value?.results) return []
  return analyzeResult.value.results.filter(r => r.dimension === currentDimension.value.dimension)
})

const guidanceTurns = computed(() => guidanceSession.value?.turns || [])

const currentGuidanceTurn = computed(() => {
  if (!guidanceTurns.value.length) return null
  return guidanceTurns.value[guidanceTurns.value.length - 1]
})

const getCurrentAgentAssistKeys = () => {
  if (!agentAssistEnabled.value) return []
  return agentAssistOnlySelected.value ? [...selectedKeys.value] : []
}

const clearGuidanceSession = () => {
  guidanceSession.value = null
  guidanceFeedback.value = ''
}

const buildExternalKnowledgePayload = () => ({
  knowledge_doc_ids: [...selectedKnowledgeDocIds.value],
  external_knowledge_max_chars: Number(guidanceExternalMaxChars.value || 12000),
  external_knowledge_max_chunks: Number(guidanceExternalMaxChunks.value || 12),
  external_knowledge_chunk_chars: Number(guidanceExternalChunkChars.value || 800),
})

const loadKnowledgeDocs = async () => {
  try {
    const result = await getKnowledgeDocs()
    if (result.success) {
      knowledgeDocs.value = result.docs || []
      return
    }
    ElMessage.error(result.message || '加载知识库文档失败')
  } catch (error) {
    ElMessage.error('加载知识库文档失败: ' + error.message)
  }
}

// 加载分析器列表
const loadAnalyzers = async () => {
  loadingAnalyzers.value = true
  try {
    const result = await getAnalyzers()
    if (result.success) {
      analyzers.value = result.data.analyzers
      analyzersByDimension.value = result.data.by_dimension
      // 默认收起，不展开任何维度
      expandedDimensions.value = []
      // 默认全选
      selectedKeys.value = analyzers.value.map(a => a.key)
    }
  } catch (error) {
    ElMessage.error('加载分析器失败')
  } finally {
    loadingAnalyzers.value = false
  }
}

// 检查数据状态
const checkDataStatus = async () => {
  checkingStatus.value = true
  try {
    const keys = selectedKeys.value.length > 0 ? selectedKeys.value : null
    const result = await getDataStatus(keys)
    if (result.success) {
      dataStatus.value = result
    }
  } catch (error) {
    console.error('检查数据状态失败:', error)
  } finally {
    checkingStatus.value = false
  }
}

// 执行分析
const handleAnalyze = async () => {
  analyzing.value = true
  analyzeProgress.value = 0
  analyzeResult.value = null
  clearGuidanceSession()

  const analysisRequest = {
    keys: [...selectedKeys.value],
    agentAssist: agentAssistEnabled.value,
    agentAssistKeys: getCurrentAgentAssistKeys(),
  }
  
  // 模拟进度
  const progressInterval = setInterval(() => {
    if (analyzeProgress.value < 90) {
      analyzeProgress.value += Math.random() * 15
    }
  }, 500)
  
  try {
    const result = await runAnalysis(analysisRequest.keys, {
      agentAssist: analysisRequest.agentAssist,
      agentAssistKeys: analysisRequest.agentAssistKeys,
    })
    analyzeProgress.value = 100
    
    if (result.success) {
      analyzeResult.value = result
      lastAnalysisRequest.value = analysisRequest
      ElMessage.success(`评估完成: ${result.results?.length || 0} 个评估项`)
    } else {
      ElMessage.error(result.message || '评估失败')
    }
  } catch (error) {
    ElMessage.error('评估失败: ' + error.message)
  } finally {
    clearInterval(progressInterval)
    analyzing.value = false
  }
}

const handleGenerateGuidance = async () => {
  if (!lastAnalysisRequest.value.keys.length) {
    ElMessage.warning('请先运行评估')
    return
  }

  generatingGuidance.value = true
  try {
    const result = await generateGuidance({
      keys: lastAnalysisRequest.value.keys,
      agent_assist: lastAnalysisRequest.value.agentAssist,
      agent_assist_keys: lastAnalysisRequest.value.agentAssistKeys,
      ...buildExternalKnowledgePayload(),
    })

    if (result.success) {
      guidanceSession.value = result.session
      guidanceFeedback.value = ''
      ElMessage.success('已生成首轮改进建议')
    } else {
      ElMessage.error(result.message || '生成改进建议失败')
    }
  } catch (error) {
    ElMessage.error('生成改进建议失败: ' + error.message)
  } finally {
    generatingGuidance.value = false
  }
}

const handleRefineGuidance = async () => {
  if (!guidanceSession.value) {
    ElMessage.warning('请先生成首轮改进建议')
    return
  }
  if (!guidanceFeedback.value.trim()) {
    ElMessage.warning('请输入反馈内容')
    return
  }

  refiningGuidance.value = true
  try {
    const result = await refineGuidance({
      session: guidanceSession.value,
      feedback: guidanceFeedback.value.trim(),
      ...buildExternalKnowledgePayload(),
    })

    if (result.success) {
      guidanceSession.value = result.session
      guidanceFeedback.value = ''
      ElMessage.success('已根据反馈更新建议')
    } else {
      ElMessage.error(result.message || '更新改进建议失败')
    }
  } catch (error) {
    ElMessage.error('更新改进建议失败: ' + error.message)
  } finally {
    refiningGuidance.value = false
  }
}

// 显示维度详情
const showDimensionDetail = (dim) => {
  currentDimension.value = dim
  showDetail.value = true
}

// 导出报告
const exportReport = () => {
  if (!analyzeResult.value) return
  const blob = new Blob([JSON.stringify(analyzeResult.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `sesora_report_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadAnalyzers()
  loadKnowledgeDocs()
})
</script>

<style scoped>
.analyze-view {
  max-width: 1400px;
  margin: 0 auto;
}

.selector-card,
.status-card,
.loading-card,
.overview-card,
.summary-card,
.guidance-card,
.detail-card,
.empty-card {
  border-radius: 8px;
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.header-icon {
  font-size: 16px;
  color: var(--color-primary);
}

.header-actions {
  display: flex;
  gap: 4px;
}

/* 维度折叠面板 */
.dimension-collapse {
  border: none;
}

:deep(.el-collapse-item__header) {
  height: 44px;
  padding: 0 12px;
  border-radius: 6px;
  background: var(--color-bg-1);
  border: 1px solid var(--color-border);
  margin-bottom: 6px;
  font-size: 14px;
}

:deep(.el-collapse-item__wrap) {
  border: none;
}

:deep(.el-collapse-item__content) {
  padding: 8px 0;
}

.dim-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.dim-icon {
  font-size: 16px;
}

.dim-name {
  font-weight: 500;
  color: var(--color-text-primary);
}

.dim-count {
  margin-left: auto;
  margin-right: 10px;
}

/* 分析器列表 */
.analyzer-list {
  padding: 0 4px;
}

.analyzer-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.analyzer-item:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.analyzer-item.active {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.analyzer-info {
  flex: 1;
}

.analyzer-key {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  font-family: monospace;
}

.analyzer-meta {
  font-size: 11px;
  color: var(--color-text-tertiary);
  display: flex;
  gap: 12px;
  margin-top: 2px;
}

/* 操作按钮 */
.action-bar {
  margin-top: 14px;
}

.assist-options {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.action-btn {
  width: 100%;
  height: 40px;
  border-radius: 6px;
  font-weight: 500;
}

.guidance-empty {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.guidance-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.guidance-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.guidance-model {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.guidance-block {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 14px;
  background: var(--color-bg-1);
}

.guidance-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 10px;
}

.guidance-text {
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.recommendation-item,
.gap-item,
.history-item {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 12px;
  background: var(--color-bg-white);
}

.recommendation-item + .recommendation-item,
.gap-item + .gap-item,
.history-item + .history-item {
  margin-top: 10px;
}

.recommendation-header,
.history-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 8px;
}

.recommendation-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.recommendation-scope,
.gap-hint,
.history-feedback,
.history-summary {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.recommendation-text,
.gap-text,
.gap-scope {
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.recommendation-subtitle {
  margin-top: 10px;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.guidance-list {
  margin: 0;
  padding-left: 18px;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.guidance-list.compact {
  line-height: 1.6;
}

.guidance-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.guidance-config-grid {
  display: grid;
  gap: 10px;
}

.guidance-config-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.knowledge-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.knowledge-option-id {
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 数据状态 */
.status-summary {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
}

.status-item {
  display: flex;
  flex-direction: column;
}

.status-label {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.status-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-success);
}

.status-value.warning {
  color: var(--color-warning);
}

.status-alert {
  border-radius: 6px;
}

/* 加载状态 */
.loading-content {
  padding: 60px 20px;
  text-align: center;
}

.loading-animation {
  color: var(--color-primary);
  margin-bottom: 20px;
}

.loading-content h2 {
  color: var(--color-text-primary);
  margin-bottom: 8px;
  font-size: 18px;
}

.loading-content p {
  color: var(--color-text-secondary);
}

.loading-progress {
  max-width: 400px;
  margin: 20px auto 0;
}

/* 总览卡片 */
.overview-content {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 8px 0;
}

.score-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.score-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.score-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.maturity-badge {
  padding: 3px 14px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
}

.maturity-badge.excellent {
  background: #F6FFED;
  color: #389E0D;
  border: 1px solid #B7EB8F;
}

.maturity-badge.good {
  background: var(--color-primary-bg);
  color: var(--color-primary);
  border: 1px solid #91CAFF;
}

.maturity-badge.fair {
  background: #FFFBE6;
  color: #D48806;
  border: 1px solid #FFE58F;
}

.maturity-badge.basic {
  background: var(--color-bg-2);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.maturity-badge.none {
  background: #FFF2F0;
  color: #CF1322;
  border: 1px solid #FFCCC7;
}

.stats-section {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-item .stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.stat-item.highlight .stat-value {
  color: var(--color-primary);
}

.stat-item.coverage .stat-value {
  color: #0ABF5B;
}

.stat-item .stat-label {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.stat-divider {
  font-size: 20px;
  color: var(--color-text-placeholder);
}

.action-section {
  margin-left: auto;
}

/* 维度汇总 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.summary-item {
  padding: 14px;
  background: var(--color-bg-1);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.2s ease;
}

.summary-item:hover {
  border-color: var(--color-primary);
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-weight: 500;
  color: var(--color-text-primary);
  font-size: 14px;
}

.summary-score {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.score-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.summary-meta {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-top: 6px;
}

.summary-meta.coverage-meta {
  color: #0ABF5B;
  margin-top: 4px;
}

/* 详情表格 */
.key-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.score-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.reason-text {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 空状态 */
.empty-card {
  padding: 60px 0;
}

.empty-icon {
  color: var(--color-bg-3);
}

/* 抽屉内容 */
.drawer-content {
  padding: 20px;
}

.drawer-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.drawer-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.indicator-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.indicator-item {
  padding: 12px;
  background: var(--color-bg-1);
  border-radius: 6px;
  border: 1px solid var(--color-border);
}

.indicator-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.indicator-tags {
  display: flex;
  gap: 6px;
}

.indicator-name {
  font-family: monospace;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
}

.indicator-reason {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 6px;
}

.indicator-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
</style>
