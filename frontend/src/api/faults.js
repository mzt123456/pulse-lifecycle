import { request } from '@/api/request';
export function listFaults(params) {
    return request({ url: '/fault-records', method: 'get', params });
}
export function createFault(payload) {
    return request({ url: '/fault-records', method: 'post', data: payload });
}
export function updateFault(id, payload) {
    return request({ url: `/fault-records/${id}`, method: 'put', data: payload });
}
