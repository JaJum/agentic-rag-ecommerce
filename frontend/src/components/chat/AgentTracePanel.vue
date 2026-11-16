<template>
  <!-- Agent 执行轨迹面板：节点/工具/参数/结果/耗时，默认折叠 -->
  <div class="trace-panel">
    <div class="trace-head" @click="expanded = !expanded">
      <el-icon class="chev" :class="{ open: expanded }"><ArrowRight /></el-icon>
      <span class="title">Agent 执行轨迹</span>
      <el-tag v-if="meta?.route" size="small" type="primary">{{ routeLabel }}</el-tag>
      <el-tag v-if="meta?.steps" size="small" type="info">{{ meta.steps }} 步</el-tag>
      <el-tag v-if="failed" size="small" type="danger">含失败步骤</el-tag>
      <span v-if="meta?.latency_ms" class="latency">{{ meta.latency_ms }}ms</span>
      <span class="count">{{ trace.length }} 条</span>
    </div>
    <el-collapse-transition>
      <div v-show="expanded" class="trace-body">
        <el-empty v-if="!trace.length" description="暂无执行轨迹" :image-size="48" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="(t, i) in trace"
            :key="i"
            :type="itemType(t)"
            :hollow="t.ok === 0"
          >
            <div class="step-head">
              <el-tag size="small" :type="itemType(t)" effect="plain">
                {{ nodeLabel(t) }}
              </el-tag>
              <span v-if="t.tool_name" class="tool">{{ t.tool_name }}</span>
              <span v-if="t.ok === 0" class="fail">失败</span>
            </div>
            <div v-if="t.args_preview" class="line">
              <span class="k">参数</span><code>{{ t.args_preview }}</code>
            </div>
            <div v-if="t.result_preview" class="line">
              <span class="k">结果</span><code>{{ t.result_preview }}</code>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-collapse-transition>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'

const props = defineProps({
  trace: { type: Array, default: () => [] },
  meta: { type: Object, default: null },
  streaming: { type: Boolean, default: false }
})

const expanded = ref(false)
watch(
  () => props.streaming,
  (v) => { expanded.value = v },
  { immediate: true }
)

const NODE_LABEL = {
  route: '路由',
  retrieval: '检索',
  agent: '决策',
  tool_call: '调用工具',
  tool_result: '工具结果',
  finalize: '生成回答',
  verify: '引用校验',
  general_chat: '通用回答'
}
const ROUTE_LABEL = {
  chitchat: '闲聊',
  kb_simple: '单跳知识',
  business: '业务办理',
  multi_hop: '多跳对比'
}

const routeLabel = computed(() => ROUTE_LABEL[props.meta?.route] || props.meta?.route || '')
const failed = computed(() => props.trace.some((t) => t.ok === 0))

function nodeLabel(t) {
  return NODE_LABEL[t.node] || t.node || '步骤'
}

function itemType(t) {
  if (t.ok === 0) return 'danger'
  if (t.node === 'tool_call' || t.node === 'tool_result') return 'primary'
  if (t.node === 'verify') return 'success'
  return 'info'
}
</script>

<style scoped>
.trace-panel {
  margin-top: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}
.trace-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.trace-head .title { font-weight: 600; color: var(--el-text-color-regular); }
.trace-head .chev { transition: transform 0.2s; }
.trace-head .chev.open { transform: rotate(90deg); }
.trace-head .latency, .trace-head .count { margin-left: auto; }
.trace-head .count { margin-left: 8px; }
.trace-body { padding: 4px 12px 8px; }
.trace-body :deep(.el-timeline) { padding-left: 2px; }
.step-head { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.step-head .tool { font-family: ui-monospace, Consolas, monospace; color: var(--el-color-primary); }
.step-head .fail { color: var(--el-color-danger); font-size: 12px; }
.line { margin-top: 2px; font-size: 12px; line-height: 1.5; word-break: break-all; }
.line .k { color: var(--el-text-color-secondary); margin-right: 6px; }
.line code { color: var(--el-text-color-regular); }
</style>
