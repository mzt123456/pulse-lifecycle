/** 去掉空值查询条件：空字符串不是合法的时间/数值参数，传给后端会被判为非法。 */
export function compactParams(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== '' && value !== null && value !== undefined,
    ),
  )
}
