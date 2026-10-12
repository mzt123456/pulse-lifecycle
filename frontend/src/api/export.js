import http from '@/api/request';
import { triggerDownload } from '@/utils/download';
/** 导出走带令牌的请求，筛选条件与列表一致。 */
export async function downloadExcel(url, params, fileName) {
    const blob = (await http.get(url, { params, responseType: 'blob' }));
    triggerDownload(blob, fileName);
}
