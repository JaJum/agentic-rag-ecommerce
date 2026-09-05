<template>
  <!-- 分块预览弹窗：验证差异化分块效果（参数表键值化 / FAQ 绑定 / 文案分节） -->
  <el-dialog
    :model-value="visible"
    title="分块预览"
    width="760px"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div v-if="loading" class="loading">加载中…</div>
    <template v-else>
      <el-empty v-if="!items.length" description="暂无分块（文档可能入库失败）" />
      <div v-for="c in items" :key="c.id" class="chunk-card">
        <div class="chunk-head">
          <el-tag size="small" :type="typeTag(c.chunk_type)">
            #{{ c.seq }} {{ typeName(c.chunk_type) }}
          </el-tag>
          <span class="meta">{{ formatMeta(c.meta) }}</span>
          <span class="len">{{ c.char_len }} 字</span>
        </div>
        <pre class="chunk-text">{{ c.text }}</pre>
      </div>
      <el-pagination
        v-model:current-page="page"
        :page-size="size"
        :total="total"
        layout="prev, pager, next, total"
        class="pager"
        @current-change="load"
      />
    </template>
  </el-dialog>
</template>

<script setup>
// 弹窗打开时加载分块（分页）
import { ref, watch } from 'vue'
import { getDocumentChunks } from '../../api/document'

const props = defineProps({
  visible: Boolean,
  docId: String
})
const emit = defineEmits(['update:visible'])

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 10

// 打开弹窗时加载第一页
watch(
  () => props.visible,
  (v) => {
    if (v && props.docId) {
      page.value = 1
      load()
    }
  }
)

/** 加载分块数据 */
async function load() {
  loading.value = true
  try {
    const data = await getDocumentChunks(props.docId, page.value, size)
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

/** 分块类型 → 标签颜色 */
function typeTag(t) {
  return { param: 'success', faq: 'warning', prose: 'info' }[t] || 'info'
}

/** 分块类型中文名 */
function typeName(t) {
  return { param: '参数表', faq: 'FAQ', prose: '文案' }[t] || t
}

/** 元数据展示（截断） */
function formatMeta(meta) {
  if (!meta) return ''
  return Object.entries(meta)
    .map(([k, v]) => `${k}=${v}`)
    .join('  ')
}
</script>

<style scoped>
.loading { text-align: center; padding: 32px; color: #909399; }
.chunk-card { border: 1px solid #e4e7ed; border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; }
.chunk-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.meta { color: #909399; font-size: 12px; flex: 1; }
.len { color: #c0c4cc; font-size: 12px; }
.chunk-text { white-space: pre-wrap; word-break: break-all; font-size: 13px; line-height: 1.6; color: #303133; margin: 0; max-height: 160px; overflow-y: auto; font-family: inherit; }
.pager { margin-top: 12px; justify-content: flex-end; display: flex; }
</style>
