import { request } from '@/api/request';
export function getDashboard() {
    return request({ url: '/reports/dashboard', method: 'get' });
}
export function getUtilization(params) {
    return request({ url: '/reports/equipment-utilization', method: 'get', params });
}
export function getFaultStatistics(params) {
    return request({ url: '/reports/fault-statistics', method: 'get', params });
}
export function getOperationTrend(months) {
    return request({
        url: '/reports/operation-trend',
        method: 'get',
        params: { months },
    });
}
