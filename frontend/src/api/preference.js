import { request } from '@/api/request';
export function getPreferences() {
    return request({ url: '/user-preferences', method: 'get' });
}
export function savePreferences(payload) {
    return request({ url: '/user-preferences', method: 'put', data: payload });
}
