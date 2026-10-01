<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'

import {
  getDashboard,
  getFaultStatistics,
  getOperationTrend,
  getUtilization,
  type DashboardData,
  type FaultStatisticsData,
  type OperationTrendData,
  type UtilizationData,
} from '@/api/report'
import EChart from '@/components/EChart.vue'

const loading = ref(false)
const dashboard = ref<DashboardData | null>(null)
const utilization = ref<UtilizationData | null>(null)
const faults = ref<FaultStatisticsData | null>(null)
const trend = ref<OperationTrendData | null>(null)

const statusOption = computed<EChartsOption>(() => ({
  title: { text: '设备状态分布', left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'item' },
  legend: { bottom: 0 },
  series: [
    {
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '48%'],
      data: Object.entries(dashboard.value?.status_counts ?? {}).map(([name, value]) => ({
        name,
        value,
      })),
      label: { formatter: '{b}: {c}' },
    },
  ],
}))

const faultTypeOption = computed<EChartsOption>(() => ({
  title: { text: '故障按类型分布', left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 20, top: 50, bottom: 30 },
  xAxis: { type: 'category', data: (faults.value?.by_type ?? []).map((item) => item.fault_type) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      type: 'bar',
      data: (faults.value?.by_type ?? []).map((item) => item.count),
      itemStyle: { color: '#E67E22' },
      barMaxWidth: 40,
    },
  ],
}))

const faultMonthOption = computed<EChartsOption>(() => ({
  title: { text: '故障按月份趋势', left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 20, top: 50, bottom: 30 },
  xAxis: { type: 'category', data: (faults.value?.by_month ?? []).map((item) => item.month) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      type: 'line',
      smooth: true,
      data: (faults.value?.by_month ?? []).map((item) => item.count),
      itemStyle: { color: '#E74C3C' },
    },
  ],
}))

const trendOption = computed<EChartsOption>(() => ({
  title: { text: '使用趋势（按月）', left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0 },
  grid: { left: 45, right: 45, top: 50, bottom: 50 },
  xAxis: { type: 'category', data: (trend.value?.by_month ?? []).map((item) => item.month) },
  yAxis: [
    { type: 'value', name: '时长(h)' },
    { type: 'value', name: '次数', minInterval: 1 },
  ],
  series: [
    {
      name: '使用时长',
      type: 'line',
      smooth: true,
      data: (trend.value?.by_month ?? []).map((item) => Number(item.hours)),
      itemStyle: { color: '#2980B9' },
    },
    {
      name: '使用次数',
      type: 'line',
      smooth: true,
      yAxisIndex: 1,
      data: (trend.value?.by_month ?? []).map((item) => item.count),
      itemStyle: { color: '#27AE60' },
    },
  ],
}))

const instrumentOption = computed<EChartsOption>(() => ({
  title: { text: '各仪器类型累计使用时长', left: 'center', textStyle: { fontSize: 14 } },
  tooltip: { trigger: 'axis' },
  grid: { left: 45, right: 20, top: 50, bottom: 30 },
  xAxis: {
    type: 'category',
    data: (trend.value?.by_instrument ?? []).map((item) => item.instrument_type),
  },
  yAxis: { type: 'value', name: '小时' },
  series: [
    {
      type: 'bar',
      data: (trend.value?.by_instrument ?? []).map((item) => Number(item.hours)),
      itemStyle: { color: '#2980B9' },
      barMaxWidth: 40,
    },
  ],
}))

async function load(): Promise<void> {
  loading.value = true
  try {
    const [dash, use, fault, trendData] = await Promise.all([
      getDashboard(),
      getUtilization({}),
      getFaultStatistics({}),
      getOperationTrend(6),
    ])
    dashboard.value = dash
    utilization.value = use
    faults.value = fault
    trend.value = trendData
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-label">设备总数</div>
        <div class="stat-value">{{ dashboard?.equipment_total ?? 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">待维保设备</div>
        <div class="stat-value warning">{{ dashboard?.maintenance_due ?? 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">未解决故障</div>
        <div class="stat-value danger">{{ dashboard?.open_faults ?? 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">低库存耗材</div>
        <div class="stat-value warning">{{ dashboard?.low_stock_consumables ?? 0 }}</div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="page-card chart-card">
        <EChart :option="statusOption" />
      </div>
      <div class="page-card chart-card">
        <EChart :option="faultTypeOption" />
      </div>
      <div class="page-card chart-card">
        <EChart :option="trendOption" />
      </div>
      <div class="page-card chart-card">
        <EChart :option="faultMonthOption" />
      </div>
      <div class="page-card chart-card wide">
        <EChart :option="instrumentOption" />
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">设备利用率</h2>
      <p class="formula">
        统计区间 {{ utilization?.start }} 至 {{ utilization?.end }}，区间总时长
        {{ utilization?.total_hours }} 小时；{{ utilization?.formula }}（口径如需调整请告知，我们同步改文档与页面）
      </p>
      <el-table :data="utilization?.items ?? []" border stripe size="small">
        <el-table-column prop="equipment_no" label="设备编号" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.equipment_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="型号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="90" align="center" />
        <el-table-column prop="operation_count" label="使用次数" width="100" align="right" />
        <el-table-column prop="run_hours" label="使用时长(h)" width="120" align="right" />
        <el-table-column prop="utilization_rate" label="利用率(%)" width="110" align="right" />
      </el-table>
    </div>

    <div class="page-card">
      <h2 class="page-title">最近维保与使用</h2>
      <el-row :gutter="12">
        <el-col :span="12">
          <h3 class="sub-title">最近维保工单</h3>
          <el-table :data="dashboard?.recent_maintenance ?? []" size="small" border>
            <el-table-column prop="order_no" label="工单号" width="160" />
            <el-table-column prop="equipment_no" label="设备" width="120" />
            <el-table-column prop="level" label="等级" width="100" />
            <el-table-column prop="status" label="状态" width="90" align="center" />
            <el-table-column prop="start_date" label="开始日期" />
          </el-table>
        </el-col>
        <el-col :span="12">
          <h3 class="sub-title">最近使用记录</h3>
          <el-table :data="dashboard?.recent_operations ?? []" size="small" border>
            <el-table-column prop="equipment_no" label="设备" width="120" />
            <el-table-column prop="well_no" label="井号" width="120" />
            <el-table-column prop="run_hours" label="时长(h)" width="90" align="right" />
            <el-table-column prop="start_date" label="入井时间" />
          </el-table>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<style scoped>
.stat-cards {
  display: flex;
  gap: 14px;
  margin-bottom: 14px;
}

.stat-card {
  flex: 1;
  padding: 16px 18px;
  background: var(--color-surface);
  border: 1px solid #d9d9d9;
  border-radius: 4px;
}

.stat-label {
  font-size: 13px;
  color: #7f8c8d;
}

.stat-value {
  margin-top: 6px;
  font-size: 26px;
  font-weight: 600;
  color: var(--color-accent);
}

.stat-value.warning {
  color: var(--color-warning);
}

.stat-value.danger {
  color: var(--color-danger);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.chart-card.wide {
  grid-column: span 2;
}

.formula {
  margin: 0 0 12px;
  font-size: 13px;
  color: #7f8c8d;
}

.sub-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.page-card + .page-card {
  margin-top: 14px;
}
</style>
