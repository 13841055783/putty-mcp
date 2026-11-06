"""通过 PuTTY 将文本或二进制数据分块写入远程路径。

远程终端的行长度限制（BusyBox 环境通常约为 512）无法容纳数 KB 的单行命令。
因此，本模块使用多条短 printf 命令分块写入文件。
"""

from __future__ import annotations

import sys
import time
from typing import Any, Literal

Encoding = Literal["shell", "hex"]

# 让每条 shell 命令的长度明显低于 BusyBox 常见的 MAX_CANON 限制（约 512）。
_DEFAULT_SHELL_CHUNK = 120
_DEFAULT_HEX_CHUNK = 40  # 40 字节转换后占 160 个十六进制转义字符。
_CHUNK_DELAY_S = 0.08
_SETTLE_S = 0.25


def _shell_single_quote(text: str) -> str:
    """将文本转义并包裹为 POSIX 单引号字符串，不支持 NUL 字符。"""
    return "'" + text.replace("'", "'\\''") + "'"


def _hex_printf_payload(data: bytes) -> str:
    """将字节编码为 BusyBox 兼容的 printf %b 转义序列：\\xHH\\xHH...。"""
    return "".join(f"\\x{b:02x}" for b in data)


if sys.platform != "win32":
    def upload_putty_text(
        content: str | bytes,
        remote_path: str,
        host: str | None = None,
        title_substring: str | None = None,
        process_id: int | None = None,
        encoding: Encoding = "shell",
        chunk_size: int | None = None,
        verify: bool = True,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Uploading via PuTTY is supported only on Windows.",
        }
else:
    from putty_lib import window_reader, window_send

    def upload_putty_text(
        content: str | bytes,
        remote_path: str,
        host: str | None = None,
        title_substring: str | None = None,
        process_id: int | None = None,
        encoding: Encoding = "shell",
        chunk_size: int | None = None,
        verify: bool = True,
    ) -> dict[str, Any]:
        """使用多条短 printf 命令，将内容分块追加到 remote_path。

        encoding 参数说明：
          - shell：通过单引号包裹的 printf 分块写入 UTF-8 文本，速度较快，不支持 NUL 字节。
          - hex：通过 printf %b 写入 \\xHH 转义序列，可安全传输二进制数据，无需远程 base64 命令。
        """
        if not remote_path or remote_path.startswith("-"):
            return {"success": False, "error": "remote_path must be a non-empty absolute/relative path."}
        if encoding not in ("shell", "hex"):
            return {"success": False, "error": "encoding must be 'shell' or 'hex'."}

        selector = {
            "host": host,
            "title_substring": title_substring,
            "process_id": process_id,
        }

        if isinstance(content, str):
            raw = content.encode("utf-8")
        else:
            raw = content

        if encoding == "shell" and b"\x00" in raw:
            return {
                "success": False,
                "error": "shell encoding cannot carry NUL bytes; use encoding='hex'.",
            }

        path_q = _shell_single_quote(remote_path)
        clear = window_send.send_putty_command(f": > {path_q}", **selector)
        if not clear.get("success"):
            return clear
        time.sleep(_SETTLE_S)

        chunks_sent = 0
        if encoding == "shell":
            text = raw.decode("utf-8")
            size = chunk_size or _DEFAULT_SHELL_CHUNK
            for offset in range(0, len(text), size):
                piece = text[offset : offset + size]
                cmd = f"printf '%s' {_shell_single_quote(piece)} >> {path_q}"
                if len(cmd) > 480:
                    return {
                        "success": False,
                        "error": f"Chunk command too long ({len(cmd)}); reduce chunk_size.",
                        "chunks_sent": chunks_sent,
                    }
                result = window_send.send_putty_command(cmd, **selector)
                if not result.get("success"):
                    return {
                        "success": False,
                        "error": result.get("error", "chunk send failed"),
                        "chunks_sent": chunks_sent,
                    }
                chunks_sent += 1
                time.sleep(_CHUNK_DELAY_S)
        else:
            size = chunk_size or _DEFAULT_HEX_CHUNK
            for offset in range(0, len(raw), size):
                piece = raw[offset : offset + size]
                esc = _hex_printf_payload(piece)
                cmd = f"printf '%b' '{esc}' >> {path_q}"
                if len(cmd) > 480:
                    return {
                        "success": False,
                        "error": f"Chunk command too long ({len(cmd)}); reduce chunk_size.",
                        "chunks_sent": chunks_sent,
                    }
                result = window_send.send_putty_command(cmd, **selector)
                if not result.get("success"):
                    return {
                        "success": False,
                        "error": result.get("error", "chunk send failed"),
                        "chunks_sent": chunks_sent,
                    }
                chunks_sent += 1
                time.sleep(_CHUNK_DELAY_S)

        expected = len(raw)
        remote_size = None
        if verify:
            marker = f"UP{expected}"
            window_send.send_putty_command(
                f"wc -c < {path_q}; echo {marker}",
                **selector,
            )
            time.sleep(0.8)
            read = window_reader.read_putty_window(**selector)
            content_out = read.get("content") or ""
            # 尝试从标记之前的文本行中解析远程文件字节数。
            if marker in content_out:
                before = content_out.rsplit(marker, 1)[0]
                for line in reversed(before.splitlines()):
                    line = line.strip()
                    if line.isdigit():
                        remote_size = int(line)
                        break
            if remote_size != expected:
                return {
                    "success": False,
                    "error": f"Size mismatch after upload: remote={remote_size} expected={expected}",
                    "remote_path": remote_path,
                    "bytes": expected,
                    "remote_bytes": remote_size,
                    "chunks_sent": chunks_sent,
                    "encoding": encoding,
                }

        return {
            "success": True,
            "remote_path": remote_path,
            "bytes": expected,
            "remote_bytes": remote_size if verify else None,
            "chunks_sent": chunks_sent,
            "encoding": encoding,
        }
