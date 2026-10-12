import { request } from '@/api/request';
export function listOperations(params) {
    return request({ url: '/well-operations', method: 'get', params });
}
export function createOperation(payload) {
    return request({ url: '/well-operations', method: 'post', data: payload });
}
export function updateOperation(id, payload) {
    return request({ url: `/well-operations/${id}`, method: 'put', data: payload });
}
export function deleteOperation(id) {
    return request({ url: `/well-operations/${id}`, method: 'delete' });
}
