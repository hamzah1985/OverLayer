"""Global shortcut definitions and parsing; independent of Qt and Win32."""

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8

# (RegisterHotKey id, setting name, label, default shortcut)
ACTIONS = (
    (1, "toggle_overlay", "Show / hide guides", "Ctrl+Alt+O"),
    (2, "toggle_lock", "Lock / unlock", "Ctrl+Alt+L"),
    (3, "toggle_panel", "Show / hide controls", "Ctrl+Alt+P"),
    (4, "draw_area", "Draw viewport area", "Ctrl+Alt+A"),
    (5, "quit", "Quit", "Ctrl+Alt+Q"),
    (6, "hide_overlay", "Hide guides immediately", "Ctrl+Alt+H"),
    (7, "next_preset", "Next preset", "Ctrl+Alt+PgDown"),
    (8, "prev_preset", "Previous preset", "Ctrl+Alt+PgUp"),
)
LABELS = {name: label for _, name, label, _ in ACTIONS}
DEFAULT_HOTKEYS = {name: default for _, name, _, default in ACTIONS}

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "meta": MOD_WIN,
}
_ORDER = (("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN))


def _key_table():
    table = {}
    for code in range(ord("A"), ord("Z") + 1):
        table[chr(code).lower()] = (code, chr(code))
    for code in range(ord("0"), ord("9") + 1):
        table[chr(code)] = (code, chr(code))
    for n in range(1, 13):
        table[f"f{n}"] = (0x70 + n - 1, f"F{n}")
    for names, vk, text in (
        (("pgup", "pageup"), 0x21, "PgUp"),
        (("pgdown", "pagedown", "pgdn"), 0x22, "PgDown"),
        (("end",), 0x23, "End"),
        (("home",), 0x24, "Home"),
        (("left",), 0x25, "Left"),
        (("up",), 0x26, "Up"),
        (("right",), 0x27, "Right"),
        (("down",), 0x28, "Down"),
        (("ins", "insert"), 0x2D, "Insert"),
        (("del", "delete"), 0x2E, "Delete"),
    ):
        for name in names:
            table[name] = (vk, text)
    return table


KEYS = _key_table()


def parse(spec):
    """Return (modifiers, virtual-key, canonical text), or None if unusable."""
    if not isinstance(spec, str) or len(spec) > 40:
        return None
    mods, key = 0, None
    for part in spec.split("+"):
        token = part.strip().lower()
        if token in _MODIFIERS:
            mods |= _MODIFIERS[token]
        elif key is None and token in KEYS:
            key = KEYS[token]
        else:
            return None
    if not mods or key is None:
        return None
    text = "+".join([name for name, bit in _ORDER if mods & bit] + [key[1]])
    return mods, key[0], text


def canonical(spec):
    parsed = parse(spec)
    return parsed[2] if parsed else None


def validated_hotkeys(value):
    """Full name -> shortcut mapping; unusable or duplicate entries fall back."""
    value = value if isinstance(value, dict) else {}
    result, used = {}, set()
    for _, name, _, default in ACTIONS:
        spec = canonical(value.get(name)) or default
        if spec in used:
            spec = default
        result[name] = spec
        used.add(spec)
    return result
