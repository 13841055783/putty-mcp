"""向已打开的 PuTTY 窗口发送命令。

通过剪贴板粘贴（IDM_PASTE，适合长命令行）或 WM_CHAR 发送文本；
Ctrl+C 等控制字符需要通过 WM_CHAR 发送。
消息直接发送到 PuTTY 窗口句柄，不恢复窗口、不置顶，也不切换焦点。
依赖 Windows 环境中的 pywin32。
"""

from __future__ import annotations

import sys
import time
from typing import Any

if sys.platform != "win32":
    def send_putty_command(
        command: str,
        host: str | None = None,
        title_substring: str | None = None,
        process_id: int | None = None,
        append_newline: bool = True,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Sending to PuTTY window is supported only on Windows.",
        }

    def clear_putty_window(
        host: str | None = None,
        title_substring: str | None = None,
        process_id: int | None = None,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Clearing PuTTY window is supported only on Windows.",
        }
else:
    try:
        import win32clipboard
        import win32con
        import win32gui
    except ImportError:
        def send_putty_command(
            command: str,
            host: str | None = None,
            title_substring: str | None = None,
            process_id: int | None = None,
            append_newline: bool = True,
        ) -> dict[str, Any]:
            return {
                "success": False,
                "error": "pywin32 is required. Install with: pip install pywin32",
            }

        def clear_putty_window(
            host: str | None = None,
            title_substring: str | None = None,
            process_id: int | None = None,
        ) -> dict[str, Any]:
            return {
                "success": False,
                "error": "pywin32 is required. Install with: pip install pywin32",
            }
    else:
        from putty_lib import window_reader

        WM_CHAR = 0x0102
        WM_SYSCOMMAND = 0x0112
        # PuTTY 系统菜单命令 ID，取自上游源码 windows/window.c。
        IDM_CLRSB = 0x0060
        IDM_PASTE = 0x01A0

        # 普通文本使用粘贴发送。此前逐字符 WM_CHAR 发送长命令时，
        # 终端行规程与自动换行的交互会导致命令截断，
        # 使 ash 停留在“>”续行提示符处等待输入。
        _PASTE_MIN_LEN = 1

        _CHAR_DELAY_S = 0.01
        _PASTE_DELAY_S = 0.15

        def _command_needs_wm_char(command: str) -> bool:
            """当内容无法通过粘贴表达（如包含控制字符）时返回 True。"""
            if not command:
                return True
            for ch in command:
                code = ord(ch)
                # 允许制表符、换行和回车；其余编码小于空格的控制字符必须逐字符发送。
                if code < 32 and ch not in ("\t", "\n", "\r"):
                    return True
            return False

        def _clipboard_get_text() -> str | None:
            try:
                win32clipboard.OpenClipboard()
                try:
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                except (TypeError, OSError):
                    return None
            except Exception:
                return None
            finally:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass

        def _clipboard_set_text(text: str) -> None:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()

        def _send_with_wm_char(hwnd: int, command: str, append_newline: bool) -> None:
            text = command + ("\r" if append_newline else "")
            for c in text:
                win32gui.SendMessage(hwnd, WM_CHAR, 13 if c == "\n" else ord(c), 0)
                time.sleep(_CHAR_DELAY_S)

        def _send_with_paste(hwnd: int, command: str, append_newline: bool) -> str:
            """通过 PuTTY 的 IDM_PASTE 粘贴文本，随后恢复之前保存的剪贴板文本。

            返回发送方式标识，供工具响应使用。
            """
            old = _clipboard_get_text()
            try:
                _clipboard_set_text(command)
                # 与全部复制、清空滚动历史相同，通过系统菜单命令 ID 触发操作。
                win32gui.PostMessage(hwnd, WM_SYSCOMMAND, IDM_PASTE, 0)
                # 等待 PuTTY 读取剪贴板并将粘贴内容送入终端。
                # 根据文本长度略微延长等待，避免大段粘贴时发生时序竞争。
                time.sleep(_PASTE_DELAY_S + min(len(command), 4000) * 0.00005)
                if append_newline:
                    win32gui.SendMessage(hwnd, WM_CHAR, 13, 0)
                    time.sleep(_CHAR_DELAY_S)
            finally:
                if old is not None:
                    try:
                        _clipboard_set_text(old)
                    except Exception:
                        pass
            return "paste"

        def send_putty_command(
            command: str,
            host: str | None = None,
            title_substring: str | None = None,
            process_id: int | None = None,
            append_newline: bool = True,
        ) -> dict[str, Any]:
            resolved = window_reader.resolve_putty_window(
                host=host,
                title_substring=title_substring,
                process_id=process_id,
            )
            if not resolved.get("success"):
                return {
                    "success": False,
                    "error": resolved.get("error", "No PuTTY window selected."),
                    "windows": resolved.get("windows", []),
                }
            hwnd = resolved["hwnd"]
            title = resolved.get("title", "")
            method = "wm_char"
            # 粘贴和 WM_CHAR 均直接发送到目标窗口句柄，无需恢复、置顶或切换焦点。
            # SW_RESTORE 会使最大化的 PuTTY 恢复原尺寸，
            # SetForegroundWindow 则会抢占用户当前的输入焦点。
            try:
                activated = win32gui.GetForegroundWindow() == hwnd
            except Exception:
                activated = False
            try:
                # 普通文本优先使用剪贴板批量粘贴，避免逐字符 WM_CHAR
                # 发送长命令行时发生中途截断。
                if (
                    len(command) >= _PASTE_MIN_LEN
                    and not _command_needs_wm_char(command)
                ):
                    method = _send_with_paste(hwnd, command, append_newline)
                else:
                    _send_with_wm_char(hwnd, command, append_newline)
                    method = "wm_char"
            except Exception as e:
                return {"success": False, "error": f"Send failed: {e}"}
            return {
                "success": True,
                "window_title": title,
                "command_sent": command + ("\n" if append_newline else ""),
                "activated": activated,
                "delivery": method,
            }

        def clear_putty_window(
            host: str | None = None,
            title_substring: str | None = None,
            process_id: int | None = None,
        ) -> dict[str, Any]:
            """通过不依赖界面语言的方式清空 PuTTY 滚动历史。"""
            resolved = window_reader.resolve_putty_window(
                host=host,
                title_substring=title_substring,
                process_id=process_id,
            )
            if not resolved.get("success"):
                return {
                    "success": False,
                    "error": resolved.get("error", "No PuTTY window selected."),
                    "windows": resolved.get("windows", []),
                }

            hwnd = resolved["hwnd"]
            title = resolved.get("title", "")

            try:
                # 直接调用 PuTTY 清空滚动历史的命令 ID，不依赖界面语言。
                win32gui.PostMessage(hwnd, WM_SYSCOMMAND, IDM_CLRSB, 0)
                time.sleep(0.1)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to clear PuTTY scrollback: {e}",
                    "window_title": title,
                }

            return {
                "success": True,
                "window_title": title,
                "message": "PuTTY scrollback was cleared.",
            }
