import { request } from '@/api/request';
export function listKnowledgeDocuments(params) {
    return request({ url: '/knowledge/documents', method: 'get', params });
}
export function getKnowledgeDocument(id) {
    return request({ url: `/knowledge/documents/${id}`, method: 'get' });
}
export function getKnowledgeStats() {
    return request({ url: '/knowledge/stats', method: 'get' });
}
export function createKnowledgeText(payload) {
    return request({
        url: '/knowledge/documents/text',
        method: 'post',
        data: payload,
    });
}
export function uploadKnowledgeDocument(file, title) {
    const formData = new FormData();
    formData.append('file', file);
    if (title) {
        formData.append('title', title);
    }
    return request({
        url: '/knowledge/documents/upload',
        method: 'post',
        data: formData,
        headers: { 'Content-Type': 'multipart/form-data' },
    });
}
export function deleteKnowledgeDocument(id) {
    return request({ url: `/knowledge/documents/${id}`, method: 'delete' });
}
