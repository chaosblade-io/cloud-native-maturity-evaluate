<template>
  <div class="collect-view">
    <div class="page-two-col">
      <!-- 左侧：采集器选择 -->
      <div class="page-two-col-left">
        <div class="section-header">
          <span class="section-title">选择采集器</span>
          <div class="section-actions">
            <el-button size="small" text @click="selectAll">全选</el-button>
            <el-button size="small" text @click="selectNone">清空</el-button>
          </div>
        </div>
        <div class="section-body collector-scroll">
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
        <div class="section-footer action-bar">
          <el-button
            type="primary"
            :loading="isCollecting"
            :disabled="isCollecting || selectedCollectors.length === 0"
            @click="handleCollect"
            class="action-btn"
          >
            <el-icon><VideoPlay /></el-icon>
            采集选中 ({{ selectedCollectors.length }})
          </el-button>
          <el-button
            :disabled="isCollecting"
            @click="handleCollectAll"
            class="action-btn"
          >
            <el-icon><Refresh /></el-icon>
            采集全部
          </el-button>
        </div>
      </div>

      <!-- 右侧：采集结果 + 采集说明 -->
      <div class="page-two-col-right">
        <div class="section-header">
          <span class="section-title">采集结果</span>
          <div v-if="progressList.length" class="section-actions">
            <el-tag type="success" effect="plain">{{ doneCount }} 成功</el-tag>
            <el-tag v-if="failCount > 0" type="danger" effect="plain">{{ failCount }} 失败</el-tag>
            <el-tag v-if="isCollecting" type="warning" effect="plain">{{ pendingCount }} 等待</el-tag>
          </div>
        </div>
        <div class="section-body">
          <!-- 空状态 -->
          <div v-if="!progressList.length" class="empty-state">
            <el-empty description="选择采集器并点击开始采集">
              <template #image>
                <el-icon :size="60" class="empty-icon"><Connection /></el-icon>
              </template>
            </el-empty>
          </div>
          <!-- 进度列表 -->
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
        </div>

        <hr class="section-divider" />
        <div class="section-header">
          <span class="section-title">采集说明</span>
        </div>
        <div class="section-body tip-body">
          <div class="tip-content">
            <el-icon class="tip-icon"><InfoFilled /></el-icon>
            <div class="tip-text">
              <ul>
                <li>采集前请确保已正确配置环境变量</li>
                <li>部分采集器需要特定的凭证和配置才能正常工作</li>
                <li>采集的数据会保存到本地数据库 (data/sesora.db)</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
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
  min-height: 100%;
}

.action-bar {
  display: flex;
  gap: 10px;
}

/* 采集器列表 */
.collector-scroll {
  max-height: 500px;
  overflow-y: auto;
  padding-top: 8px;
  padding-bottom: 8px;
}

.collector-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.collector-item:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.collector-item.active {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.collector-info {
  flex: 1;
}

.collector-label {
  font-weight: 500;
  color: var(--color-text-primary);
  margin-bottom: 2px;
  font-size: 14px;
}

.collector-desc {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.collector-arrow {
  color: var(--color-text-placeholder);
  transition: all 0.2s ease;
}

.collector-item:hover .collector-arrow,
.collector-item.active .collector-arrow {
  color: var(--color-primary);
}

/* 操作按钮 */
.action-btn {
  flex: 1;
}

/* 空状态 */
.empty-state {
  padding: 40px 0;
}

.empty-icon {
  color: var(--color-bg-3);
}

/* 结果列表 */
.result-list {
  max-height: 420px;
  overflow-y: auto;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 6px;
  margin-bottom: 8px;
  background: var(--color-bg-1);
  border: 1px solid var(--color-border);
}

.result-item.success {
  background: #F6FFED;
  border-color: #B7EB8F;
}

.result-item.failed {
  background: #FFF2F0;
  border-color: #FFCCC7;
}

.result-status {
  flex-shrink: 0;
}

.status-icon {
  font-size: 20px;
}

.status-icon.success {
  color: var(--color-success);
}

.status-icon.failed {
  color: var(--color-danger);
}

.status-icon.running {
  color: var(--color-primary);
}

.status-icon.pending {
  color: var(--color-text-placeholder);
}

.result-info {
  flex: 1;
}

.result-name {
  font-weight: 500;
  color: var(--color-text-primary);
  margin-bottom: 2px;
  font-size: 14px;
}

.result-message {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.result-time {
  font-size: 12px;
  color: var(--color-text-tertiary);
  font-family: monospace;
}

/* 提示卡片 */
.tip-content {
  display: flex;
  gap: 12px;
}

.tip-icon {
  font-size: 20px;
  color: var(--color-primary);
  flex-shrink: 0;
}

.tip-text h4 {
  color: var(--color-primary-active);
  margin-bottom: 6px;
  font-size: 14px;
}

.tip-text ul {
  margin: 0;
  padding-left: 16px;
  color: var(--color-primary);
  font-size: 13px;
}

.tip-text li {
  margin: 3px 0;
}
</style>
