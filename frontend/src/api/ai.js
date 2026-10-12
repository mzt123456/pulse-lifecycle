/** 智能运维助手接口：故障诊断（RAG）与数据问答（Agent 工具调用）。 */
import { request } from '@/api/request';
/** 诊断与问答都要等模型，默认 15 秒不够用，这里单独放宽。 */
const AI_TIMEOUT_MS = 90000;
export function diagnoseFault(payload) {
    return request({
        url: '/ai/diagnosis',
        method: 'post',
        data: payload,
        timeout: AI_TIMEOUT_MS,
    });
}
export function askQuestion(payload) {
    return request({
        url: '/ai/ask',
        method: 'post',
        data: payload,
        timeout: AI_TIMEOUT_MS,
    });
}
/** 忘掉服务端的会话记忆；不存在时也返回成功（幂等）。 */
export function forgetConversation(conversationId) {
    return request({ url: `/ai/conversations/${conversationId}`, method: 'delete' });
}
export function getCorpusStats() {
    return request({ url: '/ai/corpus/stats', method: 'get' });
}
