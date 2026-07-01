from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class WindowNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class DesktopWindow:
    id: str
    handle: int
    title: str
    process_id: int
    process_name: str = ""
    executable_path: str = ""
    class_name: str = ""
    is_active: bool = False
    bounds: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bounds"] = data["bounds"] or {}
        return data


def is_supported_platform() -> bool:
    return sys.platform == "win32"


def list_windows(limit: int = 120) -> list[DesktopWindow]:
    if not is_supported_platform():
        return []

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _configure_user32(user32, wintypes)
    active_handle = int(user32.GetForegroundWindow() or 0)
    process_cache: dict[int, tuple[str, str]] = {}
    rows: list[DesktopWindow] = []

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        title = _window_title(user32, hwnd)
        if not _should_include_window(title):
            return True

        process_id = _window_process_id(user32, hwnd)
        if process_id not in process_cache:
            process_cache[process_id] = _process_identity(process_id)
        process_name, executable_path = process_cache[process_id]

        rows.append(
            DesktopWindow(
                id=str(int(hwnd)),
                handle=int(hwnd),
                title=title,
                process_id=process_id,
                process_name=process_name,
                executable_path=executable_path,
                class_name=_window_class_name(user32, hwnd),
                is_active=int(hwnd) == active_handle,
                bounds=_window_bounds(user32, hwnd),
            )
        )
        return len(rows) < limit

    user32.EnumWindows(_callback, 0)
    rows.sort(key=lambda item: (not item.is_active, item.process_name.lower(), item.title.lower()))
    return rows


def get_window(window_id: str) -> DesktopWindow:
    if not is_supported_platform():
        raise WindowNotFoundError("Desktop window capture is only available on Windows.")

    import ctypes

    try:
        handle = int(window_id)
    except (TypeError, ValueError) as exc:
        raise WindowNotFoundError("Invalid window id.") from exc

    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _configure_user32(user32, wintypes)
    if not user32.IsWindow(handle):
        raise WindowNotFoundError("Window is no longer open.")

    title = _window_title(user32, handle)
    process_id = _window_process_id(user32, handle)
    process_name, executable_path = _process_identity(process_id)
    active_handle = int(user32.GetForegroundWindow() or 0)

    return DesktopWindow(
        id=str(handle),
        handle=handle,
        title=title or "(sem titulo)",
        process_id=process_id,
        process_name=process_name,
        executable_path=executable_path,
        class_name=_window_class_name(user32, handle),
        is_active=handle == active_handle,
        bounds=_window_bounds(user32, handle),
    )


def extract_window_context(window_id: str, max_chars: int = 12000) -> dict[str, Any]:
    window = get_window(window_id)
    text = ""
    truncated = False
    warning = None
    extraction_method = "metadata"

    try:
        text, truncated = _extract_text_with_uia(window.handle, max_chars=max_chars)
        if text:
            extraction_method = "uia"
        else:
            warning = "A janela nao expos texto via acessibilidade."
    except Exception as exc:
        warning = f"Nao consegui ler texto via acessibilidade: {exc}"

    context_prompt = build_context_prompt(
        window=window,
        text=text,
        extraction_method=extraction_method,
        warning=warning,
        max_chars=max_chars,
    )
    return {
        "window": window.to_dict(),
        "text": text,
        "extraction_method": extraction_method,
        "warning": warning,
        "truncated": truncated,
        "context_prompt": context_prompt,
    }


def build_context_prompt(
    *,
    window: DesktopWindow,
    text: str,
    extraction_method: str,
    warning: str | None = None,
    max_chars: int = 12000,
) -> str:
    title = window.title.strip() or "(sem titulo)"
    process = window.process_name.strip() or "processo desconhecido"
    executable = window.executable_path.strip()
    accessible_text = normalize_context_text(text, max_chars=max_chars)

    parts = [
        "Contexto da janela escolhida pelo usuario.",
        f"Titulo: {title}",
        f"Processo: {process} (PID {window.process_id})",
    ]
    if executable:
        parts.append(f"Executavel: {executable}")
    parts.append(f"Metodo de leitura: {extraction_method}")
    if warning:
        parts.append(f"Aviso: {warning}")
    if accessible_text:
        parts.append("Texto acessivel da janela:")
        parts.append(accessible_text)
    else:
        parts.append("Texto acessivel da janela: nao disponivel.")
    return "\n".join(parts)


def normalize_context_text(text: str, max_chars: int = 12000) -> str:
    lines = []
    seen = set()
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    normalized = "\n".join(lines).strip()
    if len(normalized) <= max_chars:
        return normalized
    suffix = "\n...[contexto truncado]"
    if max_chars <= len(suffix):
        return suffix[-max_chars:]
    return normalized[: max_chars - len(suffix)].rstrip() + suffix


def _should_include_window(title: str) -> bool:
    clean = title.strip()
    if len(clean) < 2:
        return False
    ignored_titles = {
        "Program Manager",
        "Windows Input Experience",
        "Microsoft Text Input Application",
    }
    return clean not in ignored_titles


def _window_title(user32: Any, hwnd: int) -> str:
    import ctypes

    length = int(user32.GetWindowTextLengthW(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def _window_class_name(user32: Any, hwnd: int) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _window_process_id(user32: Any, hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes

    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


def _window_bounds(user32: Any, hwnd: int) -> dict[str, int]:
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return {}
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
        "width": max(0, int(rect.right - rect.left)),
        "height": max(0, int(rect.bottom - rect.top)),
    }


def _process_identity(process_id: int) -> tuple[str, str]:
    if process_id <= 0 or not is_supported_platform():
        return "", ""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return "", ""

    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        executable_path = buffer.value.strip() if ok else ""
    finally:
        kernel32.CloseHandle(handle)

    process_name = Path(executable_path).name if executable_path else ""
    return process_name, executable_path


def _configure_user32(user32: Any, wintypes: Any) -> None:
    import ctypes

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetWindowRect.restype = wintypes.BOOL


def _extract_text_with_uia(handle: int, max_chars: int) -> tuple[str, bool]:
    script = r'''
Add-Type -AssemblyName UIAutomationClient
$handleValue = [Int64]$env:ASSISTANT_WINDOW_HANDLE
$limit = [Math]::Max(1000, [Int32]$env:ASSISTANT_CONTEXT_MAX_CHARS)
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handleValue)
$items = New-Object System.Collections.Generic.List[string]

function Add-ContextText([string]$value) {
  if ([string]::IsNullOrWhiteSpace($value)) { return }
  $clean = ($value -replace "\r\n", "`n" -replace "\r", "`n").Trim()
  if ($clean.Length -gt 0) { $items.Add($clean) }
}

function Walk-Element($element, [int]$depth) {
  if ($null -eq $element -or $depth -gt 5 -or $items.Count -ge 160) { return }
  try {
    Add-ContextText $element.Current.Name

    $valuePattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
      Add-ContextText $valuePattern.Current.Value
    }

    $textPattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$textPattern)) {
      Add-ContextText $textPattern.DocumentRange.GetText($limit)
    }

    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $child = $walker.GetFirstChild($element)
    while ($null -ne $child -and $items.Count -lt 160) {
      Walk-Element $child ($depth + 1)
      $child = $walker.GetNextSibling($child)
    }
  } catch {}
}

Walk-Element $root 0
$seen = @{}
$lines = New-Object System.Collections.Generic.List[string]
foreach ($item in $items) {
  foreach ($line in ($item -split "`n")) {
    $clean = ($line -replace "\s+", " ").Trim()
    if ($clean.Length -eq 0) { continue }
    $key = $clean.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    $lines.Add($clean)
  }
}
$text = ($lines -join "`n")
$truncated = $false
if ($text.Length -gt $limit) {
  $text = $text.Substring(0, $limit)
  $truncated = $true
}
[PSCustomObject]@{
  text = $text
  truncated = $truncated
} | ConvertTo-Json -Compress
'''
    env = {
        **os.environ,
        "ASSISTANT_WINDOW_HANDLE": str(handle),
        "ASSISTANT_CONTEXT_MAX_CHARS": str(max_chars),
    }
    result = subprocess.run(
        [
            "powershell",
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=6,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "PowerShell returned an error.").strip()
        raise RuntimeError(detail[:500])

    output = result.stdout.strip()
    if not output:
        return "", False
    data = json.loads(output)
    text = normalize_context_text(str(data.get("text") or ""), max_chars=max_chars)
    return text, bool(data.get("truncated")) or len(text) >= max_chars
