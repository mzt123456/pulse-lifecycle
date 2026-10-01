<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useUserStore } from '@/store/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta.title ?? '')

onMounted(async () => {
  // 每次进入后台都刷新一次当前用户：权限调整可在下次请求即生效
  try {
    await store.loadMe()
  } catch {
    // 令牌失效时由请求封装负责清理并跳转登录页
  }
})

async function handleLogout(): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', { type: 'warning' })
  } catch {
    return
  }
  await store.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <el-container class="admin">
    <el-aside width="200px" class="admin-aside">
      <div class="admin-brand">剪切阀脉冲器</div>
      <el-menu :default-active="activeMenu" router class="admin-menu">
        <el-menu-item index="/dashboard">数据总览</el-menu-item>
      </el-menu>
      <div class="admin-aside-note">业务模块将在后续阶段接入</div>
    </el-aside>

    <el-container>
      <el-header class="admin-header">
        <div class="admin-header-title">{{ currentTitle }}</div>
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
  background: var(--color-primary);
  color: #fff;
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
  color: #d5dbdb;
}

.admin-menu :deep(.el-menu-item.is-active) {
  color: #fff;
  background: rgb(41 128 185 / 65%);
}

.admin-aside-note {
  padding: 12px 16px;
  font-size: 12px;
  color: #95a5a6;
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--color-surface);
  border-bottom: 1px solid #d9d9d9;
}

.admin-header-title {
  font-size: 16px;
  font-weight: 600;
}

.admin-user {
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text);
}

.admin-user-roles {
  margin-left: 8px;
  font-size: 12px;
  color: #7f8c8d;
}

.admin-main {
  background: var(--color-bg);
}

.admin-breadcrumb {
  margin-bottom: 14px;
}
</style>
