"""仅提供 PuTTY 窗口交互工具的 MCP 服务。"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from putty_lib import window_reader
from putty_lib import window_send
from putty_lib import window_upload

mcp = FastMCP("putty-mcp", json_response=True)


@mcp.tool()
def putty_list_windows() -> dict:
    """列出所有可见 PuTTY 窗口的标题和 PID。仅支持 Windows，依赖 pywin32。"""
    windows = window_reader.list_putty_windows()
    return {
        "success": True,
        "windows": [{"title": w["title"], "pid": w["pid"]} for w in windows],
        "count": len(windows),
    }


@mcp.tool()
def putty_read_window(
    host: str | None = None,
    title_substring: str | None = None,
    process_id: int | None = None,
) -> dict:
    """通过“全部复制到剪贴板”读取已打开 PuTTY 窗口的屏幕及滚动历史文本。
    存在多个窗口时，通过 host、title_substring 或 process_id 选择目标窗口。
    仅支持 Windows，依赖 pywin32。读取后恢复之前保存的剪贴板文本。"""
    return window_reader.read_putty_window(
        host=host,
        title_substring=title_substring,
        process_id=process_id,
    )


@mcp.tool()
def putty_send_command(
    command: str,
    host: str | None = None,
    title_substring: str | None = None,
    process_id: int | None = None,
    append_newline: bool = True,
) -> dict:
    """向已打开的 PuTTY 窗口发送命令，可选择是否追加回车。
    普通文本通过 PuTTY 剪贴板粘贴发送，以提高长命令行的可靠性；
    Ctrl+C 等控制字符仍通过 WM_CHAR 逐字符发送。
    不恢复窗口、不置顶，也不切换焦点。
    存在多个窗口时，通过 host、title_substring 或 process_id 选择目标窗口。
    仅支持 Windows，依赖 pywin32。"""
    return window_send.send_putty_command(
        command=command,
        host=host,
        title_substring=title_substring,
        process_id=process_id,
        append_newline=append_newline,
    )


@mcp.tool()
def putty_clear_window(
    host: str | None = None,
    title_substring: str | None = None,
    process_id: int | None = None,
) -> dict:
    """清空所选 PuTTY 窗口的滚动历史。
    可在读取窗口内容前调用，以减少旧历史对上下文的干扰。"""
    return window_send.clear_putty_window(
        host=host,
        title_substring=title_substring,
        process_id=process_id,
    )


@mcp.tool()
def putty_upload_text(
    content: str,
    remote_path: str,
    host: str | None = None,
    title_substring: str | None = None,
    process_id: int | None = None,
    encoding: Literal["shell", "hex"] = "shell",
    chunk_size: int | None = None,
    verify: bool = True,
) -> dict:
    """通过多条短 printf 命令，将文本或数据分块写入远程文件。

    适用于超过约 400 个字符的内容，以避开远程终端的行长度限制。
    encoding='shell' 适合快速传输 UTF-8 文本；encoding='hex' 可安全传输二进制数据，
    无需远程主机提供 base64 命令。
    存在多个窗口时，通过 host、title_substring 或 process_id 选择目标窗口。
    仅支持 Windows，依赖 pywin32。"""
    return window_upload.upload_putty_text(
        content=content,
        remote_path=remote_path,
        host=host,
        title_substring=title_substring,
        process_id=process_id,
        encoding=encoding,
        chunk_size=chunk_size,
        verify=verify,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
