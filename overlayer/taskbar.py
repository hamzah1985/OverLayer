"""Explicit Windows taskbar and relaunch identity for the control window."""

import ctypes
from ctypes import wintypes as W
from pathlib import Path
import subprocess
import sys
import uuid

APP_ID = "BogdanDemchenko.OverLayer"


class GUID(ctypes.Structure):
    _fields_ = [
        ("data1", W.DWORD),
        ("data2", W.WORD),
        ("data3", W.WORD),
        ("data4", ctypes.c_byte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", W.DWORD)]


class Value(ctypes.Union):
    _fields_ = [
        ("pointer", ctypes.c_void_p),
        ("storage", ctypes.c_byte * 16),
        ("alignment", ctypes.c_ulonglong),
    ]


class PropVariant(ctypes.Structure):
    _fields_ = [
        ("vt", W.WORD),
        ("reserved1", W.WORD),
        ("reserved2", W.WORD),
        ("reserved3", W.WORD),
        ("value", Value),
    ]


FORMAT = GUID.parse("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")
IID = GUID.parse("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
shell32.SHGetPropertyStoreForWindow.argtypes = [
    W.HWND,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
shell32.SHChangeNotify.argtypes = [
    ctypes.c_long,
    W.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
shell32.SHChangeNotify.restype = None
ole32.PropVariantClear.argtypes = [ctypes.POINTER(PropVariant)]
ole32.PropVariantClear.restype = ctypes.c_long


def check(hr):
    if hr < 0:
        raise OSError(f"Windows taskbar property error 0x{hr & 0xFFFFFFFF:08x}")


class WindowProperties:
    def __init__(self, hwnd):
        self.store = ctypes.c_void_p()
        check(
            shell32.SHGetPropertyStoreForWindow(
                hwnd, ctypes.byref(IID), ctypes.byref(self.store)
            )
        )
        self.table = ctypes.cast(
            self.store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents

    def call(self, index, *types):
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(
            self.table[index]
        )

    def set(self, pid, text=None):
        key = PropertyKey(FORMAT, pid)
        variant = PropVariant()
        if text is not None:
            buffer = ctypes.create_unicode_buffer(text)
            variant.vt = 31  # VT_LPWSTR; SetValue copies the borrowed string.
            variant.value.pointer = ctypes.cast(buffer, ctypes.c_void_p).value
        check(
            self.call(6, ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant))(
                self.store, ctypes.byref(key), ctypes.byref(variant)
            )
        )

    def get(self, pid):
        key = PropertyKey(FORMAT, pid)
        variant = PropVariant()
        check(
            self.call(5, ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant))(
                self.store, ctypes.byref(key), ctypes.byref(variant)
            )
        )
        try:
            return (
                ctypes.wstring_at(variant.value.pointer) if variant.vt == 31 else None
            )
        finally:
            ole32.PropVariantClear(ctypes.byref(variant))

    def close(self):
        if self.store:
            self.call(2)(self.store)
            self.store = ctypes.c_void_p()


def configure(hwnd):
    frozen = getattr(sys, "frozen", False)
    root = (
        Path(sys.executable).parent if frozen else Path(__file__).resolve().parents[1]
    )
    icon = root / "OverLayer.ico" if frozen else root / "assets" / "overlayer.ico"
    if not icon.is_file():
        raise FileNotFoundError(f"Taskbar icon missing: {icon}")
    command = [sys.executable] if frozen else [sys.executable, str(root / "run.py")]
    properties = WindowProperties(hwnd)
    try:
        properties.set(2, subprocess.list2cmdline(command))
        properties.set(3, str(icon) + ",0")
        properties.set(4, "OverLayer")
        properties.set(5, APP_ID)
    finally:
        properties.close()
    # Notify Explorer about this app only; no Explorer restart or cache deletion.
    for path in (icon, Path(sys.executable)) if frozen else (icon,):
        buffer = ctypes.create_unicode_buffer(str(path))
        shell32.SHChangeNotify(
            0x2000, 0x1005, ctypes.cast(buffer, ctypes.c_void_p), None
        )


def clear(hwnd):
    properties = WindowProperties(hwnd)
    try:
        for pid in (2, 3, 4, 5):
            properties.set(pid)
    finally:
        properties.close()
