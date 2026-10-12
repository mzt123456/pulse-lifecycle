<script setup>
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { getDictItems } from '@/api/dict';
import { createEquipment, deleteEquipment, listEquipment, updateEquipment, } from '@/api/equipment';
import { usePagedList } from '@/composables/usePagedList';
import DataTable from '@/components/DataTable.vue';
import { usePreferencesStore } from '@/store/preferences';
import { useUserStore } from '@/store/user';
const store = useUserStore();
const preferences = usePreferencesStore();
const columns = [
    { key: 'equipment_no', label: '脉冲编号', width: 150 },
    { key: 'model', label: '型号', minWidth: 140, tooltip: true },
    { key: 'status', label: '状态', width: 90, align: 'center' },
    { key: 'total_run_hours', label: '累计时长(h)', width: 110, align: 'right' },
    { key: 'total_run_count', label: '累计次数', width: 90, align: 'right' },
    { key: 'company', label: '关联公司', minWidth: 140, tooltip: true },
    { key: 'last_maintenance_at', label: '最近维保', width: 170 },
    { key: 'actions', label: '操作', width: 140, fixed: 'right', align: 'center' },
];
const EMPTY_FORM = {
    equipment_no: '',
    model: '',
    status: '待命',
    factory_date: null,
    temperature_grade: '',
    pressure_grade: '',
    valve_shell_size: '',
    company: '',
    contact_name: '',
    contact_phone: '',
    remark: '',
};
const filters = reactive({ keyword: '', status: '' });
const { items, total, loading, page, pageSize, load, search, changePage, changeSize } = usePagedList(filters, listEquipment);
function changePageSize(size) {
    void preferences.setPageSize(size);
    void changeSize(size);
}
const statusOptions = ref([]);
const dialogVisible = ref(false);
const submitting = ref(false);
const editingId = ref(null);
const editingVersion = ref(0);
const formRef = ref();
const form = reactive({ ...EMPTY_FORM });
const rules = {
    equipment_no: [{ required: true, message: '请输入脉冲编号', trigger: 'blur' }],
    status: [{ required: true, message: '请选择状态', trigger: 'change' }],
};
onMounted(async () => {
    await preferences.load();
    pageSize.value = preferences.pageSize;
    const dict = await getDictItems();
    statusOptions.value = dict['设备状态'] ?? [];
    await load();
});
function openCreate() {
    editingId.value = null;
    editingVersion.value = 0;
    Object.assign(form, EMPTY_FORM);
    dialogVisible.value = true;
}
function openEdit(row) {
    editingId.value = row.id;
    editingVersion.value = row.version;
    Object.assign(form, {
        equipment_no: row.equipment_no,
        model: row.model,
        status: row.status,
        factory_date: row.factory_date,
        temperature_grade: row.temperature_grade,
        pressure_grade: row.pressure_grade,
        valve_shell_size: row.valve_shell_size,
        company: row.company,
        contact_name: row.contact_name,
        contact_phone: row.contact_phone,
        remark: row.remark,
    });
    dialogVisible.value = true;
}
async function submit() {
    if (!formRef.value) {
        return;
    }
    const valid = await formRef.value.validate().catch(() => false);
    if (!valid) {
        return;
    }
    submitting.value = true;
    try {
        if (editingId.value === null) {
            await createEquipment({ ...form });
            ElMessage.success('设备已新增');
        }
        else {
            await updateEquipment(editingId.value, { ...form, version: editingVersion.value });
            ElMessage.success('设备已保存');
        }
        dialogVisible.value = false;
        await load();
    }
    catch (error) {
        console.warn('保存设备失败', error);
    }
    finally {
        submitting.value = false;
    }
}
async function remove(row) {
    try {
        await ElMessageBox.confirm(`确定删除设备 ${row.equipment_no} 吗？`, '删除确认', { type: 'warning' });
    }
    catch {
        return;
    }
    try {
        await deleteEquipment(row.id);
        ElMessage.success('已删除');
        await load();
    }
    catch (error) {
        console.warn('删除设备失败', error);
    }
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">设备台账</h2>

    <el-form :inline="true" class="filter-bar">
      <el-form-item label="关键字">
        <el-input v-model="filters.keyword" placeholder="脉冲编号或型号" clearable @keyup.enter="search" />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="filters.status" placeholder="全部" clearable style="width: 140px">
          <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="() => { filters.keyword = ''; filters.status = ''; search() }">重置</el-button>
      </el-form-item>
    </el-form>

    <DataTable table-key="equipment" :columns="columns" :data="items" :loading="loading">
      <template #toolbar>
        <el-button v-if="store.has('equipment.create')" type="success" @click="openCreate">新增设备</el-button>
      </template>
      <template #cell-equipment_no="{ row }">
        <span class="mono">{{ row.equipment_no }}</span>
      </template>
      <template #cell-status="{ row }">
        <el-tag :type="row.status === '在用' ? 'success' : row.status === '维保' ? 'warning' : 'info'">
          {{ row.status }}
        </el-tag>
      </template>
      <template #cell-actions="{ row }">
        <el-button v-if="store.has('equipment.update')" link type="primary" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="store.has('equipment.delete')" link type="danger" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增设备' : '编辑设备'" width="720px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="脉冲编号" prop="equipment_no">
              <el-input v-model="form.equipment_no" placeholder="唯一，重复会被拒绝" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="型号">
              <el-input v-model="form.model" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态" prop="status">
              <el-select v-model="form.status" style="width: 100%">
                <el-option v-for="item in statusOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="出厂日期">
              <el-date-picker v-model="form.factory_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="温度等级">
              <el-input v-model="form.temperature_grade" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="抗压等级">
              <el-input v-model="form.pressure_grade" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="阀壳尺寸">
              <el-input v-model="form.valve_shell_size" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="关联公司">
              <el-input v-model="form.company" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系人">
              <el-input v-model="form.contact_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系电话">
              <el-input v-model="form.contact_phone" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" />
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
