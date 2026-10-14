<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createRole,
  createUser,
  deleteRole,
  listPermissions,
  listRoles,
  listUsers,
  resetUserPassword,
  updateRole,
  updateUser,
} from '@/api/system'
import DataTable from '@/components/DataTable.vue'
import { usePagedList } from '@/composables/usePagedList'
import { usePreferencesStore } from '@/store/preferences'
import { useUserStore } from '@/store/user'

const store = useUserStore()
const preferences = usePreferencesStore()

const columns = [
  { key: 'username', label: '登录名', width: 140 },
  { key: 'real_name', label: '姓名', width: 110 },
  { key: 'department', label: '岗位/部门', width: 130 },
  { key: 'roles', label: '角色', minWidth: 180 },
  { key: 'is_active', label: '状态', width: 90, align: 'center' },
  { key: 'last_login_at', label: '最近登录', width: 170 },
  { key: 'actions', label: '操作', width: 230, fixed: 'right', align: 'center' },
]

const filters = reactive({ is_active: undefined, role_id: undefined })
const query = reactive({ keyword: '', is_active: undefined, role_id: undefined })
const keyword = ref('')

const { items, total, loading, page, pageSize, load, search, changePage, changeSize } =
  usePagedList(query, listUsers)

const roles = ref([])
const permissions = ref([])
const activeTab = ref('users')

const permissionGroups = computed(() => {
  const grouped = new Map()
  for (const item of permissions.value) {
    if (!grouped.has(item.module)) {
      grouped.set(item.module, [])
    }
    grouped.get(item.module).push(item)
  }
  return [...grouped.entries()].map(([module, items]) => ({ module, items }))
})

async function loadMeta() {
  const [roleData, permissionData] = await Promise.all([listRoles(), listPermissions()])
  roles.value = roleData.items
  permissions.value = permissionData.items
}

async function refresh() {
  await Promise.all([load(), loadMeta()])
}

async function applyFilters() {
  query.keyword = keyword.value.trim()
  query.is_active = filters.is_active
  query.role_id = filters.role_id
  await search()
}

async function resetFilters() {
  keyword.value = ''
  filters.is_active = undefined
  filters.role_id = undefined
  await applyFilters()
}

onMounted(async () => {
  await preferences.load()
  pageSize.value = preferences.pageSize
  await refresh()
})

function changePageSize(size) {
  void preferences.setPageSize(size)
  void changeSize(size)
}

// ------------------------------------------------------------------ 账号

const userVisible = ref(false)
const userSubmitting = ref(false)
const editingUserId = ref(null)
const userForm = reactive({
  username: '',
  password: '',
  real_name: '',
  phone: '',
  department: '',
  role_ids: [],
  is_active: true,
})

function openCreate() {
  editingUserId.value = null
  Object.assign(userForm, {
    username: '',
    password: '',
    real_name: '',
    phone: '',
    department: '',
    role_ids: [],
    is_active: true,
  })
  userVisible.value = true
}

function openEdit(row) {
  editingUserId.value = row.id
  Object.assign(userForm, {
    username: row.username,
    password: '',
    real_name: row.real_name ?? '',
    phone: row.phone ?? '',
    department: row.department ?? '',
    role_ids: [...row.role_ids],
    is_active: row.is_active,
  })
  userVisible.value = true
}

async function submitUser() {
  if (!userForm.real_name.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (!userForm.role_ids.length) {
    ElMessage.warning('至少分配一个角色')
    return
  }
  userSubmitting.value = true
  try {
    if (editingUserId.value === null) {
      await createUser({
        username: userForm.username.trim(),
        password: userForm.password,
        real_name: userForm.real_name.trim(),
        phone: userForm.phone || null,
        department: userForm.department || null,
        role_ids: userForm.role_ids,
      })
      ElMessage.success('账号已创建')
    } else {
      await updateUser(editingUserId.value, {
        real_name: userForm.real_name.trim(),
        phone: userForm.phone || null,
        department: userForm.department || null,
        role_ids: userForm.role_ids,
        is_active: userForm.is_active,
      })
      ElMessage.success('账号已更新')
    }
    userVisible.value = false
    await refresh()
  } catch (error) {
    console.warn('保存账号失败', error)
  } finally {
    userSubmitting.value = false
  }
}

async function toggleActive(row) {
  const action = row.is_active ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(
      row.is_active
        ? `停用后 ${row.username} 将无法登录，已登录的会话会被强制下线。确定停用吗？`
        : `确定启用 ${row.username} 吗？`,
      `${action}账号`,
      { type: 'warning' },
    )
  } catch {
    return
  }
  await updateUser(row.id, { is_active: !row.is_active })
  ElMessage.success(`已${action}`)
  await refresh()
}

const passwordVisible = ref(false)
const passwordSubmitting = ref(false)
const passwordTarget = ref(null)
const passwordForm = reactive({ password: '' })

function openReset(row) {
  passwordTarget.value = row
  passwordForm.password = ''
  passwordVisible.value = true
}

async function submitPassword() {
  if (passwordForm.password.length < 8) {
    ElMessage.warning('口令至少 8 位')
    return
  }
  passwordSubmitting.value = true
  try {
    await resetUserPassword(passwordTarget.value.id, passwordForm.password)
    ElMessage.success('口令已重置，该账号的旧会话已失效')
    passwordVisible.value = false
  } catch (error) {
    console.warn('重置口令失败', error)
  } finally {
    passwordSubmitting.value = false
  }
}

// ------------------------------------------------------------------ 角色

const roleVisible = ref(false)
const roleSubmitting = ref(false)
const editingRoleId = ref(null)
const roleForm = reactive({ name: '', description: '', permission_ids: [] })

function openCreateRole() {
  editingRoleId.value = null
  Object.assign(roleForm, { name: '', description: '', permission_ids: [] })
  roleVisible.value = true
}

function openEditRole(row) {
  editingRoleId.value = row.id
  Object.assign(roleForm, {
    name: row.name,
    description: row.description ?? '',
    permission_ids: [...row.permission_ids],
  })
  roleVisible.value = true
}

async function submitRole() {
  if (!roleForm.name.trim()) {
    ElMessage.warning('请填写角色名称')
    return
  }
  roleSubmitting.value = true
  try {
    if (editingRoleId.value === null) {
      await createRole({
        name: roleForm.name.trim(),
        description: roleForm.description || null,
        permission_ids: roleForm.permission_ids,
      })
      ElMessage.success('角色已创建')
    } else {
      await updateRole(editingRoleId.value, {
        description: roleForm.description || null,
        permission_ids: roleForm.permission_ids,
      })
      ElMessage.success('角色已更新')
    }
    roleVisible.value = false
    await refresh()
  } catch (error) {
    console.warn('保存角色失败', error)
  } finally {
    roleSubmitting.value = false
  }
}

async function removeRole(row) {
  try {
    await ElMessageBox.confirm(`确定删除角色「${row.name}」吗？`, '删除角色', { type: 'warning' })
  } catch {
    return
  }
  await deleteRole(row.id)
  ElMessage.success('已删除')
  await refresh()
}
</script>

<template>
  <div class="page-card">
    <h2 class="page-title">用户与权限</h2>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="账号" name="users">
        <el-form :inline="true" class="filter-bar">
          <el-form-item label="账号">
            <el-input
              v-model="keyword"
              placeholder="登录名或姓名"
              clearable
              style="width: 180px"
              @keyup.enter="applyFilters"
            />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="filters.is_active" placeholder="全部" clearable style="width: 120px">
              <el-option label="启用" :value="true" />
              <el-option label="停用" :value="false" />
            </el-select>
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="filters.role_id" placeholder="全部" clearable style="width: 160px">
              <el-option v-for="item in roles" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="applyFilters">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
          </el-form-item>
        </el-form>

        <DataTable table-key="sys_user" :columns="columns" :data="items" :loading="loading">
          <template #toolbar>
            <el-button type="success" @click="openCreate">新建账号</el-button>
          </template>

          <template #cell-roles="{ row }">
            <el-tag v-for="name in row.roles" :key="name" size="small" class="role-tag">
              {{ name }}
            </el-tag>
            <span v-if="!row.roles.length">-</span>
          </template>

          <template #cell-is_active="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>

          <template #cell-last_login_at="{ row }">{{ row.last_login_at || '-' }}</template>

          <template #cell-actions="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openReset(row)">重置口令</el-button>
            <el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggleActive(row)">
              {{ row.is_active ? '停用' : '启用' }}
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
      </el-tab-pane>

      <el-tab-pane label="角色与权限点" name="roles">
        <el-alert
          class="role-note"
          type="info"
          :closable="false"
          show-icon
          title="内置角色的名称与删除不开放（权限范围是业务口径的一部分），说明与权限点可以调整；系统管理员固定拥有全部权限。"
        />

        <div class="role-toolbar">
          <el-button type="success" @click="openCreateRole">新建角色</el-button>
        </div>

        <el-table v-loading="loading" :data="roles" border stripe>
          <el-table-column prop="name" label="角色" width="160" />
          <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="类型" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_builtin ? 'warning' : 'info'">
                {{ row.is_builtin ? '内置' : '自定义' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="权限点" width="90" align="right">
            <template #default="{ row }">
              {{ row.name === '系统管理员' ? '全部' : row.permission_ids.length }}
            </template>
          </el-table-column>
          <el-table-column prop="user_count" label="账号数" width="90" align="right" />
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditRole(row)">编辑权限</el-button>
              <el-button
                v-if="!row.is_builtin"
                link
                type="danger"
                @click="removeRole(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="userVisible"
      :title="editingUserId === null ? '新建账号' : '编辑账号'"
      width="620px"
    >
      <el-form :model="userForm" label-width="90px">
        <el-form-item label="登录名" required>
          <el-input v-model="userForm.username" :disabled="editingUserId !== null" />
        </el-form-item>
        <el-form-item v-if="editingUserId === null" label="初始口令" required>
          <el-input v-model="userForm.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="userForm.real_name" />
        </el-form-item>
        <el-form-item label="岗位/部门">
          <el-input v-model="userForm.department" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="userForm.phone" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="userForm.role_ids" multiple style="width: 100%">
            <el-option
              v-for="item in roles"
              :key="item.id"
              :label="item.description ? `${item.name}（${item.description}）` : item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingUserId !== null" label="状态">
          <el-switch v-model="userForm.is_active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userVisible = false">取消</el-button>
        <el-button type="primary" :loading="userSubmitting" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordVisible" title="重置口令" width="460px">
      <p class="dialog-hint">
        为 {{ passwordTarget?.username }} 设置新口令，保存后该账号已登录的会话会立即失效。
      </p>
      <el-input
        v-model="passwordForm.password"
        type="password"
        show-password
        placeholder="至少 8 位"
      />
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="passwordSubmitting" @click="submitPassword">
          重置
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="roleVisible"
      :title="editingRoleId === null ? '新建角色' : `编辑角色：${roleForm.name}`"
      width="720px"
    >
      <el-form :model="roleForm" label-width="90px">
        <el-form-item label="角色名称" required>
          <el-input v-model="roleForm.name" :disabled="editingRoleId !== null" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="roleForm.description" placeholder="例如：现场技术员（只能看台账与作业）" />
        </el-form-item>
        <el-form-item label="权限点">
          <div class="permission-box">
            <div v-for="group in permissionGroups" :key="group.module" class="permission-group">
              <span class="permission-module">{{ group.module }}</span>
              <el-checkbox-group v-model="roleForm.permission_ids">
                <el-tooltip
                  v-for="item in group.items"
                  :key="item.id"
                  :content="item.description || item.code"
                  placement="top"
                >
                  <el-checkbox :value="item.id">{{ item.action }}</el-checkbox>
                </el-tooltip>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSubmitting" @click="submitRole">保存</el-button>
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

.role-note {
  margin-bottom: 12px;
}

.role-toolbar {
  margin-bottom: 10px;
}

.role-tag {
  margin-right: 6px;
}

.dialog-hint {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.permission-box {
  max-height: 320px;
  overflow-y: auto;
  padding-right: 6px;
  width: 100%;
}

.permission-group {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--color-border);
}

.permission-module {
  flex: 0 0 110px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  color: var(--color-text-secondary);
}
</style>
