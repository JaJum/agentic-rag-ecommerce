<template>
  <!-- 问答主界面（需求 2/3/4）：左=会话列表 中=流式对话 右=引用溯源 -->
  <div class="chat-layout">
    <!-- 左侧：会话列表 -->
    <aside class="sessions">
      <el-button type="primary" class="new-btn" :icon="Plus" @click="onNewSession">
        新建会话
      </el-button>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === activeSessionId }"
          @click="onSelectSession(s)"
        >
          <span class="title" :title="s.title">{{ s.title }}</span>
          <el-dropdown trigger="click" @command="(cmd) => onSessionCmd(cmd, s)" @click.stop>
            <el-icon class="more" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </aside>

    <!-- 中间：对话区 -->
    <main class="chat-main">
      <div ref="msgArea" class="messages">
        <el-empty v-if="!messages.length" description="开始提问吧～支持商品参数、价格、售后等问题" />
        <div v-for="m in messages" :key="m.id" class="msg-row" :class="m.role">
          <div class="bubble">
            <!-- 助手消息：来源标签 + Markdown 渲染 + 引用可点击 -->
            <template v-if="m.role === 'assistant'">
              <el-tag v-if="m.status === 'general'" size="small" type="info" class="src-tag">
                AI 通用回答 · 非知识库内容
              </el-tag>
              <el-tag v-else-if="m.status === 'fallback'" size="small" type="warning" class="src-tag">
                知识库未命中
              </el-tag>
              <MarkdownRenderer :content="m.content" @cite="(n) => onCiteClick(m, n)" />
            </template>
            <div v-else class="user-text">{{ m.content }}</div>
            <!-- 助手消息操作条 -->
            <div v-if="m.role === 'assistant' && !m.streaming" class="actions">
              <el-button link size="small" @click="onFeedback(m, 1)">
                <el-icon :color="m.rating === 1 ? '#67c23a' : ''"><CircleCheck /></el-icon>赞
              </el-button>
              <el-button link size="small" @click="onFeedback(m, -1)">
                <el-icon :color="m.rating === -1 ? '#f56c6c' : ''"><CircleClose /></el-icon>踩
              </el-button>
              <el-button v-if="m.citations?.length" link size="small" @click="onCiteClick(m, 1)">
                引用 {{ m.citations.length }}
              </el-button>
            </div>
            <!-- 流式中 -->
            <div v-if="m.streaming" class="streaming-tip">生成中…</div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-bar">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          :placeholder="streaming ? '正在生成中…' : '输入商品相关问题，Enter 发送'"
          :disabled="streaming"
          @keydown.enter.exact.prevent="onSend"
        />
        <div class="send-btns">
          <el-button v-if="streaming" type="danger" @click="onStop">停止生成</el-button>
          <el-button v-else type="primary" :disabled="!input.trim()" @click="onSend">
            发送
          </el-button>
          <el-button @click="onExport">导出对话</el-button>
        </div>
      </div>
    </main>

    <!-- 右侧：引用溯源面板（可折叠） -->
    <aside v-show="panelVisible" class="citations">
      <CitationPanel :citations="activeCitations" :active-n="activeCiteN" />
    </aside>
    <el-button
      class="panel-toggle"
      size="small"
      @click="panelVisible = !panelVisible"
    >
      {{ panelVisible ? '收起引用' : '引用溯源' }}
    </el-button>
  </div>
</template>

<script setup>
// 问答主逻辑：会话管理 + SSE 流式渲染 + 引用溯源联动
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, CircleClose, MoreFilled, Plus } from '@element-plus/icons-vue'
import {
  createSession,
  deleteSession,
  exportSession,
  feedback,
  getSessionMessages,
  listSessions,
  renameSession,
  stopGeneration
} from '../../api/chat'
import { useSSE } from '../../composables/useSSE'
import MarkdownRenderer from '../../components/chat/MarkdownRenderer.vue'
import CitationPanel from '../../components/chat/CitationPanel.vue'

const { streamChat } = useSSE()

const sessions = ref([])
const activeSessionId = ref(null)
const messages = ref([])
const input = ref('')
const streaming = ref(false)
const panelVisible = ref(true)
const activeCitations = ref([])
const activeCiteN = ref(0)
const msgArea = ref()
let abortController = null

onMounted(loadSessions)

/** 加载会话列表（自动选中最近会话） */
async function loadSessions() {
  sessions.value = await listSessions()
  if (!activeSessionId.value && sessions.value.length) {
    await onSelectSession(sessions.value[0])
  }
}

/** 新建会话 */
async function onNewSession() {
  const s = await createSession()
  sessions.value.unshift(s)
  activeSessionId.value = s.id
  messages.value = []
  activeCitations.value = []
}

/** 切换会话：拉取历史（需求 4：重登可找回） */
async function onSelectSession(s) {
  if (streaming.value) return
  activeSessionId.value = s.id
  messages.value = await getSessionMessages(s.id)
  activeCitations.value = []
  await scrollToBottom()
}

/** 会话重命名 / 删除 */
async function onSessionCmd(cmd, s) {
  if (cmd === 'rename') {
    const { value } = await ElMessageBox.prompt('输入新标题', '重命名会话', {
      inputValue: s.title
    })
    if (value?.trim()) {
      await renameSession(s.id, value.trim())
      s.title = value.trim()
    }
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm(`确定删除会话「${s.title}」？`, '删除确认', { type: 'warning' })
    await deleteSession(s.id)
    sessions.value = sessions.value.filter((x) => x.id !== s.id)
    if (activeSessionId.value === s.id) {
      activeSessionId.value = null
      messages.value = []
      await loadSessions()
    }
  }
}

/** 发送问题：SSE 流式渲染回答（需求 2） */
async function onSend() {
  const query = input.value.trim()
  if (!query || streaming.value) return
  input.value = ''

  // 本地先渲染用户消息 + 助手占位
  const userMsg = { id: 'u' + Date.now(), role: 'user', content: query }
  const botMsg = { id: 'b' + Date.now(), role: 'assistant', content: '', citations: [], streaming: true }
  messages.value.push(userMsg, botMsg)
  streaming.value = true
  activeCitations.value = botMsg.citations
  await scrollToBottom()

  abortController = new AbortController()
  try {
    await streamChat(
      { sessionId: activeSessionId.value, query },
      {
        onEvent(event, data) {
          if (event === 'meta') {
            activeSessionId.value = data.session_id
            if (data.answer_source === 'general') botMsg.status = 'general'
          } else if (event === 'citation') {
            botMsg.citations.push(data)
          } else if (event === 'reasoning') {
            botMsg.content += data.delta // thinking 开启时展示思考过程
          } else if (event === 'token') {
            botMsg.content += data.delta
            scrollToBottom()
          } else if (event === 'fallback') {
            botMsg.content = '抱歉，知识库中未找到相关内容。'
            botMsg.status = 'fallback'
          } else if (event === 'done') {
            botMsg.streaming = false
            botMsg.id = data.message_id
            if (data.answer_source === 'general') botMsg.status = 'general'
            else if (data.answer_source === 'fallback') botMsg.status = 'fallback'
          } else if (event === 'error') {
            botMsg.content = `⚠️ ${data.message}`
            botMsg.streaming = false
          }
        }
      },
      abortController.signal
    )
  } catch (e) {
    if (e.name !== 'AbortError') {
      ElMessage.error('网络异常，请重试')
      botMsg.content = botMsg.content || '⚠️ 生成失败，请重试'
    }
    botMsg.streaming = false
  } finally {
    streaming.value = false
    abortController = null
    loadSessions() // 刷新会话（标题/时间更新）
    await scrollToBottom()
  }
}

/** 停止生成（服务端停止 + 客户端中断） */
async function onStop() {
  if (activeSessionId.value) {
    await stopGeneration(activeSessionId.value).catch(() => {})
  }
  abortController?.abort()
}

/** 点击 [n] 引用 → 右侧溯源面板定位高亮 */
function onCiteClick(m, n) {
  activeCitations.value = m.citations || []
  activeCiteN.value = n
  panelVisible.value = true
}

/** 点赞/点踩（需求 8） */
async function onFeedback(m, rating) {
  try {
    await feedback(m.id, rating)
    m.rating = rating
    ElMessage.success('感谢反馈')
  } catch {
    ElMessage.error('反馈失败')
  }
}

/** 导出对话 Markdown（需求 8） */
async function onExport() {
  if (!activeSessionId.value) return
  const { markdown } = await exportSession(activeSessionId.value)
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `对话导出-${new Date().toLocaleDateString('zh-CN')}.md`
  a.click()
  URL.revokeObjectURL(a.href)
}

/** 滚动到底部 */
async function scrollToBottom() {
  await nextTick()
  msgArea.value?.scrollTo({ top: msgArea.value.scrollHeight, behavior: 'smooth' })
}
</script>

<style scoped>
.chat-layout { display: flex; height: calc(100vh - 56px); position: relative; }

/* 左侧会话列表 */
.sessions { width: 240px; background: #fff; border-right: 1px solid #e4e7ed; display: flex; flex-direction: column; }
.new-btn { margin: 12px; }
.session-list { flex: 1; overflow-y: auto; padding: 0 8px; }
.session-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 4px;
}
.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #ecf5ff; color: #409eff; }
.session-item .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.session-item .more { color: #909399; }

/* 中间对话区 */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; background: #f5f7fa; }
.messages { flex: 1; overflow-y: auto; padding: 20px; }
.msg-row { display: flex; margin-bottom: 16px; }
.msg-row.user { justify-content: flex-end; }
.msg-row .bubble {
  max-width: 72%; padding: 10px 14px; border-radius: 10px; background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}
.msg-row.user .bubble { background: #409eff; color: #fff; }
.user-text { white-space: pre-wrap; line-height: 1.6; }
.src-tag { display: flex; width: fit-content; margin-bottom: 6px; }
.actions { margin-top: 6px; display: flex; gap: 2px; }
.streaming-tip { color: #909399; font-size: 12px; margin-top: 4px; }

/* 输入区 */
.input-bar { background: #fff; border-top: 1px solid #e4e7ed; padding: 12px 20px; }
.send-btns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }

/* 右侧引用面板 */
.citations { width: 320px; background: #fff; border-left: 1px solid #e4e7ed; }
.panel-toggle { position: absolute; right: 12px; top: 12px; z-index: 10; }
</style>
