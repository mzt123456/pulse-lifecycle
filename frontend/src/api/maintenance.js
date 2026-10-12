import { request } from '@/api/request';
export function listMaintenanceOrders(params) {
    return request({
        url: '/maintenance-orders',
        method: 'get',
        params,
    });
}
export function getMaintenanceOrder(id) {
    return request({ url: `/maintenance-orders/${id}`, method: 'get' });
}
export function createMaintenanceOrder(payload) {
    return request({ url: '/maintenance-orders', method: 'post', data: payload });
}
export function updateMaintenanceOrder(id, payload) {
    return request({
        url: `/maintenance-orders/${id}`,
        method: 'put',
        data: payload,
    });
}
export function completeStep(orderId, stepId, isDone, remark) {
    return request({
        url: `/maintenance-orders/${orderId}/steps/${stepId}`,
        method: 'post',
        data: { is_done: isDone, remark },
    });
}
