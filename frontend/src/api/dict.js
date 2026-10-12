import { request } from '@/api/request';
export function getDictItems() {
    return request({ url: '/dict-items', method: 'get' });
}
