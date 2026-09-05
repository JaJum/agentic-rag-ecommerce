<template>
  <!-- 引用溯源面板（需求 2 核心差异化）：展示回答引用的知识库片段原文 -->
  <div class="panel">
    <div class="panel-head">
      <span>引用溯源</span>
      <el-tag v-if="citations.length" size="small" type="info">{{ citations.length }} 条</el-tag>
    </div>
    <el-empty v-if="!citations.length" description="暂无引用" :image-size="60" />
    <div
      v-for="c in citations"
      :key="c.n ?? c.citation_no"
      class="cite-card"
      :class="{ active: (c.n ?? c.citation_no) === activeN, uncited: !c.cited }"
      :ref="(el) => setRef(c.n ?? c.citation_no, el)"
    >
      <div class="cite-head">
        <el-tag size="small" :type="c.cited ? 'primary' : 'info'">
          [{{ c.n ?? c.citation_no }}]{{ c.cited ? '' : ' 参考未引用' }}
        </el-tag>
        <span class="doc-name" :title="c.doc_name">{{ c.doc_name || '未知来源' }}</span>
        <span v-if="c.score != null" class="score">{{ (c.score * 100).toFixed(0) }}%</span>
      </div>
      <el-collapse>
        <el-collapse-item title="展开原文片段">
          <pre class="snippet">{{ c.snippet }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  citations: { type: Array, default: () => [] },
  activeN: { type: Number, default: 0 }
})

const refs = ref({})

/** 记录卡片元素（供点击引用时滚动定位） */
function setRef(n, el) {
  if (el) refs.value[n] = el
}

// 高亮引用变化时滚动到对应卡片
watch(
  () => props.activeN,
  async (n) => {
    if (n && refs.value[n]) {
      await nextTick()
      refs.value[n].scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }
)
</script>

<style scoped>
.panel { padding: 12px; overflow-y: auto; height: 100%; }
.panel-head { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 12px; }
.cite-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  transition: border-color 0.2s;
}
.cite-card.active { border-color: #409eff; background: #ecf5ff; }
.cite-card.uncited { opacity: 0.75; }
.cite-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.doc-name { font-size: 12px; color: #606266; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.score { font-size: 12px; color: #909399; }
.snippet {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
  font-family: inherit;
}
</style>
