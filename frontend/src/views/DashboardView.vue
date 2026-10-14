<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getDashboard } from '@/api/report';
import { useUserStore } from '@/store/user';
const store = useUserStore();
const router = useRouter();
const permissionCount = computed(() => store.user?.permissions.length ?? 0);
const summary = ref(null);
const loading = ref(false);
const shortcuts = computed(() => [
    { title: '设备台账', path: '/equipment', permission: 'equipment.view' },
    { title: '使用记录', path: '/operations', permission: 'well_operation.view' },
    { title: '维保工单', path: '/maintenance', permission: 'maintenance.view' },
    { title: '故障记录', path: '/faults', permission: 'fault.view' },
    { title: '耗材管理', path: '/consumables', permission: 'consumable.view' },
    { title: '报表中心', path: '/reports', permission: 'report.view' },
].filter((item) => store.has(item.permission)));
onMounted(async () => {
    loading.value = true;
    try {
        summary.value = await getDashboard();
    }
    catch (error) {
        console.warn('加载总览数据失败', error);
    }
    finally {
        loading.value = false;
    }
});
</script>

<template>
  <div v-loading="loading">
    <div class="stat-cards">
      <div class="stat-card" @click="router.push('/equipment')">
        <div class="stat-label">设备总数</div>
        <div class="stat-value">{{ summary?.equipment_total ?? 0 }}</div>
      </div>
      <div class="stat-card" @click="router.push('/maintenance')">
        <div class="stat-label">待维保设备</div>
        <div class="stat-value warning">{{ summary?.maintenance_due ?? 0 }}</div>
      </div>
      <div class="stat-card" @click="router.push('/faults')">
        <div class="stat-label">未解决故障</div>
        <div class="stat-value danger">{{ summary?.open_faults ?? 0 }}</div>
      </div>
      <div class="stat-card" @click="router.push('/consumables')">
        <div class="stat-label">低库存耗材</div>
        <div class="stat-value warning">{{ summary?.low_stock_consumables ?? 0 }}</div>
      </div>
    </div>

    <div class="page-card">
      <h2 class="page-title">当前账号</h2>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="当前用户">{{ store.displayName }}</el-descriptions-item>
        <el-descriptions-item label="登录名">{{ store.user?.username ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="岗位或部门">{{ store.user?.department ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ store.roles.join('、') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="权限点数量">{{ permissionCount }}</el-descriptions-item>
        <el-descriptions-item label="系统版本">v3.0 网络版</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="page-card">
      <h2 class="page-title">常用入口</h2>
      <div class="shortcuts">
        <el-button v-for="item in shortcuts" :key="item.path" @click="router.push(item.path)">
          {{ item.title }}
        </el-button>
      </div>
    </div>

    <el-alert
      class="dashboard-note"
      type="info"
      :closable="false"
      show-icon
      title="列表的列显示、列顺序与每页条数可在「列设置」里调整，设置随账号保存，换电脑登录同样生效。"
    />
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
  cursor: pointer;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 4px;
}

.stat-card:hover {
  border-color: var(--color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--color-text-secondary);
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

.page-card + .page-card {
  margin-top: 14px;
}

.shortcuts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.dashboard-note {
  margin-top: 18px;
}
</style>
