import { request } from '@/api/request';
export function loginApi(username, password) {
    return request({
        url: '/auth/login',
        method: 'post',
        data: { username, password },
    });
}
export function logoutApi(refreshToken) {
    return request({
        url: '/auth/logout',
        method: 'post',
        data: { refresh_token: refreshToken },
    });
}
export function getMeApi() {
    return request({ url: '/auth/me', method: 'get' });
}
