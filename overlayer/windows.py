"""Small, typed Win32 bridge.

No hooks or injection. Other windows are only listed, measured, and identified
by process id and executable file name.
"""

import ctypes
from ctypes import wintypes as W
import os

if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel32.OpenProcess.restype = W.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        W.HANDLE,
        W.DWORD,
        W.LPWSTR,
        ctypes.POINTER(W.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = W.BOOL
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    kernel32.CloseHandle.restype = W.BOOL
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmGetWindowAttribute.argtypes = [
        W.HWND,
        W.DWORD,
        ctypes.c_void_p,
        W.DWORD,
    ]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    user32.GetKeyboardLayout.argtypes = [W.DWORD]
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.MapVirtualKeyExW.argtypes = [W.UINT, W.UINT, ctypes.c_void_p]
    user32.MapVirtualKeyExW.restype = W.UINT
    user32.ToUnicodeEx.argtypes = [
        W.UINT,
        W.UINT,
        ctypes.POINTER(ctypes.c_ubyte),
        W.LPWSTR,
        ctypes.c_int,
        W.UINT,
        ctypes.c_void_p,
    ]
    user32.ToUnicodeEx.restype = ctypes.c_int
    enum_proc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, W.LPARAM]
    user32.EnumWindows.restype = W.BOOL
    user32.IsWindowVisible.argtypes = [W.HWND]
    user32.IsWindowVisible.restype = W.BOOL
    user32.IsWindow.argtypes = [W.HWND]
    user32.IsWindow.restype = W.BOOL
    user32.IsIconic.argtypes = [W.HWND]
    user32.IsIconic.restype = W.BOOL
    user32.GetWindowTextLengthW.argtypes = [W.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
    user32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    user32.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
    user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
    user32.GetForegroundWindow.restype = W.HWND
    user32.RegisterHotKey.argtypes = [W.HWND, ctypes.c_int, W.UINT, W.UINT]
    user32.RegisterHotKey.restype = W.BOOL
    user32.UnregisterHotKey.argtypes = [W.HWND, ctypes.c_int]
    user32.RegisterWindowMessageW.argtypes = [W.LPCWSTR]
    user32.RegisterWindowMessageW.restype = W.UINT
    user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user32.PostMessageW.restype = W.BOOL
    user32.AllowSetForegroundWindow.argtypes = [W.DWORD]
    user32.AllowSetForegroundWindow.restype = W.BOOL
    SHOW_CONTROLS_MESSAGE = user32.RegisterWindowMessageW(
        "BogdanDemchenko.OverLayer.ShowControls"
    )
    get_style = user32.GetWindowLongPtrW
    get_style.argtypes = [W.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style = user32.SetWindowLongPtrW
    set_style.argtypes = [W.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t


def window_pid(hwnd):
    pid = W.DWORD()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_name(pid):
    """Executable file name of a process, or "" when Windows denies the query."""
    if not pid:
        return ""
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = W.DWORD(520)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def is_cloaked(hwnd):
    """True for windows Windows keeps alive but hides (suspended UWP apps)."""
    try:
        value = W.DWORD()
        if (
            dwmapi.DwmGetWindowAttribute(
                hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)
            )
            == 0
        ):
            return bool(value.value)
    except (OSError, NameError):
        pass
    return False


def windows():
    """Visible, titled top-level windows of other processes: (hwnd, title, exe)."""
    result = []
    names = {}

    @enum_proc
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                pid = window_pid(hwnd)
                if pid != os.getpid() and not is_cloaked(hwnd):
                    text = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, text, length + 1)
                    if pid not in names:
                        names[pid] = process_name(pid)
                    result.append((int(hwnd), text.value, names[pid]))
        return True

    user32.EnumWindows(visit, 0)
    return sorted(result, key=lambda item: item[1].lower())


def host_active(target):
    """True when the followed window, or another window of its app, has focus.

    Tool palettes, inspectors and file dialogs are separate top-level windows of
    the same process; guides should stay visible while they are in front.
    """
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    if foreground == target:
        return True
    pid = window_pid(target)
    return bool(pid) and window_pid(foreground) == pid


def altgr_conflict(vk):
    """True if Ctrl+Alt+key types a character on the active keyboard layout.

    Layouts with an AltGr key (Polish, German, ...) report AltGr as Ctrl+Alt,
    so a global Ctrl+Alt+letter shortcut would swallow that letter.
    """
    try:
        layout = user32.GetKeyboardLayout(0)
        scan = user32.MapVirtualKeyExW(vk, 0, layout)
        state = (ctypes.c_ubyte * 256)()
        state[0x11] = state[0x12] = state[0xA2] = state[0xA5] = 0x80
        buffer = ctypes.create_unicode_buffer(8)
        count = user32.ToUnicodeEx(vk, scan, state, buffer, 8, 4, layout)
    except (OSError, ValueError):
        return False
    return count < 0 or (count > 0 and any(ord(ch) >= 0x20 for ch in buffer.value[:count]))


def client_rect(hwnd):
    if (
        not user32.IsWindow(hwnd)
        or not user32.IsWindowVisible(hwnd)
        or user32.IsIconic(hwnd)
    ):
        return None
    rect, point = W.RECT(), W.POINT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(
        hwnd, ctypes.byref(point)
    ):
        return None
    return point.x, point.y, rect.right, rect.bottom


def set_click_through(hwnd, locked):
    style = get_style(hwnd, -20)
    mask = 0x20 | 0x80000 | 0x08000000  # transparent, layered, no activate
    set_style(
        hwnd, -20, style | mask if locked else (style | 0x80000) & ~0x20 & ~0x08000000
    )


def own_foreground():
    hwnd = user32.GetForegroundWindow()
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def request_existing_controls():
    """Wake the existing controller, including when its window is hidden."""
    result = []

    @enum_proc
    def visit(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            suffix = title.value.removeprefix("OverLayer ")
            if title.value.startswith("OverLayer ") and suffix[:1].isdigit():
                result.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, 0)
    if not result:
        return False
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(result[0], ctypes.byref(pid))
    user32.AllowSetForegroundWindow(pid.value)
    return bool(user32.PostMessageW(result[0], SHOW_CONTROLS_MESSAGE, 0, 0))
