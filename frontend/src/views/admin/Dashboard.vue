<template>
  <!-- 统计仪表盘（仅 admin，M6）：概览卡片 + 问答趋势/Top 查询/反馈图表 -->
  <div class="page">
    <!-- 概览指标卡片 -->
    <el-row :gutter="16" class="cards">
      <el-col v-for="c in cardList" :key="c.label" :span="6">
        <el-card shadow="hover">
          <div class="card-value">{{ c.value }}</div>
          <div class="card-label">{{ c.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区 -->
    <el-row :gutter="16" class="charts">
      <el-col :span="14">
        <el-card header="近 7 日问答量趋势">
          <div ref="trendChart" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card header="知识库命中率">
          <div ref="hitChart" class="chart"></div>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16" class="charts">
      <el-col :span="12">
        <el-card header="Top 5 高频查询">
          <div ref="topChart" class="chart"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="用户反馈占比">
          <div ref="feedbackChart" class="chart"></div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
// 仪表盘：GET /admin/stats → ECharts 四图（需求 8 + M6 验收：与 qa_logs 一致）
import { computed, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import request from '../../api/request'

const stats = ref(null)
const trendChart = ref()
const hitChart = ref()
const topChart = ref()
const feedbackChart = ref()
let charts = []

// 概览卡片数据
const cardList = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: '注册用户', value: s.overview.user_count },
    { label: '知识库文档', value: s.overview.document_count },
    { label: '问答次数', value: s.quality.total_queries },
    { label: '命中率', value: (s.quality.hit_rate * 100).toFixed(1) + '%' }
  ]
})

onMounted(async () => {
  stats.value = await request.get('/admin/stats')
  renderCharts()
})
onUnmounted(() => charts.forEach((c) => c.dispose()))

/** 渲染四张图表 */
function renderCharts() {
  const s = stats.value

  // 1. 近 7 日问答量趋势（折线）
  const trend = echarts.init(trendChart.value)
  trend.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: s.trend.map((t) => t.date) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      type: 'line', smooth: true, areaStyle: { opacity: 0.15 },
      data: s.trend.map((t) => t.count), itemStyle: { color: '#409eff' }
    }]
  })

  // 2. 命中率仪表盘
  const hit = echarts.init(hitChart.value)
  hit.setOption({
    series: [{
      type: 'gauge', startAngle: 200, endAngle: -20,
      progress: { show: true, width: 14 },
      axisLine: { lineStyle: { width: 14 } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      pointer: { show: false }, title: { show: false },
      detail: { fontSize: 28, formatter: '{value}%', offsetCenter: [0, 0] },
      data: [{ value: (s.quality.hit_rate * 100).toFixed(1) }]
    }]
  })

  // 3. Top 5 查询（横向柱状）
  const top = echarts.init(topChart.value)
  top.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: {
      type: 'category', inverse: true,
      data: s.top_queries.map((q) => q.query.slice(0, 12))
    },
    series: [{ type: 'bar', data: s.top_queries.map((q) => q.count), itemStyle: { color: '#67c23a' } }]
  })

  // 4. 反馈占比（饼图）
  const fb = echarts.init(feedbackChart.value)
  fb.setOption({
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie', radius: ['40%', '65%'],
      data: [
        { name: '点赞', value: s.feedback.like, itemStyle: { color: '#67c23a' } },
        { name: '点踩', value: s.feedback.dislike, itemStyle: { color: '#f56c6c' } }
      ]
    }]
  })

  charts = [trend, hit, top, fb]
}
</script>

<style scoped>
.page { padding: 24px; }
.cards { margin-bottom: 16px; }
.card-value { font-size: 28px; font-weight: 600; color: #303133; }
.card-label { color: #909399; margin-top: 4px; }
.charts { margin-bottom: 16px; }
.chart { height: 280px; }
</style>
