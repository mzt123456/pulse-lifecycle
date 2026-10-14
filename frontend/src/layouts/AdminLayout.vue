<script setup>
import { ElMessageBox } from 'element-plus';
import { computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { usePreferencesStore } from '@/store/preferences';
import { useUserStore } from '@/store/user';
const route = useRoute();
const router = useRouter();
const store = useUserStore();
const preferences = usePreferencesStore();
const activeMenu = computed(() => route.path);
const currentTitle = computed(() => route.meta.title ?? '');
const asideWidth = computed(() => (preferences.navCollapsed ? '0px' : '200px'));
/** 菜单按权限点显隐；没有权限点的菜单所有人可见。 */
const MENUS = [
    { path: '/dashboard', title: '数据总览', permission: '' },
    { path: '/equipment', title: '设备管理', permission: 'equipment.view' },
    { path: '/operations', title: '使用管理', permission: 'well_operation.view' },
    { path: '/maintenance', title: '维保管理', permission: 'maintenance.view' },
    { path: '/faults', title: '故障记录', permission: 'fault.view' },
    { path: '/consumables', title: '耗材管理', permission: 'consumable.view' },
    { path: '/reports', title: '报表中心', permission: 'report.view' },
    { path: '/audit-logs', title: '审计日志', permission: 'system.audit' },
    // 账号、角色与权限点维护，只有持有 user.manage 的账号可见
    { path: '/users', title: '用户与权限', permission: 'user.manage' },
    // 知识库是智能助手的语料来源，按 knowledge.view 控制可见性
    { path: '/knowledge', title: '知识库', permission: 'knowledge.view' },
    // 智能助手对登录用户可见：诊断能力需要 fault.view，页内会按权限隐藏该模式
    { path: '/assistant', title: '智能助手', permission: '' },
];
const visibleMenus = computed(() => MENUS.filter((item) => !item.permission || store.has(item.permission)));
onMounted(async () => {
    await preferences.load();
    // 每次进入后台都刷新一次当前用户：权限调整可在下次请求即生效
    try {
        await store.loadMe();
    }
    catch {
        // 令牌失效时由请求封装负责清理并跳转登录页
    }
});
function toggleNav() {
    void preferences.setNavCollapsed(!preferences.navCollapsed);
}
async function handleLogout() {
    try {
        await ElMessageBox.confirm('确定要退出登录吗？', '提示', { type: 'warning' });
    }
    catch {
        return;
    }
    await store.logout();
    preferences.reset();
    await router.replace({ name: 'login' });
}
</script>

<template>
  <el-container class="admin">
    <el-aside :width="asideWidth" class="admin-aside">
      <div class="admin-brand">剪切阀脉冲器</div>
      <el-menu :default-active="activeMenu" router class="admin-menu">
        <el-menu-item v-for="item in visibleMenus" :key="item.path" :index="item.path">
          {{ item.title }}
        </el-menu-item>
      </el-menu>
      <div class="admin-aside-note">设备维保管理 · 演示环境</div>
    </el-aside>

    <el-container>
      <el-header class="admin-header">
        <div class="admin-header-left">
          <el-button link class="nav-toggle" @click="toggleNav">
            {{ preferences.navCollapsed ? '展开导航' : '收起导航' }}
          </el-button>
          <span class="admin-header-title">{{ currentTitle }}</span>
        </div>
        <el-dropdown trigger="click" @command="handleLogout">
          <span class="admin-user">
            {{ store.displayName }}
            <span class="admin-user-roles">{{ store.roles.join('、') }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="admin-main">
        <el-breadcrumb separator="/" class="admin-breadcrumb">
          <el-breadcrumb-item>首页</el-breadcrumb-item>
          <el-breadcrumb-item v-if="currentTitle">{{ currentTitle }}</el-breadcrumb-item>
        </el-breadcrumb>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin {
  height: 100vh;
}

.admin-aside {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-primary);
  color: var(--color-on-primary);
}

.admin-brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 1px;
  border-bottom: 1px solid rgb(255 255 255 / 12%);
}

.admin-menu {
  flex: 1;
  border-right: none;
  background: transparent;
}

.admin-menu :deep(.el-menu-item) {
  color: var(--color-on-primary-muted);
}

.admin-menu :deep(.el-menu-item.is-active) {
  color: var(--color-on-primary);
  background: rgb(41 128 185 / 65%);
}

.admin-aside-note {
  padding: 12px 16px;
  font-size: 12px;
  color: var(--color-text-placeholder);
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.admin-header-title {
  font-size: 16px;
  font-weight: 600;
}

.admin-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-toggle {
  font-size: 13px;
  color: var(--color-primary);
}

.admin-user {
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text);
}

.admin-user-roles {
  margin-left: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.admin-main {
  background: var(--color-bg);
}

.admin-breadcrumb {
  margin-bottom: 14px;
}
</style>
