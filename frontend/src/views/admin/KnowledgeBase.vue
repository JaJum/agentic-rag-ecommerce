<template>
  <!-- 知识库管理（仅 admin）：上传 → 入库进度 → 分块预览 / 重建索引 / 删除（需求 1） -->
  <div class="page">
    <el-card>
      <div class="toolbar">
        <h2>知识库管理</h2>
        <el-button type="primary" :icon="Upload" @click="uploadVisible = true">
          上传文档
        </el-button>
      </div>

      <!-- 文档列表 -->
      <el-table :data="docs" v-loading="loading" empty-text="暂无文档，请上传">
        <el-table-column prop="orig_name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="70">
          <template #default="{ row }">
            <el-tag size="small">{{ row.file_type.toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="入库状态" width="200">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusName(row.status) }}</el-tag>
            <el-progress
              v-if="isRunning(row.status)"
              :percentage="row.progress"
              :stroke-width="4"
              class="progress"
            />
            <span v-if="row.status === 'failed' && row.error_msg" class="err">
              {{ row.error_msg.slice(0, 40) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="preview(row)">分块预览</el-button>
            <el-button link type="warning" size="small" @click="onReindex(row)">重建</el-button>
            <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadVisible" title="上传文档" width="520px">
      <el-upload
        drag
        multiple
        :auto-upload="false"
        :file-list="fileList"
        :on-change="onFileChange"
        :on-remove="onFileRemove"
        accept=".md,.txt,.pdf,.docx,.csv,.xlsx"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 md / txt / pdf / docx / csv / xlsx，单文件 ≤ 50MB</div>
        </template>
      </el-upload>
      <el-form-item label="内容类型" class="type-select">
        <el-select v-model="docType">
          <el-option label="自动识别" value="auto" />
          <el-option label="商品参数表" value="param" />
          <el-option label="FAQ 问答" value="faq" />
          <el-option label="详情文案" value="prose" />
        </el-select>
      </el-form-item>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!fileList.length" @click="onUpload">
          开始上传
        </el-button>
      </template>
    </el-dialog>

    <!-- 分块预览弹窗 -->
    <ChunkPreviewDialog v-model:visible="previewVisible" :doc-id="previewDocId" />
  </div>
</template>

<script setup>
// 知识库管理逻辑：上传 → 轮询入库进度 → 分块预览/重建/删除
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, UploadFilled } from '@element-plus/icons-vue'
import {
  deleteDocument,
  listDocuments,
  reindexDocument,
  uploadDocuments
} from '../../api/document'
import ChunkPreviewDialog from './ChunkPreviewDialog.vue'

const docs = ref([])
const loading = ref(false)
const uploadVisible = ref(false)
const uploading = ref(false)
const fileList = ref([])
const docType = ref('auto')
const previewVisible = ref(false)
const previewDocId = ref('')
let pollTimer = null

onMounted(load)
onUnmounted(() => clearTimeout(pollTimer))

/** 加载文档列表；有进行中的任务则 2 秒后继续轮询（进度状态机可视化） */
async function load() {
  loading.value = true
  try {
    docs.value = await listDocuments()
    if (docs.value.some((d) => isRunning(d.status))) {
      clearTimeout(pollTimer)
      pollTimer = setTimeout(load, 2000)
    }
  } finally {
    loading.value = false
  }
}

/** 上传文件选择变化 */
function onFileChange(file, list) {
  fileList.value = list
}
/** 移除待传文件 */
function onFileRemove(file, list) {
  fileList.value = list
}

/** 执行上传：成功后刷新列表并开始轮询进度 */
async function onUpload() {
  uploading.value = true
  try {
    await uploadDocuments(fileList.value.map((f) => f.raw), docType.value)
    ElMessage.success('上传成功，后台入库中')
    uploadVisible.value = false
    fileList.value = []
    load()
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

/** 打开分块预览 */
function preview(row) {
  previewDocId.value = row.id
  previewVisible.value = true
}

/** 重建索引（重跑入库链路） */
async function onReindex(row) {
  try {
    await reindexDocument(row.id)
    ElMessage.success('重建任务已提交')
    load()
  } catch (e) {
    ElMessage.error(e.message || '重建失败')
  }
}

/** 删除文档（二次确认） */
async function onDelete(row) {
  await ElMessageBox.confirm(`确定删除「${row.orig_name}」及其全部分块？`, '删除确认', {
    type: 'warning'
  })
  try {
    await deleteDocument(row.id)
    ElMessage.success('删除成功')
    load()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

/** 是否入库进行中（用于进度条与轮询） */
function isRunning(status) {
  return ['uploaded', 'parsing', 'cleaning', 'chunking', 'embedding', 'indexing'].includes(status)
}

/** 状态 → 标签颜色 */
function statusTag(status) {
  return { completed: 'success', failed: 'danger' }[status] || 'warning'
}

/** 状态中文名 */
function statusName(status) {
  return {
    uploaded: '排队中',
    parsing: '解析中',
    cleaning: '清洗中',
    chunking: '分块中',
    embedding: '向量化中',
    indexing: '建索引中',
    completed: '已完成',
    failed: '失败'
  }[status] || status
}

/** 字节数格式化 */
function formatSize(size) {
  if (size > 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + ' MB'
  return (size / 1024).toFixed(1) + ' KB'
}

/** 时间格式化 */
function formatTime(t) {
  return new Date(t).toLocaleString('zh-CN')
}
</script>

<style scoped>
.page { padding: 24px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.progress { width: 120px; margin-top: 4px; }
.err { color: #f56c6c; font-size: 12px; display: block; }
.type-select { margin-top: 16px; }
</style>
