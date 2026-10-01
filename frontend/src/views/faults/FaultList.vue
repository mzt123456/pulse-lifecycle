<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { getDictItems } from '@/api/dict'
import { downloadExcel } from '@/api/export'
import { listEquipment } from '@/api/equipment'
import { createFault, listFaults, updateFault, type FaultPayload } from '@/api/faults'
import { usePagedList } from '@/composables/usePagedList'
import { useUserStore } from '@/store/user'
import { compactParams } from '@/utils/params'
import type { Equipment, FaultRecord } from '@/types'

const store = useUserStore()

const filters = reactive<{ equipment_id?: number; fault_type: string; status: string }>({
  equipment_id: undefined,
  fault_type: '',
  status: '',
})
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } =
  usePagedList<FaultRecord, typeof filters>(filters, listFaults)

const equipmentOptions = ref<Equipment[]>([])
const typeOptions = ref<string[]>([])
const statusOptions = ref<string[]>([])
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)

const form = reactive<FaultPayload>({
  equipment_id: undefined,
  occurred_at: null,
  position: '',
  fault_type: '',
  description: '',
  cause: '',
  solution: '',
  status: '待处理',
})

onMounted(async () => {
  const [dict, equipmentPage] = await Promise.all([
    getDictItems(),
    listEquipment({ page: 1, page_size: 100 }),
  ])
  typeOptions.value = dict['故障类型'] ?? []
  statusOptions.value = dict['故障处理状态'] ?? []
  equipmentOptions.value = equipmentPage.items
  await load()
})

function openCreate(): void {
  editingId.value = null
  Object.assign(form, {
    equipment_id: undefined,
    occurred_at: null,
    position: '',
    fault_type: '',
    description: '',
    cause: '',
    solution: '',
    status: statusOptions.value[0] ?? '待处理',
  })
  dialogVisible.value = true
}

function openEdit(row: FaultRecord): void {
  editingId.value = row.id
  Object.assign(form, {
    equipment_id: row.equipment_id,
    occurred_at: row.occurred_at,
    position: row.position,
    fault_type: row.fault_type,
    description: row.description,
    cause: row.cause,
    solution: row.solution,
    status: row.status,
  })
  dialogVisible.value = true
}

async function submit(): Promise<void> {
  if (!form.equipment_id) {
    ElMessage.warning('请选择关联设备')
    return
  }
  submitting.value = true
  try {
    if (editingId.value === null) {
      await createFault({ ...form })
      ElMessage.success('故障记录已新增')
    } else {
      await updateFault(editingId.value, { ...form })
      ElMessage.success('故障记录已保存')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    console.warn('保存故障记录失败', error)
  } finally {
    submitting.value = false
  }
}

async function exportExcel(): Promise<void> {
  try {
    await downloadExcel(
      '/fault-records/export',
      compactParams({
        equipment_id: filters.equipment_id,
        fault_type: filters.fault_type,
        status: filters.status,
      }),
      '故障记录.xlsx',
    )
    ElMessage.success('导出已开始，请查看浏览器下载')
  } catch (error) {
    console.warn('导出失败', error)
  }
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">故障记录</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="设备">
        <el-select v-model="filters.equipment_id" placeholder="全部" clearable filterable style="width: 190px">
          <el-option v-for="item in equipmentOptions" :key="item.id" :label="item.equipment_no" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="故障类型">
        <el-select v-model="filters.fault_type" placeholder="全部" clearable style="width: 140px">
          <el-option v-for="item in typeOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="处理状态">
        <el-select v-model="filters.status" placeholder="全部" clearable style="width: 130px">
          <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="() => { filters.equipment_id = undefined; filters.fault_type = ''; filters.status = ''; search() }">重置</el-button>
        <el-button v-if="store.has('fault.create')" type="success" @click="openCreate">新增故障</el-button>
        <el-button v-if="store.has('report.export')" @click="exportExcel">导出 Excel</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column prop="equipment_no" label="设备" width="130" />
      <el-table-column prop="occurred_at" label="发生时间" width="170" />
      <el-table-column prop="position" label="故障位置" width="120" show-overflow-tooltip />
      <el-table-column prop="fault_type" label="故障类型" width="120" />
      <el-table-column prop="description" label="现象描述" min-width="180" show-overflow-tooltip />
      <el-table-column prop="cause" label="原因分析" min-width="160" show-overflow-tooltip />
      <el-table-column prop="solution" label="解决方案" min-width="160" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === '已解决' ? 'success' : row.status === '处理中' ? 'warning' : 'danger'">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right" align="center">
        <template #default="{ row }">
          <el-button v-if="store.has('fault.update')" link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      @current-change="changePage"
      @size-change="changeSize"
    />

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增故障记录' : '编辑故障记录'" width="700px">
      <el-form :model="form" label-width="96px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="关联设备" required>
              <el-select v-model="form.equipment_id" :disabled="editingId !== null" filterable style="width: 100%">
                <el-option
                  v-for="item in equipmentOptions"
                  :key="item.id"
                  :label="item.equipment_no"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="发生时间">
              <el-date-picker
                v-model="form.occurred_at"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="故障位置">
              <el-input v-model="form.position" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="故障类型">
              <el-select v-model="form.fault_type" clearable style="width: 100%">
                <el-option v-for="item in typeOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="现象描述">
              <el-input v-model="form.description" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="原因分析">
              <el-input v-model="form.cause" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="解决方案">
              <el-input v-model="form.solution" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="处理状态">
              <el-select v-model="form.status" style="width: 100%">
                <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
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
</style>
