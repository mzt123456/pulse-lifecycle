import { ref } from 'vue';
import { compactParams } from '@/utils/params';
/**
 * 列表页共用状态：分页、加载、查询与重置。
 * 各页面自己维护筛选条件对象，这里只负责按条件取数与分页。
 */
export function usePagedList(filters, fetcher) {
    const items = ref([]);
    const total = ref(0);
    const loading = ref(false);
    const page = ref(1);
    const pageSize = ref(20);
    async function load() {
        loading.value = true;
        try {
            const params = compactParams({
                ...filters,
                page: page.value,
                page_size: pageSize.value,
            });
            const data = await fetcher(params);
            items.value = data.items;
            total.value = data.total;
        }
        finally {
            loading.value = false;
        }
    }
    async function search() {
        page.value = 1;
        await load();
    }
    async function changePage(next) {
        page.value = next;
        await load();
    }
    async function changeSize(size) {
        pageSize.value = size;
        page.value = 1;
        await load();
    }
    return { items, total, loading, page, pageSize, load, search, changePage, changeSize };
}
