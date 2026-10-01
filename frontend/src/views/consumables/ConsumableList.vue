<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createConsumable,
  importConsumables,
  issueConsumable,
  listConsumables,
  updateConsumable,
  type ConsumablePayload,
} from '@/api/consumables'
import { usePagedList } from '@/composables/usePagedList'
import { useUserStore } from '@/store/user'
import type { Consumable, ImportSummary } from '@/types'

const store = useUserStore()

const filters = reactive<{ keyword: string; low_stock_only: boolean }>({
  keyword: '',
  low_stock_only: false,
})
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } =
  usePagedList<Consumable, typeof filters>(filters, listConsumables)

const dialogVisible = ref(false)
const issueVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const importSummary = ref<ImportSummary | null>(null)

const form = reactive<ConsumablePayload>({
  part_no: '',
  description: '',
  quantity: 0,
  safety_stock: 0,
  unit: '',
  remark: '',
})
const issueForm = reactive<{ consumable: Consumable | null; quantity: number; remark: string }>({
  consumable: null,
  quantity: 1,
  remark: '',
})

onMounted(load)

function openCreate(): void {
  editingId.value = null
  Object.assign(form, { part_no: '', description: '', quantity: 0, safety_stock: 0, unit: '', remark: '' })
  dialogVisible.value = true
}

function openEdit(row: Consumable): void {
  editingId.value = row.id
  Object.assign(form, {
    part_no: row.part_no,
    description: row.description,
    quantity: row.quantity,
    safety_stock: row.safety_stock,
    unit: row.unit,
    remark: row.remark,
  })
  dialogVisible.value = true
}

async function submit(): Promise<void> {
  if (!form.part_no || !form.description) {
    ElMessage.warning('部件号与中文描述必填')
    return
  }
  submitting.value = true
  try {
    if (editingId.value === null) {
      await createConsumable({ ...form })
      ElMessage.success('耗材已新增')
    } else {
      await updateConsumable(editingId.value, {
        description: form.description,
        safety_stock: form.safety_stock,
        unit: form.unit,
        remark: form.remark,
      })
      ElMessage.success('耗材已保存')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    console.warn('保存耗材失败', error)
  } finally {
    submitting.value = false
  }
}

function openIssue(row: Consumable): void {
  issueForm.consumable = row
  issueForm.quantity = 1
  issueForm.remark = ''
  issueVisible.value = true
}

async function submitIssue(): Promise<void> {
  if (!issueForm.consumable) {
    return
  }
  submitting.value = true
  try {
    await issueConsumable(issueForm.consumable.id, issueForm.quantity, issueForm.remark || null)
    ElMessage.success(`已领用 ${issueForm.quantity}${issueForm.consumable.unit ?? ''}，库存已扣减`)
    issueVisible.value = false
    await load()
  } catch (error) {
    console.warn('领用失败', error)
  } finally {
    submitting.value = false
  }
}

async function handleImport(file: File): Promise<boolean> {
  try {
    const summary = await importConsumables(file)
    importSummary.value = summary
    ElMessage.success(`导入完成：新增 ${summary.created}，更新 ${summary.updated}，失败 ${summary.failed}`)
    await load()
  } catch (error) {
    console.warn('导入失败', error)
  }
  return false // 阻止组件自身的上传行为，已用自定义请求提交
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">耗材管理</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="关键字">
        <el-input v-model="filters.keyword" placeholder="部件号或描述" clearable @keyup.enter="search" />
      </el-form-item>
      <el-form-item label="只看低库存">
        <el-switch v-model="filters.low_stock_only" @change="search" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="() => { filters.keyword = ''; filters.low_stock_only = false; search() }">重置</el-button>
        <el-button v-if="store.has('consumable.create')" type="success" @click="openCreate">新增耗材</el-button>
        <el-upload
          v-if="store.has('consumable.import')"
          class="import-upload"
          :show-file-list="false"
          accept=".xlsx"
          :before-upload="handleImport"
        >
          <el-button type="warning">导入 Excel</el-button>
        </el-upload>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="importSummary"
      class="import-result"
      type="info"
      show-icon
      :closable="true"
      @close="importSummary = null"
      :title="`上次导入：新增 ${importSummary.created}，更新 ${importSummary.updated}，失败 ${importSummary.failed}`"
    >
      <ul v-if="importSummary.errors.length" class="import-errors">
        <li v-for="(message, index) in importSummary.errors" :key="index">{{ message }}</li>
      </ul>
    </el-alert>

    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column prop="part_no" label="部件号" width="150">
        <template #default="{ row }">
          <span class="mono">{{ row.part_no }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="中文描述" min-width="180" show-overflow-tooltip />
      <el-table-column prop="quantity" label="库存" width="100" align="right">
        <template #default="{ row }">
          <el-tag v-if="row.quantity <= row.safety_stock" type="danger">{{ row.quantity }}</el-tag>
          <span v-else>{{ row.quantity }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="safety_stock" label="安全库存" width="100" align="right" />
      <el-table-column prop="unit" label="单位" width="80" align="center" />
      <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip />
      <el-table-column label="操作" width="150" fixed="right" align="center">
        <template #default="{ row }">
          <el-button v-if="store.has('consumable.issue')" link type="primary" @click="openIssue(row)">领用</el-button>
          <el-button v-if="store.has('consumable.create')" link type="primary" @click="openEdit(row)">编辑</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增耗材' : '编辑耗材'" width="620px">
      <el-form :model="form" label-width="96px">
        <el-form-item label="部件号" required>
          <el-input v-model="form.part_no" :disabled="editingId !== null" placeholder="唯一，重复会被拒绝" />
        </el-form-item>
        <el-form-item label="中文描述" required>
          <el-input v-model="form.description" />
        </el-form-item>
        <el-form-item label="库存数量">
          <el-input-number v-model="form.quantity" :min="0" :disabled="editingId !== null" />
          <span v-if="editingId !== null" class="field-hint">库存只能通过领用扣减，保证可追溯</span>
        </el-form-item>
        <el-form-item label="安全库存">
          <el-input-number v-model="form.safety_stock" :min="0" />
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="form.unit" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="issueVisible" title="领用耗材" width="520px">
      <el-descriptions v-if="issueForm.consumable" :column="2" border class="issue-info">
        <el-descriptions-item label="部件号">{{ issueForm.consumable.part_no }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ issueForm.consumable.description }}</el-descriptions-item>
        <el-descriptions-item label="当前库存">
          {{ issueForm.consumable.quantity }} {{ issueForm.consumable.unit ?? '' }}
        </el-descriptions-item>
        <el-descriptions-item label="安全库存">{{ issueForm.consumable.safety_stock }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="96px">
        <el-form-item label="领用数量" required>
          <el-input-number v-model="issueForm.quantity" :min="1" :max="issueForm.consumable?.quantity ?? 1" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="issueForm.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitIssue">确认领用</el-button>
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

.import-upload {
  display: inline-block;
  margin-left: 12px;
}

.import-result {
  margin-bottom: 12px;
}

.import-errors {
  margin: 6px 0 0;
  padding-left: 18px;
}

.issue-info {
  margin-bottom: 14px;
}

.field-hint {
  margin-left: 10px;
  color: var(--color-muted);
  font-size: 12px;
}
</style>
