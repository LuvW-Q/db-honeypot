<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { TrendItem } from '../types'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

interface Props {
  items: TrendItem[]
  loading?: boolean
  days?: number
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  days: 14
})

const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const isEmpty = computed(() => !props.loading && props.items.length === 0)

function ensureObserver(): void {
  if (resizeObserver || !chartRef.value || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => {
    chart?.resize()
  })
  resizeObserver.observe(chartRef.value)
}

function render(): void {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  ensureObserver()
  if (isEmpty.value) {
    chart.clear()
    return
  }

  const days = props.days > 0 ? props.days : props.items.length
  const dates = props.items.map((item) => item.stat_date)

  chart.setOption(
    {
      color: ['#409eff', '#67c23a', '#e6a23c'],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'line' }
      },
      legend: {
        top: 0,
        right: 0,
        data: ['事件数', '查询数', '告警数']
      },
      grid: {
        left: 12,
        right: 16,
        top: 40,
        bottom: 8,
        containLabel: true
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: dates,
        axisLabel: { color: '#909399' },
        axisLine: { lineStyle: { color: '#dcdfe6' } }
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        name: `近 ${days} 天`,
        nameTextStyle: { color: '#909399' },
        axisLabel: { color: '#909399' },
        splitLine: { lineStyle: { color: '#ebeef5' } }
      },
      series: [
        {
          name: '事件数',
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: props.items.map((item) => item.event_count),
          areaStyle: { opacity: 0.12 }
        },
        {
          name: '查询数',
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: props.items.map((item) => item.query_count)
        },
        {
          name: '告警数',
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: props.items.map((item) => item.alert_count)
        }
      ]
    },
    true
  )
  chart.resize()
}

watch(
  () => props.items,
  async () => {
    await nextTick()
    render()
  },
  { deep: true }
)

watch(
  () => props.loading,
  async (loading) => {
    if (!loading) {
      await nextTick()
      render()
    }
  }
)

onMounted(async () => {
  await nextTick()
  render()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="trend-chart">
    <el-skeleton v-if="loading" class="trend-chart__skeleton" animated :rows="6" />
    <el-empty
      v-else-if="isEmpty"
      class="trend-chart__empty"
      description="暂无趋势数据"
      :image-size="80"
    />
    <div v-show="!loading && !isEmpty" ref="chartRef" class="trend-chart__canvas"></div>
  </div>
</template>

<style scoped>
.trend-chart {
  min-height: 320px;
}

.trend-chart__canvas {
  width: 100%;
  height: 320px;
}

.trend-chart__skeleton {
  padding: 8px;
}

.trend-chart__empty {
  padding: 48px 0;
}
</style>
