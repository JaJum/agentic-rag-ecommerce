<template>
  <!-- Markdown 渲染器：支持代码高亮 + [n] 引用上标可点击（需求 2） -->
  <div class="md-body" v-html="html" @click="onClick"></div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

const props = defineProps({
  content: { type: String, default: '' }
})
const emit = defineEmits(['cite'])

// Markdown 渲染器（代码块高亮）
const md = new MarkdownIt({
  linkify: true,
  highlight(code, lang) {
    try {
      return hljs.highlight(code, { language: lang }).value
    } catch {
      return md.utils.escapeHtml(code)
    }
  }
})

// 渲染并把 [n] 替换为可点击的引用上标
const html = computed(() => {
  const raw = md.render(props.content || '')
  return raw.replace(/\[(\d+)\]/g, '<sup class="cite-tag" data-n="$1">[$1]</sup>')
})

/** 点击引用上标 → 通知父组件打开溯源面板 */
function onClick(e) {
  const tag = e.target.closest('.cite-tag')
  if (tag) {
    emit('cite', Number(tag.dataset.n))
  }
}
</script>

<style scoped>
.md-body :deep(pre) {
  background: #f6f8fa;
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
}
.md-body :deep(code) { font-family: Consolas, Monaco, monospace; font-size: 13px; }
.md-body :deep(p) { line-height: 1.7; margin: 6px 0; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 20px; }
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid #e4e7ed; padding: 6px 10px; }
.md-body :deep(.cite-tag) {
  color: #409eff;
  cursor: pointer;
  font-size: 11px;
  padding: 0 2px;
}
.md-body :deep(.cite-tag:hover) { text-decoration: underline; }
</style>
