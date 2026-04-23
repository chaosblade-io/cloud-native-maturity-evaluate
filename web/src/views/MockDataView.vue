<template>
  <div class="mock-view">
    <div class="page-two-col">
      <!-- 左侧：上传区域 + 结果 -->
      <div class="page-two-col-left mock-left">
        <div class="section-header">
          <span class="section-title">上传 Mock 数据</span>
        </div>
        <div class="section-body">
          <el-upload
            ref="uploadRef"
            class="upload-area"
            drag
            :auto-upload="false"
            :limit="1"
            accept=".json"
            :on-change="handleFileChange"
            :on-exceed="handleExceed"
          >
            <div class="upload-content">
              <el-icon class="upload-icon"><UploadFilled /></el-icon>
              <div class="upload-text">
                <p class="main-text">拖拽 JSON 文件到此处</p>
                <p class="sub-text">或 <em>点击上传</em></p>
              </div>
            </div>
          </el-upload>
          
          <!-- JSON 预览 -->
          <transition name="fade">
            <div v-if="previewData" class="preview-area">
              <div class="preview-header">
                <span>文件预览</span>
                <el-tag type="success">{{ Object.keys(previewData).length }} 个数据项</el-tag>
              </div>
              <el-scrollbar height="180px">
                <pre class="preview-json">{{ JSON.stringify(previewData, null, 2) }}</pre>
              </el-scrollbar>
            </div>
          </transition>
          
          <el-button
            type="primary"
            size="large"
            :loading="uploading"
            :disabled="!selectedFile"
            @click="handleUpload"
            class="upload-btn"
          >
            <el-icon><Upload /></el-icon>
            导入数据库
          </el-button>
        </div>
    
        <!-- 上传结果 -->
        <transition name="fade">
          <div v-if="uploadResult">
            <hr class="section-divider" />
            <div class="section-header">
              <span class="section-title">{{ uploadResult.success ? '导入成功' : '导入失败' }}</span>
            </div>
            <div class="section-body">
              <el-result
                :icon="uploadResult.success ? 'success' : 'error'"
                :title="uploadResult.success ? '导入成功' : '导入失败'"
                :sub-title="uploadResult.message"
              >
                <template #extra v-if="uploadResult.success && uploadResult.items">
                  <div class="result-stats">
                    <div class="stat-item">
                      <span class="stat-value">{{ uploadResult.items_count }}</span>
                      <span class="stat-label">数据项</span>
                    </div>
                    <div class="stat-item">
                      <span class="stat-value">{{ uploadResult.records_count }}</span>
                      <span class="stat-label">总记录</span>
                    </div>
                  </div>
                  <el-table :data="Object.entries(uploadResult.items).map(([k, v]) => ({name: k, count: v}))" size="small" class="result-table">
                    <el-table-column prop="name" label="数据项" />
                    <el-table-column prop="count" label="记录数" width="80" align="center" />
                  </el-table>
                </template>
              </el-result>
            </div>
          </div>
        </transition>
      </div>
    <!-- 完整模板弹窗 -->
      <!-- 右侧：示例数据 -->
      <div class="page-two-col-right">
        <div class="section-header">
          <span class="section-title">数据格式示例</span>
          <div class="section-actions">
            <el-button size="small" @click="loadFullTemplate" :loading="loadingTemplate">
              <el-icon><FolderOpened /></el-icon>
              查看完整模板
            </el-button>
          </div>
        </div>
        <div class="section-body">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            class="format-tip"
          >
            <template #title>
              <strong>Mock 数据格式说明</strong>
            </template>
            <template #default>
              <ul class="tip-list">
                <li>JSON 对象格式，key 为 DataItem 名称，value 为记录数组</li>
                <li>常见 DataItem: k8s.deployment.list, codeup.pipeline.list 等</li>
              </ul>
            </template>
          </el-alert>

          <div class="sample-container" v-loading="loadingSample">
            <el-scrollbar height="420px">
              <pre class="sample-json">{{ JSON.stringify(sampleData, null, 2) }}</pre>
            </el-scrollbar>
          </div>
        </div>
      </div>
    </div>
    <el-dialog
      v-model="showTemplateDialog"
      title="完整 Mock 数据模板"
      width="70%"
      class="template-dialog"
    >
      <el-scrollbar height="500px">
        <pre class="template-json">{{ JSON.stringify(fullTemplate, null, 2) }}</pre>
      </el-scrollbar>
      <template #footer>
        <el-button @click="downloadTemplate">
          <el-icon><Download /></el-icon>
          下载模板
        </el-button>
        <el-button type="primary" @click="showTemplateDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, genFileId } from 'element-plus'
import { uploadMockData, getMockSample, getMockTemplate } from '../api'

const uploadRef = ref(null)
const selectedFile = ref(null)
const previewData = ref(null)
const uploading = ref(false)
const uploadResult = ref(null)
const sampleData = ref({})
const loadingSample = ref(false)
const loadingTemplate = ref(false)
const showTemplateDialog = ref(false)
const fullTemplate = ref({})

// 文件变化处理
const handleFileChange = (file) => {
  selectedFile.value = file.raw
  uploadResult.value = null
  
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      previewData.value = JSON.parse(e.target.result)
    } catch (err) {
      ElMessage.error('JSON 格式错误')
      previewData.value = null
    }
  }
  reader.readAsText(file.raw)
}

// 文件数量超限处理
const handleExceed = (files) => {
  uploadRef.value.clearFiles()
  const file = files[0]
  file.uid = genFileId()
  uploadRef.value.handleStart(file)
}

// 上传文件
const handleUpload = async () => {
  if (!selectedFile.value) return
  
  uploading.value = true
  try {
    const result = await uploadMockData(selectedFile.value)
    uploadResult.value = result
    
    if (result.success) {
      ElMessage.success('数据导入成功')
      uploadRef.value.clearFiles()
      selectedFile.value = null
      previewData.value = null
    } else {
      ElMessage.error(result.message || '导入失败')
    }
  } catch (error) {
    ElMessage.error('上传失败: ' + (error.response?.data?.detail || error.message))
    uploadResult.value = {
      success: false,
      message: error.response?.data?.detail || error.message,
    }
  } finally {
    uploading.value = false
  }
}

// 加载示例数据
const loadSample = async () => {
  loadingSample.value = true
  try {
    const result = await getMockSample()
    if (result.success) {
      sampleData.value = result.data
    }
  } catch (error) {
    console.error('加载示例失败:', error)
  } finally {
    loadingSample.value = false
  }
}

// 加载完整模板
const loadFullTemplate = async () => {
  loadingTemplate.value = true
  try {
    const result = await getMockTemplate()
    if (result.success) {
      fullTemplate.value = result.data
      showTemplateDialog.value = true
    } else {
      ElMessage.warning(result.message)
    }
  } catch (error) {
    ElMessage.error('加载模板失败')
  } finally {
    loadingTemplate.value = false
  }
}

// 下载模板
const downloadTemplate = () => {
  const blob = new Blob([JSON.stringify(fullTemplate.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'mock_template.json'
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadSample()
})
</script>

<style scoped>
.mock-view {
  min-height: 100%;
}

.mock-left {
  width: 440px;
}

/* 上传区域 */
.upload-area {
  width: 100%;
}

:deep(.el-upload-dragger) {
  border: 1px dashed var(--color-border-2);
  border-radius: 6px;
  background: var(--color-bg-1);
  transition: all 0.2s ease;
  padding: 32px 20px;
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.upload-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.upload-icon {
  font-size: 40px;
  color: var(--color-primary);
}

.upload-text .main-text {
  font-size: 15px;
  color: var(--color-text-primary);
  font-weight: 500;
}

.upload-text .sub-text {
  font-size: 13px;
  color: var(--color-text-tertiary);
  margin-top: 4px;
}

.upload-text em {
  color: var(--color-primary);
  font-style: normal;
}

/* 预览区域 */
.preview-area {
  margin-top: 16px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  overflow: hidden;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: var(--color-bg-1);
  border-bottom: 1px solid var(--color-border);
  font-weight: 500;
  color: var(--color-text-primary);
  font-size: 13px;
}

.preview-json,
.sample-json,
.template-json {
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  padding: 14px;
  color: var(--color-text-primary);
}

.upload-btn {
  margin-top: 16px;
  width: 100%;
  height: 40px;
  border-radius: 6px;
}

/* 结果卡片 */
.result-stats {
  display: flex;
  justify-content: center;
  gap: 40px;
  margin-bottom: 16px;
}

.stat-item {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 26px;
  font-weight: 700;
  color: var(--color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--color-text-tertiary);
}

.result-table {
  border-radius: 6px;
  overflow: hidden;
}

/* 示例卡片 */
.format-tip {
  margin-bottom: 14px;
  border-radius: 6px;
}

.tip-list {
  margin: 6px 0 0;
  padding-left: 16px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.tip-list li {
  margin: 4px 0;
}

.sample-container {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-bg-1);
  overflow: hidden;
}

/* 模板弹窗 */
.template-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.template-json {
  background: #1E2430;
  color: #E5EBF3;
}
</style>
