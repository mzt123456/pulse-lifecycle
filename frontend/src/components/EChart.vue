<script setup lang="ts">
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps<{ option: EChartsOption; height?: string }>()

const element = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function resize(): void {
  chart?.resize()
}

onMounted(() => {
  if (!element.value) {
    return
  }
  chart = echarts.init(element.value)
  chart.setOption(props.option)
  // 监听容器尺寸：侧边导航收起、窗口缩放都要让图表跟着重排，1366 宽度下不挤压
  observer = new ResizeObserver(resize)
  observer.observe(element.value)
  window.addEventListener('resize', resize)
})

watch(
  () => props.option,
  (option) => chart?.setOption(option, true),
  { deep: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  observer?.disconnect()
  observer = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="element" :style="{ width: '100%', height: height ?? '300px' }" />
</template>
