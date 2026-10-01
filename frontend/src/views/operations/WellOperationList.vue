<script setup lang="ts">
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { getDictItems } from '@/api/dict'
import { downloadExcel } from '@/api/export'
import { listEquipment } from '@/api/equipment'
import {
  createOperation,
  deleteOperation,
  listOperations,
  updateOperation,
  type OperationPayload,
} from '@/api/operations'
import { usePagedList } from '@/composables/usePagedList'
import DataTable from '@/components/DataTable.vue'
import { usePreferencesStore } from '@/store/preferences'
import { useUserStore } from '@/store/user'
import { compactParams } from '@/utils/params'
import type { Equipment, TableColumn, WellOperation } from '@/types'

const store = useUserStore()
const preferences = usePreferencesStore()

const columns: TableColumn[] = [
  { key: 'equipment_no', label: '设备', width: 130 },
  { key: 'well_no', label: '井号', width: 120, tooltip: true },
  { key: 'start_date', label: '入井时间', width: 170 },
  { key: 'end_date', label: '出井时间', width: 170 },
  { key: 'run_hours', label: '时长(h)', width: 90, align: 'right' },
  { key: 'footage', label: '进尺(m)', width: 100, align: 'right' },
  { key: 'well_depth', label: '井深(m)', width: 100, align: 'right' },
  { key: 'mud_density', label: '泥浆密度', width: 100, align: 'right' },
  { key: 'instrument_type', label: '仪器类型', width: 110 },
  { key: 'operator_name', label: '作业人员', width: 110, tooltip: true },
  { key: 'bit_size', label: '井眼尺寸', width: 100, defaultHidden: true },
  { key: 'mud_type', label: '泥浆类型', width: 110, defaultHidden: true },
  { key: 'flow_rate', label: '排量', width: 100, defaultHidden: true },
  { key: 'temperature', label: '井下温度', width: 110, defaultHidden: true },
  { key: 'run_in_depth', label: '入井井深', width: 110, defaultHidden: true },
  { key: 'run_out_depth', label: '出井井深', width: 110, defaultHidden: true },
  { key: 'instrument_config', label: '仪器配置', width: 140, defaultHidden: true },
  { key: 'remark', label: '备注', minWidth: 160, tooltip: true, defaultHidden: true },
  { key: 'actions', label: '操作', width: 140, fixed: 'right', align: 'center' },
]

const EMPTY_FORM: OperationPayload = {
  equipment_id: undefined,
  well_no: '',
  well_depth: '',
  bit_size: '',
  mud_type: '',
  mud_density: '',
  flow_rate: '',
  start_date: null,
  end_date: null,
  run_hours: null,
  run_in_depth: '',
  run_out_depth: '',
  footage: null,
  temperature: '',
  instrument_type: '',
  instrument_config: '',
  operator_name: '',
  remark: '',
}

const filters = reactive<{ equipment_id?: number; well_no: string }>({ equipment_id: undefined, well_no: '' })
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } =
  usePagedList<WellOperation, typeof filters>(filters, listOperations)

function changePageSize(size: number): void {
  void preferences.setPageSize(size)
  void changeSize(size)
}

const equipmentOptions = ref<Equipment[]>([])
const instrumentTypes = ref<string[]>([])
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const form = reactive<OperationPayload>({ ...EMPTY_FORM })
const computedHint = ref('')

onMounted(async () => {
  await preferences.load()
  pageSize.value = preferences.pageSize
  const [dict, equipmentPage] = await Promise.all([
    getDictItems(),
    listEquipment({ page: 1, page_size: 100 }),
  ])
  instrumentTypes.value = dict['仪器类型'] ?? []
  equipmentOptions.value = equipmentPage.items
  await load()
})

function openCreate(): void {
  editingId.value = null
  Object.assign(form, EMPTY_FORM)
  computedHint.value = ''
  dialogVisible.value = true
}

function openEdit(row: WellOperation): void {
  editingId.value = row.id
  Object.assign(form, {
    equipment_id: row.equipment_id,
    well_no: row.well_no,
    well_depth: row.well_depth,
    bit_size: row.bit_size,
    mud_type: row.mud_type,
    mud_density: row.mud_density,
    flow_rate: row.flow_rate,
    start_date: row.start_date,
    end_date: row.end_date,
    run_hours: row.run_hours,
    run_in_depth: row.run_in_depth,
    run_out_depth: row.run_out_depth,
    footage: row.footage,
    temperature: row.temperature,
    instrument_type: row.instrument_type,
    instrument_config: row.instrument_config,
    operator_name: row.operator_name,
    remark: row.remark,
  })
  computedHint.value = ''
  dialogVisible.value = true
}

async function submit(): Promise<void> {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  submitting.value = true
  try {
    if (editingId.value === null) {
      const saved = await createOperation({ ...form })
      computedHint.value = `已保存：使用时长 ${saved.run_hours ?? '-'} 小时，进尺 ${saved.footage ?? '-'}`
      ElMessage.success('使用记录已新增，设备累计值已同步')
    } else {
      const saved = await updateOperation(editingId.value, { ...form })
      computedHint.value = `已保存：使用时长 ${saved.run_hours ?? '-'} 小时，进尺 ${saved.footage ?? '-'}`
      ElMessage.success('使用记录已保存，设备累计值已按差额调整')
    }
    await load()
  } catch (error) {
    console.warn('保存使用记录失败', error)
  } finally {
    submitting.value = false
  }
}

async function remove(row: WellOperation): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除 ${row.equipment_no ?? ''} 的这条使用记录吗？设备累计值会同步回退。`,
      '删除确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteOperation(row.id)
    ElMessage.success('已删除，设备累计值已回退')
    await load()
  } catch (error) {
    console.warn('删除使用记录失败', error)
  }
}

async function exportExcel(): Promise<void> {
  try {
    await downloadExcel(
      '/well-operations/export',
      compactParams({ equipment_id: filters.equipment_id, well_no: filters.well_no }),
      '使用记录.xlsx',
    )
    ElMessage.success('导出已开始，请查看浏览器下载')
  } catch (error) {
    console.warn('导出失败', error)
  }
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">使用记录</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="设备">
        <el-select
          v-model="filters.equipment_id"
          placeholder="全部"
          clearable
          filterable
          style="width: 200px"
        >
          <el-option
            v-for="item in equipmentOptions"
            :key="item.id"
            :label="item.equipment_no"
            :value="item.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="井号">
        <el-input v-model="filters.well_no" placeholder="井号" clearable @keyup.enter="search" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="() => { filters.equipment_id = undefined; filters.well_no = ''; search() }">重置</el-button>
      </el-form-item>
    </el-form>

    <DataTable table-key="well_operation" :columns="columns" :data="items" :loading="loading">
      <template #toolbar>
        <el-button v-if="store.has('well_operation.create')" type="success" @click="openCreate">新增记录</el-button>
        <el-button v-if="store.has('well_operation.export')" @click="exportExcel">导出 Excel</el-button>
      </template>
      <template #cell-equipment_no="{ row }">
        <span class="mono">{{ row.equipment_no }}</span>
      </template>
      <template #cell-actions="{ row }">
        <el-button v-if="store.has('well_operation.update')" link type="primary" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="store.has('well_operation.delete')" link type="danger" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增使用记录' : '编辑使用记录'" width="820px">
      <el-alert
        class="dialog-hint"
        type="info"
        :closable="false"
        title="使用时长按出入井时间自动计算，进尺按出入井井深自动计算；手工填写的值优先。保存时设备累计值同步更新。"
      />
      <el-form ref="formRef" :model="form" label-width="96px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item
              label="关联设备"
              prop="equipment_id"
              :rules="[{ required: true, message: '请选择设备', trigger: 'change' }]"
            >
              <el-select
                v-model="form.equipment_id"
                :disabled="editingId !== null"
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="item in equipmentOptions"
                  :key="item.id"
                  :label="`${item.equipment_no}${item.model ? ' / ' + item.model : ''}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="井号">
              <el-input v-model="form.well_no" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="入井时间">
              <el-date-picker
                v-model="form.start_date"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="出井时间">
              <el-date-picker
                v-model="form.end_date"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手动时长(h)">
              <el-input v-model="form.run_hours" placeholder="留空自动计算" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="手动进尺(m)">
              <el-input v-model="form.footage" placeholder="留空自动计算" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="井深(m)">
              <el-input v-model="form.well_depth" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="井眼尺寸">
              <el-input v-model="form.bit_size" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="入井井深">
              <el-input v-model="form.run_in_depth" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="出井井深">
              <el-input v-model="form.run_out_depth" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="泥浆类型">
              <el-input v-model="form.mud_type" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="泥浆密度">
              <el-input v-model="form.mud_density" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="排量">
              <el-input v-model="form.flow_rate" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="井下温度">
              <el-input v-model="form.temperature" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="仪器类型">
              <el-select v-model="form.instrument_type" clearable style="width: 100%">
                <el-option v-for="item in instrumentTypes" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="仪器配置">
              <el-input v-model="form.instrument_config" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="作业人员">
              <el-input v-model="form.operator_name" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <p v-if="computedHint" class="computed-hint">{{ computedHint }}</p>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
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

.dialog-hint {
  margin-bottom: 12px;
}

.computed-hint {
  margin: 0;
  color: var(--color-accent);
  font-size: 13px;
}
</style>
