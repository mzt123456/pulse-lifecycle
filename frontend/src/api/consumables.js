import { request } from '@/api/request';
export function listConsumables(params) {
    return request({ url: '/consumables', method: 'get', params });
}
export function createConsumable(payload) {
    return request({ url: '/consumables', method: 'post', data: payload });
}
export function updateConsumable(id, payload) {
    return request({ url: `/consumables/${id}`, method: 'put', data: payload });
}
export function issueConsumable(consumableId, quantity, remark) {
    return request({
        url: '/consumables/usages',
        method: 'post',
        data: { consumable_id: consumableId, quantity, remark },
    });
}
export function importConsumables(file) {
    const formData = new FormData();
    formData.append('file', file);
    return request({
        url: '/consumables/import',
        method: 'post',
        data: formData,
        headers: { 'Content-Type': 'multipart/form-data' },
    });
}
