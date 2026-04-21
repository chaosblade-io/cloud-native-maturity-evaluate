<template>
  <div class="knowledge-view">
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card class="knowledge-card">
          <template #header>
            <div class="card-header">
              <span>上传文档</span>
            </div>
          </template>

          <el-upload
            class="knowledge-uploader"
            drag
            multiple
            :auto-upload="false"
            :show-file-list="false"
            accept=".md,text/markdown"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽一个或多个 Markdown 文件到这里，或点击上传</div>
            <template #tip>
              <div class="el-upload__tip">仅支持 .md 文件，支持批量上传</div>
            </template>
          </el-upload>

          <div class="upload-panel" v-if="pendingFiles.length">
            <div class="pending-file">待上传 {{ pendingFiles.length }} 个文件</div>
            <div class="pending-files-list">
              <el-tag v-for="file in pendingFiles" :key="file.name + file.size" closable @close="removePendingFile(file)">
                {{ file.name }}
              </el-tag>
            </div>
            <el-input
              v-model="uploadTagsText"
              placeholder="标签，多个用英文逗号分隔。例如: resilience,incident"
              clearable
            />
            <div class="upload-actions">
              <el-button @click="clearPendingFile">取消</el-button>
              <el-button type="primary" :loading="uploading" @click="submitUpload">上传</el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card class="knowledge-card">
          <template #header>
            <div class="card-header">
              <span>知识库文档</span>
              <el-button text @click="loadDocs">刷新</el-button>
            </div>
          </template>

          <el-table :data="docs" v-loading="loading" empty-text="暂无知识库文档">
            <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
            <el-table-column prop="name" label="文件名" min-width="180" show-overflow-tooltip />
            <el-table-column label="标签" min-width="220">
              <template #default="{ row }">
                <div class="tags-cell">
                  <el-tag v-for="tag in row.tags || []" :key="tag" size="small" type="info">{{ tag }}</el-tag>
                  <span v-if="!(row.tags || []).length" class="empty-text">无标签</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="100">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" min-width="180" />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" @click="openTagsDialog(row)">标签</el-button>
                  <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="showTagsDialog" title="编辑标签" width="480px">
      <div class="dialog-content">
        <div class="dialog-title">{{ activeDoc?.title || activeDoc?.name || '-' }}</div>
        <el-input
          v-model="editingTagsText"
          placeholder="标签，多个用英文逗号分隔"
          clearable
        />
      </div>
      <template #footer>
        <el-button @click="showTagsDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingTags" @click="saveTags">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteKnowledgeDoc, getKnowledgeDocs, updateKnowledgeDocTags, uploadKnowledgeDoc } from '../api'

const loading = ref(false)
const uploading = ref(false)
const savingTags = ref(false)
const docs = ref([])
const pendingFiles = ref([])
const uploadTagsText = ref('')
const showTagsDialog = ref(false)
const activeDoc = ref(null)
const editingTagsText = ref('')

const splitTags = (value) => {
  if (!value) return []
  return value.split(',').map(item => item.trim()).filter(Boolean)
}

const formatSize = (size = 0) => {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const loadDocs = async () => {
  loading.value = true
  try {
    const result = await getKnowledgeDocs()
    if (result.success) {
      docs.value = result.docs || []
      return
    }
    ElMessage.error(result.message || '加载知识库文档失败')
  } catch (error) {
    ElMessage.error('加载知识库文档失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const handleFileChange = (uploadFile, uploadFiles = []) => {
  pendingFiles.value = uploadFiles
    .map(item => item.raw)
    .filter(Boolean)
}

const handleFileRemove = (_, uploadFiles = []) => {
  pendingFiles.value = uploadFiles
    .map(item => item.raw)
    .filter(Boolean)
}

const removePendingFile = (targetFile) => {
  pendingFiles.value = pendingFiles.value.filter(file => !(file.name === targetFile.name && file.size === targetFile.size))
}

const clearPendingFile = () => {
  pendingFiles.value = []
  uploadTagsText.value = ''
}

const submitUpload = async () => {
  if (!pendingFiles.value.length) {
    ElMessage.warning('请先选择至少一个 Markdown 文件')
    return
  }

  uploading.value = true
  try {
    const result = await uploadKnowledgeDoc(pendingFiles.value, splitTags(uploadTagsText.value))
    if (result.success) {
      ElMessage.success(`知识库文档上传成功，共 ${result.docs?.length || pendingFiles.value.length} 个文件`)
      clearPendingFile()
      await loadDocs()
      return
    }
    ElMessage.error(result.message || '知识库文档上传失败')
  } catch (error) {
    ElMessage.error('知识库文档上传失败: ' + error.message)
  } finally {
    uploading.value = false
  }
}

const openTagsDialog = (doc) => {
  activeDoc.value = doc
  editingTagsText.value = (doc.tags || []).join(', ')
  showTagsDialog.value = true
}

const saveTags = async () => {
  if (!activeDoc.value) return

  savingTags.value = true
  try {
    const result = await updateKnowledgeDocTags(activeDoc.value.id, splitTags(editingTagsText.value))
    if (result.success) {
      ElMessage.success('标签更新成功')
      showTagsDialog.value = false
      await loadDocs()
      return
    }
    ElMessage.error(result.message || '标签更新失败')
  } catch (error) {
    ElMessage.error('标签更新失败: ' + error.message)
  } finally {
    savingTags.value = false
  }
}

const handleDelete = async (doc) => {
  try {
    await ElMessageBox.confirm(`确认删除知识库文档 ${doc.title || doc.name} 吗？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    const result = await deleteKnowledgeDoc(doc.id)
    if (result.success) {
      ElMessage.success('知识库文档已删除')
      await loadDocs()
      return
    }
    ElMessage.error(result.message || '删除知识库文档失败')
  } catch (error) {
    ElMessage.error('删除知识库文档失败: ' + error.message)
  }
}

onMounted(() => {
  loadDocs()
})
</script>

<style scoped>
.knowledge-view {
  max-width: 1400px;
  margin: 0 auto;
}

.knowledge-card {
  border-radius: 16px;
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.knowledge-uploader {
  width: 100%;
}

.upload-panel {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pending-files-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pending-file,
.dialog-title,
.empty-text {
  color: #64748b;
}

.upload-actions,
.row-actions {
  display: flex;
  gap: 8px;
}

.tags-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.knowledge-option-id {
  color: #94a3b8;
}

.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
