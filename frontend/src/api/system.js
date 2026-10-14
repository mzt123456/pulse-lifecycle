import http, { request } from '@/api/request';
import { triggerDownload } from '@/utils/download';
export function listAuditLogs(params) {
    return request({ url: '/system/audit-logs', method: 'get', params });
}
export function listAttachments(params) {
    return request({ url: '/attachments', method: 'get', params });
}
export function uploadAttachment(file, objectType, objectId) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('object_type', objectType);
    formData.append('object_id', String(objectId));
    return request({
        url: '/attachments',
        method: 'post',
        data: formData,
        headers: { 'Content-Type': 'multipart/form-data' },
    });
}
/** 下载走带令牌的请求再触发浏览器保存，避免直接开链接丢掉鉴权头。 */
export async function downloadAttachment(id, fileName) {
    const blob = (await http.get(`/attachments/${id}`, { responseType: 'blob' }));
    triggerDownload(blob, fileName);
}

// ------------------------------------------------------------- 用户与权限管理

export function listUsers(params) {
    return request({ url: '/system/users', method: 'get', params });
}

export function createUser(payload) {
    return request({ url: '/system/users', method: 'post', data: payload });
}

export function updateUser(id, payload) {
    return request({ url: `/system/users/${id}`, method: 'put', data: payload });
}

export function resetUserPassword(id, password) {
    return request({ url: `/system/users/${id}/password`, method: 'post', data: { password } });
}

export function listRoles() {
    return request({ url: '/system/roles', method: 'get' });
}

export function createRole(payload) {
    return request({ url: '/system/roles', method: 'post', data: payload });
}

export function updateRole(id, payload) {
    return request({ url: `/system/roles/${id}`, method: 'put', data: payload });
}

export function deleteRole(id) {
    return request({ url: `/system/roles/${id}`, method: 'delete' });
}

export function listPermissions() {
    return request({ url: '/system/permissions', method: 'get' });
}
