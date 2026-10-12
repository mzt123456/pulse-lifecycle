import { request } from '@/api/request';
export function listEquipment(params) {
    return request({ url: '/equipment', method: 'get', params });
}
export function createEquipment(payload) {
    return request({ url: '/equipment', method: 'post', data: payload });
}
export function updateEquipment(id, payload) {
    return request({ url: `/equipment/${id}`, method: 'put', data: payload });
}
export function deleteEquipment(id) {
    return request({ url: `/equipment/${id}`, method: 'delete' });
}
