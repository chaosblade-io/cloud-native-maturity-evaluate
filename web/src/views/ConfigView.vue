<template>
  <div class="config-view">
    <el-card class="config-card" v-loading="loading">
      <template #header>
        <div class="card-header">
          <div class="header-title">
            <el-icon class="header-icon"><Setting /></el-icon>
            <span>环境变量配置</span>
          </div>
          <div class="header-actions">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleFileChange"
            >
              <el-button>
                <el-icon><Upload /></el-icon>
                上传 .env 文件
              </el-button>
            </el-upload>
            <el-button type="primary" @click="handleSave" :loading="saving">
              <el-icon><Check /></el-icon>
              保存配置
            </el-button>
          </div>
        </div>
      </template>
      
      <el-alert
        title="配置说明"
        type="info"
        :closable="false"
        show-icon
        class="config-tip"
      >
        配置将保存到项目根目录的 .env 文件中。你可以手动填写，也可以上传已有的 .env 文件自动加载。
      </el-alert>
      
      <el-collapse v-model="activeGroups" class="config-collapse">
        <el-collapse-item
          v-for="group in groups"
          :key="group.name"
          :name="group.name"
        >
          <template #title>
            <div class="collapse-title">
              <el-icon class="group-icon"><Folder /></el-icon>
              <span class="group-name">{{ group.name }}</span>
              <el-tag size="small" type="info" class="group-count">
                {{ group.items.length }} 项
              </el-tag>
            </div>
          </template>
          
          <div class="group-desc" v-if="group.description">
            {{ group.description }}
          </div>
          
          <div class="config-grid">
            <div
              v-for="item in group.items"
              :key="item.key"
              class="config-item"
            >
              <label class="item-label">
                {{ item.key }}
                <el-tag v-if="item.required" size="small" type="danger" class="required-tag">必填</el-tag>
              </label>
              <el-input
                v-model="config[item.key]"
                :placeholder="item.description"
                :type="isSecret(item.key) ? 'password' : 'text'"
                show-password
                clearable
                class="item-input"
              />
              <span class="item-desc">{{ item.description }}</span>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getConfig, saveConfig, uploadEnvFile } from '../api'

const uploadRef = ref(null)
const loading = ref(false)
const saving = ref(false)
const groups = ref([])
const activeGroups = ref(['阿里云基础凭证'])

const config = reactive({})

// 判断是否为敏感字段
const isSecret = (key) => {
  return key.includes('SECRET') || key.includes('TOKEN') || key.includes('PASSWORD')
}

// 加载配置结构（不填充值，保持空白表单）
const loadConfig = async () => {
  loading.value = true
  try {
    const result = await getConfig()
    if (result.success) {
      groups.value = result.groups
      // 填充已有的配置值
      if (result.config) {
        Object.assign(config, result.config)
      }
    } else {
      ElMessage.error(result.message || '加载配置失败')
    }
  } catch (error) {
    ElMessage.error('加载配置失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

// 保存配置
const handleSave = async () => {
  saving.value = true
  try {
    const result = await saveConfig(config)
    if (result.success) {
      ElMessage.success('配置保存成功')
    } else {
      ElMessage.error(result.message || '保存失败')
    }
  } catch (error) {
    ElMessage.error('保存配置失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

// 上传 .env 文件
const handleFileChange = async (uploadFile) => {
  if (!uploadFile.raw) return
  
  loading.value = true
  try {
    const result = await uploadEnvFile(uploadFile.raw)
    if (result.success) {
      // 更新配置
      groups.value = result.groups
      Object.assign(config, result.config)
      ElMessage.success(result.message || '文件加载成功')
    } else {
      ElMessage.error(result.message || '解析文件失败')
    }
  } catch (error) {
    ElMessage.error('上传文件失败: ' + error.message)
  } finally {
    loading.value = false
    // 清除文件列表
    uploadRef.value?.clearFiles()
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.config-view {
  max-width: 1000px;
  margin: 0 auto;
}

.config-card {
  border-radius: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
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

.config-tip {
  margin-bottom: 20px;
  border-radius: 8px;
}

.config-collapse {
  border: none;
}

:deep(.el-collapse-item__header) {
  height: 56px;
  padding: 0 16px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  margin-bottom: 8px;
}

:deep(.el-collapse-item__wrap) {
  border: none;
}

:deep(.el-collapse-item__content) {
  padding: 16px 0;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.group-icon {
  color: #667eea;
  font-size: 18px;
}

.group-name {
  font-weight: 500;
  color: #1f2937;
}

.group-count {
  margin-left: auto;
  margin-right: 10px;
}

.group-desc {
  color: #64748b;
  font-size: 13px;
  margin-bottom: 16px;
  padding: 0 4px;
}

.config-grid {
  display: grid;
  gap: 20px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px;
  background: #fafbfc;
  border-radius: 10px;
  border: 1px solid #e8ecf1;
  transition: all 0.2s ease;
}

.config-item:hover {
  border-color: #667eea;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.1);
}

.item-label {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 8px;
}

.required-tag {
  font-size: 10px;
}

.item-input {
  margin-top: 4px;
}

:deep(.item-input .el-input__wrapper) {
  border-radius: 8px;
}

.item-desc {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}
</style>
