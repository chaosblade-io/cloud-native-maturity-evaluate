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
              <el-tag :type="getStateType(result.state)" size="small">
                {{ result.score }}/{{ result.max_score }}
              </el-tag>
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
import { getAnalyzers, getDataStatus, runAnalysis } from '../api'

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

const analyzers = ref([])
const analyzersByDimension = ref({})
const expandedDimensions = ref([])  // 默认收起所有维度
const selectedKeys = ref([])

const dataStatus = ref(null)
const analyzeResult = ref(null)
const searchKey = ref('')

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
  observability: '#667eea',
  elasticity: '#f093fb',
  resilience: '#4facfe',
  automation: '#43e97b',
  service_arch: '#fa709a',
  serverless: '#fee140',
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
const getDimensionColor = (name) => dimensionColors[name] || '#667eea'
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

// 当前维度的结果
const dimensionResults = computed(() => {
  if (!currentDimension.value || !analyzeResult.value?.results) return []
  return analyzeResult.value.results.filter(r => r.dimension === currentDimension.value.dimension)
})

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
  
  // 模拟进度
  const progressInterval = setInterval(() => {
    if (analyzeProgress.value < 90) {
      analyzeProgress.value += Math.random() * 15
    }
  }, 500)
  
  try {
    const result = await runAnalysis(selectedKeys.value)
    analyzeProgress.value = 100
    
    if (result.success) {
      analyzeResult.value = result
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
.detail-card,
.empty-card {
  border-radius: 16px;
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
}

.header-icon {
  font-size: 20px;
  color: #667eea;
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
  height: 50px;
  padding: 0 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e8ecf1;
  margin-bottom: 6px;
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
  gap: 10px;
  width: 100%;
}

.dim-icon {
  font-size: 18px;
}

.dim-name {
  font-weight: 500;
  color: #1f2937;
}

.dim-count {
  margin-left: auto;
  margin-right: 10px;
}

/* 分析器列表 */
.analyzer-list {
  padding: 0 8px;
}

.analyzer-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e8ecf1;
  border-radius: 8px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.analyzer-item:hover {
  border-color: #667eea;
  background: #f8faff;
}

.analyzer-item.active {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.08);
}

.analyzer-info {
  flex: 1;
}

.analyzer-key {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
  font-family: monospace;
}

.analyzer-meta {
  font-size: 11px;
  color: #94a3b8;
  display: flex;
  gap: 12px;
  margin-top: 2px;
}

/* 操作按钮 */
.action-bar {
  margin-top: 16px;
}

.action-btn {
  width: 100%;
  height: 48px;
  border-radius: 12px;
  font-weight: 500;
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
  color: #94a3b8;
}

.status-value {
  font-size: 18px;
  font-weight: 600;
  color: #67c23a;
}

.status-value.warning {
  color: #e6a23c;
}

.status-alert {
  border-radius: 8px;
}

/* 加载状态 */
.loading-content {
  padding: 80px 20px;
  text-align: center;
}

.loading-animation {
  color: #667eea;
  margin-bottom: 24px;
}

.loading-content h2 {
  color: #1f2937;
  margin-bottom: 8px;
}

.loading-content p {
  color: #64748b;
}

.loading-progress {
  max-width: 400px;
  margin: 24px auto 0;
}

/* 总览卡片 */
.overview-content {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 16px 0;
}

.score-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.score-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-value {
  font-size: 28px;
  font-weight: 700;
  color: #1f2937;
}

.score-label {
  font-size: 12px;
  color: #64748b;
}

.maturity-badge {
  padding: 4px 16px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 500;
}

.maturity-badge.excellent {
  background: linear-gradient(135deg, #67c23a 0%, #95d475 100%);
  color: #fff;
}

.maturity-badge.good {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.maturity-badge.fair {
  background: linear-gradient(135deg, #e6a23c 0%, #f5c77e 100%);
  color: #fff;
}

.maturity-badge.basic {
  background: #909399;
  color: #fff;
}

.maturity-badge.none {
  background: #f56c6c;
  color: #fff;
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
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
}

.stat-item.highlight .stat-value {
  color: #667eea;
}

.stat-item .stat-label {
  font-size: 12px;
  color: #94a3b8;
}

.stat-divider {
  font-size: 20px;
  color: #cbd5e1;
}

.action-section {
  margin-left: auto;
}

/* 维度汇总 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.summary-item {
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.summary-item:hover {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 500;
  color: #1f2937;
}

.summary-score {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.score-num {
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
}

.summary-meta {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 8px;
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
  color: #64748b;
}

/* 空状态 */
.empty-card {
  padding: 80px 0;
}

.empty-icon {
  color: #cbd5e1;
}

/* 抽屉内容 */
.drawer-content {
  padding: 20px;
}

.drawer-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.drawer-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: #64748b;
}

.indicator-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.indicator-item {
  padding: 14px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e8ecf1;
}

.indicator-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.indicator-name {
  font-family: monospace;
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
}

.indicator-reason {
  font-size: 12px;
  color: #64748b;
  margin-top: 8px;
}

.indicator-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
</style>
