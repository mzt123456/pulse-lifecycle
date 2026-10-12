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
