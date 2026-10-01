<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { getDictItems } from '@/api/dict'
import { downloadExcel } from '@/api/export'
import { listEquipment } from '@/api/equipment'
import {
  completeStep,
  createMaintenanceOrder,
  getMaintenanceOrder,
  listMaintenanceOrders,
  updateMaintenanceOrder,
  type MaintenancePayload,
} from '@/api/maintenance'
import { usePagedList } from '@/composables/usePagedList'
import AttachmentPanel from '@/components/AttachmentPanel.vue'
import DataTable from '@/components/DataTable.vue'
import { usePreferencesStore } from '@/store/preferences'
import { useUserStore } from '@/store/user'
import { compactParams } from '@/utils/params'
import type { Equipment, MaintenanceOrder, MaintenanceStep, TableColumn } from '@/types'

const store = useUserStore()
const preferences = usePreferencesStore()
const STATUSES = ['进行中', '已完成']

const columns: TableColumn[] = [
  { key: 'order_no', label: '工单号', width: 170 },
  { key: 'equipment_no', label: '设备', width: 130 },
  { key: 'level', label: '等级', width: 110 },
  { key: 'start_date', label: '开始日期', width: 120 },
  { key: 'end_date', label: '结束日期', width: 120 },
  { key: 'status', label: '状态', width: 100, align: 'center' },
  { key: 'result', label: '结果', width: 100 },
  { key: 'oil_level', label: '油位(mm)', width: 110, align: 'right' },
  { key: 'suggestion', label: '维保建议', minWidth: 180, tooltip: true },
  { key: 'actions', label: '操作', width: 110, fixed: 'right', align: 'center' },
]

const filters = reactive<{ equipment_id?: number; level: string; status: string }>({
  equipment_id: undefined,
  level: '',
  status: '',
})
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } =
  usePagedList<MaintenanceOrder, typeof filters>(filters, listMaintenanceOrders)

function changePageSize(size: number): void {
  void preferences.setPageSize(size)
  void changeSize(size)
}

const equipmentOptions = ref<Equipment[]>([])
const levelOptions = ref<string[]>([])
const createVisible = ref(false)
const detailVisible = ref(false)
const submitting = ref(false)
const detail = ref<MaintenanceOrder | null>(null)

const createForm = reactive<{
  equipment_id?: number
  level: string
  start_date: string | null
  oil_level: string
  suggestion: string
}>({ equipment_id: undefined, level: '', start_date: null, oil_level: '', suggestion: '' })

const editForm = reactive<{
  level: string
  result: string
  oil_level: string
  suggestion: string
  status: string
  end_date: string | null
}>({ level: '', result: '', oil_level: '', suggestion: '', status: '进行中', end_date: null })

const doneCount = computed(() => detail.value?.steps?.filter((step) => step.is_done).length ?? 0)
const stepCount = computed(() => detail.value?.steps?.length ?? 0)

onMounted(async () => {
  await preferences.load()
  pageSize.value = preferences.pageSize
  const [dict, equipmentPage] = await Promise.all([
    getDictItems(),
    listEquipment({ page: 1, page_size: 100 }),
  ])
  levelOptions.value = dict['维保等级'] ?? []
  createForm.level = levelOptions.value[0] ?? ''
  equipmentOptions.value = equipmentPage.items
  await load()
})

function openCreate(): void {
  Object.assign(createForm, {
    equipment_id: undefined,
    level: levelOptions.value[0] ?? '',
    start_date: null,
    oil_level: '',
    suggestion: '',
  })
  createVisible.value = true
}

async function submitCreate(): Promise<void> {
  if (!createForm.equipment_id || !createForm.level) {
    ElMessage.warning('请选择设备与维保等级')
    return
  }
  submitting.value = true
  try {
    const order = await createMaintenanceOrder({
      equipment_id: createForm.equipment_id,
      level: createForm.level,
      start_date: createForm.start_date,
      oil_level: createForm.oil_level || null,
      suggestion: createForm.suggestion || null,
    })
    ElMessage.success(`工单 ${order.order_no} 已创建，步骤清单 ${order.steps?.length ?? 0} 条`)
    createVisible.value = false
    await openDetail(order.id)
    await load()
  } catch (error) {
    console.warn('创建工单失败', error)
  } finally {
    submitting.value = false
  }
}

function syncEditForm(): void {
  if (!detail.value) {
    return
  }
  Object.assign(editForm, {
    level: detail.value.level,
    result: detail.value.result ?? '',
    oil_level: detail.value.oil_level ?? '',
    suggestion: detail.value.suggestion ?? '',
    status: detail.value.status,
    end_date: detail.value.end_date,
  })
}

async function openDetail(orderId: number): Promise<void> {
  detail.value = await getMaintenanceOrder(orderId)
  syncEditForm()
  detailVisible.value = true
}

async function toggleStep(step: MaintenanceStep, value: boolean): Promise<void> {
  if (!detail.value) {
    return
  }
  try {
    await completeStep(detail.value.id, step.id, value)
    detail.value = await getMaintenanceOrder(detail.value.id)
    await load()
  } catch (error) {
    console.warn('更新步骤失败', error)
  }
}

async function saveDetail(): Promise<void> {
  if (!detail.value) {
    return
  }
  const payload: MaintenancePayload = {
    result: editForm.result || null,
    oil_level: editForm.oil_level || null,
    suggestion: editForm.suggestion || null,
    status: editForm.status,
    end_date: editForm.end_date,
  }
  if (editForm.level !== detail.value.level) {
    try {
      await ElMessageBox.confirm(
        `改为「${editForm.level}」会按新等级重建步骤清单，已勾选的步骤记录会清空。确定继续吗？`,
        '等级变更',
        { type: 'warning' },
      )
    } catch {
      editForm.level = detail.value.level
      return
    }
    payload.level = editForm.level
  }

  submitting.value = true
  try {
    detail.value = await updateMaintenanceOrder(detail.value.id, payload)
    syncEditForm()
    ElMessage.success('工单已保存')
    await load()
  } catch (error) {
    console.warn('保存工单失败', error)
  } finally {
    submitting.value = false
  }
}

async function exportExcel(): Promise<void> {
  try {
    await downloadExcel(
      '/maintenance-orders/export',
      compactParams({
        equipment_id: filters.equipment_id,
        level: filters.level,
        status: filters.status,
      }),
      '维保工单.xlsx',
    )
    ElMessage.success('导出已开始，请查看浏览器下载')
  } catch (error) {
    console.warn('导出失败', error)
  }
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">维保工单</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="设备">
        <el-select v-model="filters.equipment_id" placeholder="全部" clearable filterable style="width: 190px">
          <el-option v-for="item in equipmentOptions" :key="item.id" :label="item.equipment_no" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="等级">
        <el-select v-model="filters.level" placeholder="全部" clearable style="width: 130px">
          <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="filters.status" placeholder="全部" clearable style="width: 120px">
          <el-option v-for="item in STATUSES" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="() => { filters.equipment_id = undefined; filters.level = ''; filters.status = ''; search() }">重置</el-button>
      </el-form-item>
    </el-form>

    <DataTable table-key="maintenance_order" :columns="columns" :data="items" :loading="loading">
      <template #toolbar>
        <el-button v-if="store.has('maintenance.create')" type="success" @click="openCreate">创建工单</el-button>
        <el-button v-if="store.has('maintenance.export')" @click="exportExcel">导出 Excel</el-button>
      </template>
      <template #cell-order_no="{ row }">
        <span class="mono">{{ row.order_no }}</span>
      </template>
      <template #cell-status="{ row }">
        <el-tag :type="row.status === '已完成' ? 'success' : 'warning'">{{ row.status }}</el-tag>
      </template>
      <template #cell-actions="{ row }">
        <el-button link type="primary" @click="openDetail(row.id)">
          {{ store.has('maintenance.update') ? '详情 / 编辑' : '详情' }}
        </el-button>
      </template>
    </DataTable>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="changePage"
      @size-change="changePageSize"
    />

    <el-dialog v-model="createVisible" title="创建维保工单" width="620px">
      <el-form :model="createForm" label-width="96px">
        <el-form-item label="关联设备" required>
          <el-select v-model="createForm.equipment_id" filterable style="width: 100%">
            <el-option
              v-for="item in equipmentOptions"
              :key="item.id"
              :label="`${item.equipment_no}${item.model ? ' / ' + item.model : ''}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="维保等级" required>
          <el-select v-model="createForm.level" style="width: 100%">
            <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker v-model="createForm.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="油位(mm)">
          <el-input v-model="createForm.oil_level" />
        </el-form-item>
        <el-form-item label="维保建议">
          <el-input v-model="createForm.suggestion" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        title="创建后系统会按维保等级自动生成步骤清单，可在详情里逐项勾选。"
      />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="`工单 ${detail?.order_no ?? ''}`" width="880px">
      <template v-if="detail">
        <el-descriptions :column="3" border class="order-info">
          <el-descriptions-item label="设备">{{ detail.equipment_no ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="等级">{{ detail.level }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="开始日期">{{ detail.start_date ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="结束日期">{{ detail.end_date ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="步骤进度">{{ doneCount }} / {{ stepCount }}</el-descriptions-item>
        </el-descriptions>

        <el-form :model="editForm" label-width="96px" class="detail-form" :disabled="!store.has('maintenance.update')">
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="维保等级">
                <el-select v-model="editForm.level" style="width: 100%">
                  <el-option v-for="item in levelOptions" :key="item" :label="item" :value="item" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="维保结果">
                <el-input v-model="editForm.result" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="油位(mm)">
                <el-input v-model="editForm.oil_level" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="结束日期">
                <el-date-picker v-model="editForm.end_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="状态">
                <el-select v-model="editForm.status" style="width: 100%">
                  <el-option v-for="item in STATUSES" :key="item" :label="item" :value="item" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="维保建议">
                <el-input v-model="editForm.suggestion" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <h3 class="steps-title">步骤清单</h3>
        <el-table :data="detail.steps ?? []" border size="small">
          <el-table-column label="完成" width="70" align="center">
            <template #default="{ row }">
              <el-checkbox
                :model-value="row.is_done"
                :disabled="!store.has('maintenance.update')"
                @change="(value: boolean) => toggleStep(row, value)"
              />
            </template>
          </el-table-column>
          <el-table-column prop="seq" label="序号" width="70" align="center" />
          <el-table-column prop="name" label="步骤内容" min-width="260" />
          <el-table-column prop="done_by_name" label="完成人" width="110" />
          <el-table-column prop="done_at" label="完成时间" width="170" />
        </el-table>

        <AttachmentPanel object-type="maintenance_order" :object-id="detail.id" />
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="store.has('maintenance.update')"
          type="primary"
          :loading="submitting"
          @click="saveDetail"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.filter-bar {
  margin-bottom: 4px;
}

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.order-info {
  margin-bottom: 14px;
}

.detail-form {
  margin-bottom: 6px;
}

.steps-title {
  margin: 6px 0 10px;
  font-size: 15px;
  font-weight: 600;
}
</style>
