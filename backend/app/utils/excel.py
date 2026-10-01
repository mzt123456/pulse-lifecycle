"""Excel 导出：用 openpyxl 的写入模式流式生成，避免整表载入内存。"""

from collections.abc import Iterable, Sequence
from io import BytesIO
from urllib.parse import quote

from fastapi import Response
from openpyxl import Workbook


def build_xlsx(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> BytesIO:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("数据")
    sheet.append(list(headers))
    for row in rows:
        sheet.append(["" if value is None else value for value in row])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def xlsx_response(buffer: BytesIO, file_name: str) -> Response:
    """返回下载响应；文件名用 RFC 5987 编码，保证中文文件名不乱码。"""
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}",
        },
    )
