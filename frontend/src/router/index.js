import { createRouter, createWebHistory } from 'vue-router';
import { getAccessToken } from '@/utils/token';
const routes = [
    {
        path: '/login',
        name: 'login',
        component: () => import('@/views/LoginView.vue'),
        meta: { public: true, title: '登录' },
    },
    {
        path: '/',
        component: () => import('@/layouts/AdminLayout.vue'),
        children: [
            { path: '', redirect: { name: 'dashboard' } },
            {
                path: 'dashboard',
                name: 'dashboard',
                component: () => import('@/views/DashboardView.vue'),
                meta: { title: '数据总览' },
            },
            {
                path: 'equipment',
                name: 'equipment',
                component: () => import('@/views/equipment/EquipmentList.vue'),
                meta: { title: '设备管理' },
            },
            {
                path: 'operations',
                name: 'operations',
                component: () => import('@/views/operations/WellOperationList.vue'),
                meta: { title: '使用管理' },
            },
            {
                path: 'maintenance',
                name: 'maintenance',
                component: () => import('@/views/maintenance/MaintenanceList.vue'),
                meta: { title: '维保管理' },
            },
            {
                path: 'faults',
                name: 'faults',
                component: () => import('@/views/faults/FaultList.vue'),
                meta: { title: '故障记录' },
            },
            {
                path: 'consumables',
                name: 'consumables',
                component: () => import('@/views/consumables/ConsumableList.vue'),
                meta: { title: '耗材管理' },
            },
            {
                path: 'audit-logs',
                name: 'audit-logs',
                component: () => import('@/views/system/AuditLogList.vue'),
                meta: { title: '审计日志' },
            },
            {
                path: 'reports',
                name: 'reports',
                component: () => import('@/views/report/ReportView.vue'),
                meta: { title: '报表中心' },
            },
            {
                path: 'assistant',
                name: 'assistant',
                component: () => import('@/views/ai/AssistantView.vue'),
                meta: { title: '智能助手' },
            },
            {
                path: 'knowledge',
                name: 'knowledge',
                component: () => import('@/views/knowledge/KnowledgeList.vue'),
                meta: { title: '知识库' },
            },
        ],
    },
    { path: '/:pathMatch(.*)*', redirect: { name: 'dashboard' } },
];
const router = createRouter({
    history: createWebHistory(),
    routes,
});
router.beforeEach((to) => {
    const loggedIn = Boolean(getAccessToken());
    if (!to.meta.public && !loggedIn) {
        return { name: 'login', query: { redirect: to.fullPath } };
    }
    if (to.name === 'login' && loggedIn) {
        return { name: 'dashboard' };
    }
    return true;
});
router.afterEach((to) => {
    const title = to.meta.title;
    document.title = title
        ? `${title} - 剪切阀脉冲器全生命周期管理系统`
        : '剪切阀脉冲器全生命周期管理系统';
});
export default router;
