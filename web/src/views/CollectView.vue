<template>
  <div class="collect-view">
    <el-row :gutter="24">
      <!-- 采集器选择 -->
      <el-col :span="10">
        <el-card class="collector-card">
          <template #header>
            <div class="card-header">
              <div class="header-title">
                <el-icon class="header-icon"><Connection /></el-icon>
                <span>选择采集器</span>
              </div>
              <div class="header-actions">
                <el-button size="small" text @click="selectAll">全选</el-button>
                <el-button size="small" text @click="selectNone">清空</el-button>
              </div>
            </div>
          </template>
          
          <div class="collector-list">
            <div
              v-for="collector in collectors"
              :key="collector.name"
              class="collector-item"
              :class="{ active: selectedCollectors.includes(collector.name) }"
              @click="toggleCollector(collector.name)"
            >
              <el-checkbox
                :model-value="selectedCollectors.includes(collector.name)"
                @change="toggleCollector(collector.name)"
              />
              <div class="collector-info">
                <div class="collector-label">{{ collector.label }}</div>
                <div class="collector-desc">{{ collector.description }}</div>
              </div>
              <el-icon class="collector-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
          
          <div class="action-bar">
            <el-button
              type="primary"
              size="large"
              :loading="isCollecting"
              :disabled="isCollecting || selectedCollectors.length === 0"
              @click="handleCollect"
              class="action-btn"
            >
              <el-icon><VideoPlay /></el-icon>
              采集选中 ({{ selectedCollectors.length }})
            </el-button>
            <el-button
              type="success"
              size="large"
              :disabled="isCollecting"
              @click="handleCollectAll"
              class="action-btn"
            >
              <el-icon><Refresh /></el-icon>
              采集全部
            </el-button>
          </div>
        </el-card>
      </el-col>
      
      <!-- 采集结果 -->
      <el-col :span="14">
        <el-card class="result-card">
          <template #header>
            <div class="card-header">
              <div class="header-title">
                <el-icon class="header-icon"><DataBoard /></el-icon>
                <span>采集结果</span>
              </div>
              <div v-if="progressList.length" class="result-summary">
                <el-tag type="success" effect="dark">{{ doneCount }} 成功</el-tag>
                <el-tag v-if="failCount > 0" type="danger" effect="dark">{{ failCount }} 失败</el-tag>
                <el-tag v-if="isCollecting" type="warning" effect="dark">{{ pendingCount }} 等待</el-tag>
              </div>
            </div>
          </template>
          
          <!-- 空状态 -->
          <div v-if="!progressList.length" class="empty-state">
            <el-empty description="选择采集器并点击开始采集">
              <template #image>
                <el-icon :size="60" class="empty-icon"><Connection /></el-icon>
              </template>
            </el-empty>
          </div>
          
          <!-- 进度列表（采集中实时更新 + 完成后展示） -->
          <div v-else class="result-list">
            <div
              v-for="item in progressList"
              :key="item.name"
              class="result-item"
              :class="{ success: item.status === 'success', failed: item.status === 'failed' }"
            >
              <div class="result-status">
                <el-icon v-if="item.status === 'success'" class="status-icon success"><CircleCheckFilled /></el-icon>
                <el-icon v-else-if="item.status === 'failed'" class="status-icon failed"><CircleCloseFilled /></el-icon>
                <el-icon v-else-if="item.status === 'running'" class="status-icon running is-loading"><Loading /></el-icon>
                <el-icon v-else class="status-icon pending"><Clock /></el-icon>
              </div>
              <div class="result-info">
                <div class="result-name">{{ item.label }}</div>
                <div class="result-message">{{ item.message }}</div>
              </div>
              <div class="result-time" v-if="item.elapsed !== null">{{ item.elapsed.toFixed(1) }}s</div>
            </div>
          </div>
        </el-card>
        
        <!-- 采集提示 -->
        <el-card class="tip-card">
          <div class="tip-content">
            <el-icon class="tip-icon"><InfoFilled /></el-icon>
            <div class="tip-text">
              <h4>采集说明</h4>
              <ul>
                <li>采集前请确保已正确配置环境变量</li>
                <li>部分采集器需要特定的凭证和配置才能正常工作</li>
                <li>采集的数据会保存到本地数据库 (data/sesora.db)</li>
              </ul>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getCollectors, runOneCollection } from '../api'

const collectors = ref([])
const selectedCollectors = ref([])
const isCollecting = ref(false)
const progressList = ref([])  // 实时采集进度

// 统计
const doneCount = computed(() => progressList.value.filter(i => i.status === 'success').length)
const failCount = computed(() => progressList.value.filter(i => i.status === 'failed').length)
const pendingCount = computed(() => progressList.value.filter(i => i.status === 'pending').length)

// 加载采集器列表
const loadCollectors = async () => {
  try {
    const result = await getCollectors()
    if (result.success) {
      collectors.value = result.data
    }
  } catch (error) {
    ElMessage.error('加载采集器列表失败')
  }
}

// 获取采集器标签
const getCollectorLabel = (name) => {
  const collector = collectors.value.find(c => c.name === name)
  return collector?.label || name
}

// 切换选择
const toggleCollector = (name) => {
  const index = selectedCollectors.value.indexOf(name)
  if (index === -1) {
    selectedCollectors.value.push(name)
  } else {
    selectedCollectors.value.splice(index, 1)
  }
}

// 全选
const selectAll = () => {
  selectedCollectors.value = collectors.value.map(c => c.name)
}

// 清空
const selectNone = () => {
  selectedCollectors.value = []
}

// 串行采集指定列表
const runSerialCollect = async (nameList) => {
  isCollecting.value = true
  
  // 初始化进度列表，全部置为 pending
  progressList.value = nameList.map(name => ({
    name,
    label: getCollectorLabel(name),
    status: 'pending',
    message: '等待采集...',
    elapsed: null,
  }))
  
  for (const name of nameList) {
    // 更新当前采集器状态为 running
    const item = progressList.value.find(i => i.name === name)
    if (item) item.status = 'running'
    if (item) item.message = '正在采集...'
    
    try {
      const result = await runOneCollection(name)
      const r = result.results?.[0]
      if (item) {
        item.status = r?.success ? 'success' : 'failed'
        item.message = r?.message || (r?.success ? '采集成功' : '采集失败')
        item.elapsed = r?.elapsed_seconds ?? null
      }
    } catch (error) {
      if (item) {
        item.status = 'failed'
        item.message = '请求失败: ' + error.message
      }
    }
  }
  
  isCollecting.value = false
  ElMessage.success(`采集完成: ${doneCount.value} 成功, ${failCount.value} 失败`)
}

// 执行采集（选中的）
const handleCollect = () => {
  if (selectedCollectors.value.length === 0) return
  runSerialCollect([...selectedCollectors.value])
}

// 执行采集（全部）
const handleCollectAll = () => {
  runSerialCollect(collectors.value.map(c => c.name))
}

onMounted(() => {
  loadCollectors()
})
</script>

<style scoped>
.collect-view {
  max-width: 1200px;
  margin: 0 auto;
}

.collector-card,
.result-card,
.tip-card {
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

.result-summary {
  display: flex;
  gap: 8px;
}

/* 采集器列表 */
.collector-list {
  max-height: 400px;
  overflow-y: auto;
}

.collector-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #e8ecf1;
  border-radius: 12px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.collector-item:hover {
  border-color: #667eea;
  background: #f8faff;
}

.collector-item.active {
  border-color: #667eea;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%);
}

.collector-info {
  flex: 1;
}

.collector-label {
  font-weight: 500;
  color: #1f2937;
  margin-bottom: 2px;
}

.collector-desc {
  font-size: 12px;
  color: #94a3b8;
}

.collector-arrow {
  color: #cbd5e1;
  transition: all 0.2s ease;
}

.collector-item:hover .collector-arrow,
.collector-item.active .collector-arrow {
  color: #667eea;
  transform: translateX(4px);
}

/* 操作按钮 */
.action-bar {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

.action-btn {
  flex: 1;
  height: 48px;
  border-radius: 12px;
  font-weight: 500;
}

/* 空状态 */
.empty-state {
  padding: 60px 0;
}

.empty-icon {
  color: #cbd5e1;
}

/* 加载状态 */
.loading-state {
  padding: 60px 20px;
  text-align: center;
}

.loading-animation {
  margin-bottom: 20px;
  color: #667eea;
}

.loading-state h3 {
  color: #1f2937;
  margin-bottom: 8px;
}

.loading-state p {
  color: #94a3b8;
  font-size: 14px;
}

.loading-progress {
  max-width: 300px;
  margin: 20px auto 0;
}

/* 结果列表 */
.result-list {
  max-height: 420px;
  overflow-y: auto;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  margin-bottom: 10px;
  background: #f8fafc;
  border: 1px solid #e8ecf1;
}

.result-item.success {
  background: linear-gradient(135deg, rgba(103, 194, 58, 0.08) 0%, rgba(103, 194, 58, 0.04) 100%);
  border-color: rgba(103, 194, 58, 0.3);
}

.result-item.failed {
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.08) 0%, rgba(245, 108, 108, 0.04) 100%);
  border-color: rgba(245, 108, 108, 0.3);
}

.result-status {
  flex-shrink: 0;
}

.status-icon {
  font-size: 24px;
}

.status-icon.success {
  color: #67c23a;
}

.status-icon.failed {
  color: #f56c6c;
}

.status-icon.running {
  color: #667eea;
  font-size: 24px;
}

.status-icon.pending {
  color: #c0c4cc;
}

.result-info {
  flex: 1;
}

.result-name {
  font-weight: 500;
  color: #1f2937;
  margin-bottom: 2px;
}

.result-message {
  font-size: 12px;
  color: #64748b;
}

.result-time {
  font-size: 13px;
  color: #94a3b8;
  font-family: monospace;
}

/* 提示卡片 */
.tip-card {
  background: linear-gradient(135deg, #f0f7ff 0%, #e8f4fc 100%);
  border: 1px solid #bde0fe;
}

.tip-content {
  display: flex;
  gap: 16px;
}

.tip-icon {
  font-size: 24px;
  color: #3b82f6;
  flex-shrink: 0;
}

.tip-text h4 {
  color: #1e40af;
  margin-bottom: 8px;
  font-size: 14px;
}

.tip-text ul {
  margin: 0;
  padding-left: 16px;
  color: #3b82f6;
  font-size: 13px;
}

.tip-text li {
  margin: 4px 0;
}
</style>
