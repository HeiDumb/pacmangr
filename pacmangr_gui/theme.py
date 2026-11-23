"""Colour schemes, matugen integration and GTK styling."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .settings import SETTINGS  # noqa: E402

ACCENT_PRESETS = {
    "gold": {"primary": "ffbe0b", "on_primary": "211a00"},
    "cyan": {"primary": "00e5ff", "on_primary": "00363d"},
    "purple": {"primary": "bd93f9", "on_primary": "28164b"},
    "green": {"primary": "50fa7b", "on_primary": "003914"},
    "coral": {"primary": "ff79c6", "on_primary": "49002a"},
}

SCHEME_PATH = Path.home() / ".local/state/heilios/scheme.json"
CAELESTIA_SCHEME_PATH = Path.home() / ".local/state/caelestia/scheme.json"
PREVIEW_SCHEME_PATH = CAELESTIA_SCHEME_PATH.parent / "wallpaper/preview-scheme.json"
MATUGEN_SCHEME_PATH = Path.home() / ".config/pacmangr/matugen_scheme.json"
CURRENT_CSS_PROVIDER: Gtk.CssProvider | None = None

_DEFAULT_PALETTE = {
    "background": "0c0e12",
    "surface": "161a1f",
    "surface_high": "21262d",
    "text": "e1e6ef",
    "muted": "a6abb4",
    "outline": "434850",
    "primary": "adc9ea",
    "on_primary": "26425e",
    "success": "b5ccba",
    "error": "fa746f",
}

_SCHEME_ROLES = {
    "background": ("background",),
    "surface": ("surfaceContainer", "surface_container", "surface"),
    "surface_high": ("surfaceContainerHighest", "surface_container_highest", "surface_high"),
    "text": ("onSurface", "on_surface", "text"),
    "muted": ("onSurfaceVariant", "on_surface_variant", "muted"),
    "outline": ("outlineVariant", "outline_variant", "outline"),
    "primary": ("primary",),
    "on_primary": ("onPrimary", "on_primary"),
    "success": ("success",),
    "error": ("error",),
}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _normalise_hex(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    return value if len(value) == 6 else ""


def _scheme_to_palette(scheme: dict) -> dict[str, str]:
    palette = dict(_DEFAULT_PALETTE)
    for key, roles in _SCHEME_ROLES.items():
        for role in roles:
            colour = _normalise_hex(scheme.get(role))
            if colour:
                palette[key] = colour
                break
    return palette


def _scheme_from_colours(colours: dict) -> dict:
    if not isinstance(colours, dict):
        return {}
    scheme: dict = {}
    for key, roles in _SCHEME_ROLES.items():
        for role in roles:
            if role in colours:
                scheme[key] = colours[role]
                break
    return scheme


def _heilios_scheme(path: Path | str = SCHEME_PATH) -> dict:
    data = _read_json(Path(path))
    colours = data.get("colours", data.get("colors", data))
    return _scheme_from_colours(colours)


def _matugen_scheme_path() -> Path:
    return Path.home() / ".config/pacmangr/matugen_scheme.json"


def palette(
    scheme_path: Path | str | None = None,
    *,
    scheme_colours: dict | None = None,
) -> dict[str, str]:
    """Resolve the active palette from matugen, Heilios or a fixed accent."""
    mode = SETTINGS.get("theme_mode", "auto")
    scheme: dict = {}

    if mode == "accent":
        scheme = {}
    elif scheme_colours is not None:
        scheme = _scheme_from_colours(scheme_colours)
    elif mode == "matugen":
        scheme = _heilios_scheme(_matugen_scheme_path()) or _heilios_scheme(SCHEME_PATH)
    else:
        source = scheme_path or SETTINGS.get("scheme_path", SCHEME_PATH)
        scheme = _heilios_scheme(source) or _heilios_scheme(SCHEME_PATH)
        if not scheme:
            scheme = _heilios_scheme(_matugen_scheme_path())

    result = _scheme_to_palette(scheme)

    accent = SETTINGS.get("theme_accent", "auto")
    if mode == "accent" and accent == "auto":
        accent = "gold"
    if accent in ACCENT_PRESETS:
        result["primary"] = ACCENT_PRESETS[accent]["primary"]
        result["on_primary"] = ACCENT_PRESETS[accent]["on_primary"]
    return result


def _flatten_matugen_colours(payload: dict) -> dict[str, str]:
    raw = payload.get("colors", payload.get("colours", payload))
    if not isinstance(raw, dict):
        return {}
    flat: dict[str, str] = {}
    for key, value in raw.items():
        normalised = str(key).replace("-", "_")
        if isinstance(value, dict):
            colour = value.get("hex") or value.get("value") or value.get("color")
        else:
            colour = value
        hex_value = _normalise_hex(colour)
        if hex_value:
            flat[normalised] = hex_value
    return flat


def _parse_json_output(text: str) -> dict | None:
    """Parse matugen output, tolerating leading log lines."""
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except (ValueError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start:end + 1])
            return payload if isinstance(payload, dict) else None
        except (ValueError, TypeError):
            pass
    return None


def _matugen_scheme(payload: dict) -> dict:
    flat = _flatten_matugen_colours(payload)
    aliases = {
        "background": ("background", "surface"),
        "surface": ("surface_container", "surfaceContainer", "surface"),
        "surface_high": ("surface_container_highest", "surfaceContainerHighest", "surface_container_high"),
        "text": ("on_surface", "onSurface", "foreground"),
        "muted": ("on_surface_variant", "onSurfaceVariant", "muted"),
        "outline": ("outline_variant", "outlineVariant", "outline"),
        "primary": ("primary",),
        "on_primary": ("on_primary", "onPrimary"),
        "success": ("success", "tertiary"),
        "error": ("error",),
    }
    scheme: dict[str, str] = {}
    for key, candidates in aliases.items():
        for candidate in candidates:
            if candidate in flat:
                scheme[key] = flat[candidate]
                break
    return scheme


def _write_scheme(scheme: dict) -> Path:
    path = _matugen_scheme_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scheme, indent=2), encoding="utf-8")
    return path


def _fallback_scheme(message: str) -> tuple[bool, str]:
    """Use Heilios/accent colours when matugen cannot generate a palette."""
    scheme = _heilios_scheme(SETTINGS.get("scheme_path", SCHEME_PATH)) or _heilios_scheme(SCHEME_PATH)
    if scheme:
        _write_scheme(scheme)
        install_css(_scheme_to_palette(scheme))
        return False, f"{message} Fell back to the detected Heilios scheme."
    install_css(palette())
    return False, f"{message} No fallback scheme found; using built-in colours."


def apply_matugen_from_wallpaper(
    wallpaper: Path | str,
    scheme_type: str = "tonal-spot",
    matugen_bin: str = "matugen",
) -> tuple[bool, str]:
    """Generate a Material You palette from an image and install it.

    Returns ``(success, human_readable_status)``.  Missing binaries, missing
    images and malformed output are handled without raising.
    """
    image = Path(wallpaper).expanduser()
    if not image.is_file():
        return _fallback_scheme(f"Wallpaper not found: {image}.")

    binary = str(matugen_bin or "matugen").strip()
    resolved = shutil.which(binary)
    if not resolved:
        candidate = Path(binary).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            resolved = str(candidate)
    if not resolved:
        return _fallback_scheme("Matugen is not installed or not executable.")

    command = [resolved, "image", str(image), "-t", str(scheme_type or "tonal-spot"), "--json"]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _fallback_scheme(f"Matugen failed to run: {exc}")

    payload = _parse_json_output(process.stdout)

    if payload is None:
        for cached in (
            Path.home() / ".cache/matugen/colors.json",
            Path.home() / ".config/matugen/colors.json",
            Path.home() / ".local/state/matugen/colors.json",
        ):
            data = _read_json(cached)
            if data:
                payload = data
                break

    if payload is None:
        detail = (process.stderr or process.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "no JSON output"
        return _fallback_scheme(f"Matugen did not return colours: {tail}")

    scheme = _matugen_scheme(payload)
    if not scheme.get("primary"):
        return _fallback_scheme("Matugen output did not contain usable colour roles.")

    _write_scheme(scheme)
    install_css(_scheme_to_palette(scheme))
    return True, f"Applied the matugen palette generated from {image.name}."


def install_css(palette_dict: dict[str, str] | None = None, compact: bool | None = None) -> None:
    """Install (or replace) the application-wide colour provider."""
    global CURRENT_CSS_PROVIDER
    c = palette_dict or palette()
    setting_density = SETTINGS.get("row_density", "normal")
    is_compact = compact if compact is not None else bool(SETTINGS.get("compact_rows", False))
    if setting_density == "compact":
        is_compact = True
    row_margin_v = "1px" if is_compact else "3px"
    row_pad_v = "6px" if is_compact else "10px"
    try:
        scale = float(SETTINGS.get("font_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.8, min(1.6, scale))
    base_font = int(round(14 * scale))

    css = f"""
    window {{
        background: alpha(#{c['background']}, 0.97);
        color: #{c['text']};
        font-size: {base_font}px;
    }}
    headerbar {{
        background: alpha(#{c['surface']}, 0.94);
        border-bottom: 1px solid alpha(#{c['outline']}, 0.75);
        padding: 6px 12px;
    }}
    .header-title-widget {{ margin: 2px 8px; }}
    .brand-name {{
        color: #{c['text']};
        font-size: {int(round(17 * scale))}px;
        font-weight: 800;
        letter-spacing: 0.4px;
    }}
    .header-divider {{
        background: alpha(#{c['outline']}, 0.8);
        min-width: 1px;
        margin: 4px 0;
    }}
    .header-view-title {{
        color: #{c['text']};
        font-size: {int(round(15 * scale))}px;
        font-weight: 750;
    }}
    .header-view-subtitle {{
        color: #{c['muted']};
        font-size: {int(round(11 * scale))}px;
    }}
    .title-label {{
        font-size: {int(round(21 * scale))}px;
        font-weight: 800;
    }}
    .brand-icon {{ color: #{c['primary']}; }}
    .subtitle-label, .muted {{ color: #{c['muted']}; }}
    .search-card {{
        background-color: alpha(#{c['surface']}, 0.72);
        background-image: linear-gradient(150deg, alpha(#{c['primary']}, 0.07), alpha(#{c['surface']}, 0.82) 60%);
        border: 1px solid alpha(#{c['outline']}, 0.45);
        border-radius: 22px;
    }}
    .view-toolbar {{ padding: 0; }}
    .detail-card, .status-card {{
        background: alpha(#{c['surface']}, 0.92);
        border: 1px solid alpha(#{c['outline']}, 0.75);
        border-radius: 16px;
    }}
    .hero-card {{
        background-image: linear-gradient(115deg, alpha(#{c['primary']}, 0.16), alpha(#{c['surface']}, 0.96) 52%);
        border-color: alpha(#{c['primary']}, 0.45);
    }}
    .search-control {{
        background-color: #{c['surface_high']};
        background-image: linear-gradient(180deg, #{c['surface_high']}, #{c['surface']});
        border: 1px solid alpha(#{c['outline']}, 0.95);
        border-radius: 18px;
        padding: 4px;
        min-height: 48px;
    }}
    .search-control:focus-within {{
        border-color: alpha(#{c['primary']}, 0.82);
        box-shadow: 0 0 0 2px alpha(#{c['primary']}, 0.12);
    }}
    .section-label {{
        color: #{c['muted']};
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.6px;
    }}
    searchentry {{
        min-height: 48px;
        border-radius: 999px;
        background-color: alpha(#{c['surface_high']}, 0.72);
        background-image: linear-gradient(180deg, alpha(#{c['surface_high']}, 0.85), alpha(#{c['surface']}, 0.92));
        border: 1px solid alpha(#{c['outline']}, 0.75);
        color: #{c['text']};
        font-size: 16px;
        padding: 0 18px;
    }}
    .search-control searchentry,
    .search-control searchentry entry,
    .search-control entry.search-field {{
        min-height: 42px;
        background-color: transparent;
        background-image: none;
        border: none;
        border-radius: 12px;
        box-shadow: none;
        color: #{c['text']};
        padding: 0 10px;
    }}
    .search-control searchentry:focus-within,
    .search-control searchentry entry:focus {{
        background-color: transparent;
        background-image: none;
        border: none;
        box-shadow: none;
    }}
    dropdown.search-source,
    .search-control dropdown.search-source,
    .search-control dropdown.search-source button,
    .search-control dropdown.search-source button:hover,
    .search-control dropdown.search-source button:focus,
    .search-control dropdown.search-source button:checked {{
        min-height: 40px;
        padding: 0 12px;
        background: transparent;
        background-color: transparent;
        background-image: none;
        border: none;
        border-radius: 12px;
        box-shadow: none;
        color: #{c['text']};
    }}
    .search-control dropdown.search-source button:hover {{
        background: alpha(#{c['primary']}, 0.10);
    }}
    .search-control entry.search-field,
    .search-control entry.search-field:focus,
    .search-control entry.search-field:focus-within {{
        background: transparent;
        background-color: transparent;
        background-image: none;
        border: none;
        box-shadow: none;
        outline: none;
        outline-color: transparent;
        color: #{c['text']};
    }}
    .search-control searchentry:focus,
    .search-control searchentry:focus-within,
    .search-control searchentry entry:focus {{
        background-color: transparent;
        background-image: none;
        border: none;
        box-shadow: none;
        outline: none;
    }}
    searchentry:focus {{
        border-color: #{c['primary']};
        box-shadow: 0 0 0 3px alpha(#{c['primary']}, 0.22);
    }}
    button {{
        border-radius: 10px;
        min-height: 36px;
        padding: 5px 14px;
        color: #{c['text']};
    }}
    button:hover {{ background: alpha(#{c['surface_high']}, 0.9); }}
    button.flat {{ background: transparent; }}
    .search-control searchentry button,
    .search-control searchentry button:hover,
    .search-control searchentry button:focus {{
        min-width: 28px;
        min-height: 28px;
        padding: 0;
        border: 0;
        border-radius: 999px;
        background: transparent;
        box-shadow: none;
        color: #{c['muted']};
    }}
    button.suggested-action {{
        background: #{c['primary']};
        color: #{c['on_primary']};
        font-weight: 750;
        border-color: transparent;
    }}
    button.suggested-action:hover {{ background: alpha(#{c['primary']}, 0.86); }}
    button.search-button {{
        min-width: 48px;
        min-height: 48px;
        padding: 0 16px;
        border-radius: 999px;
        border: 1px solid alpha(#{c['primary']}, 0.85);
        background-color: #{c['primary']};
        background-image: linear-gradient(135deg, alpha(#{c['primary']}, 0.98), alpha(#{c['primary']}, 0.72));
        color: #{c['on_primary']};
        font-weight: 800;
        font-size: 17px;
    }}
    button.search-button:hover {{
        background-image: linear-gradient(135deg, alpha(#{c['primary']}, 1.0), alpha(#{c['primary']}, 0.82));
        box-shadow: 0 2px 8px alpha(#{c['primary']}, 0.30);
    }}
    button.search-button.browse-search-button {{
        min-width: 42px;
        min-height: 42px;
        padding: 0;
        border-radius: 12px;
    }}
    button.open-search-button {{
        min-width: 42px;
        min-height: 42px;
        padding: 0;
        border-radius: 12px;
        background: alpha(#{c['surface_high']}, 0.72);
        border: 1px solid alpha(#{c['outline']}, 0.55);
    }}
    button.pill-button {{
        min-width: 36px;
        min-height: 40px;
        border-radius: 999px;
        padding: 4px 12px;
        background: alpha(#{c['surface_high']}, 0.75);
        border: 1px solid alpha(#{c['outline']}, 0.7);
        color: #{c['muted']};
    }}
    button.pill-button:hover {{ color: #{c['primary']}; border-color: #{c['primary']}; }}
    button.pill-button.active {{ color: #{c['primary']}; border-color: #{c['primary']}; }}
    dropdown.filter-inactive {{ color: #{c['muted']}; opacity: 0.85; }}
    button.tab-btn {{
        border-radius: 10px;
        padding: 5px 12px;
        font-weight: 650;
        border: 1px solid alpha(#{c['outline']}, 0.6);
        background: alpha(#{c['surface_high']}, 0.58);
        color: #{c['muted']};
    }}
    button.tab-btn:checked, button.tab-btn.active {{
        background: alpha(#{c['primary']}, 0.18);
        color: #{c['primary']};
        border-color: alpha(#{c['primary']}, 0.7);
    }}
    button.link-button {{ color: #{c['primary']}; text-decoration: underline; }}
    list {{ background: transparent; }}
    row.package-row {{
        background: alpha(#{c['surface_high']}, 0.52);
        border: 1px solid transparent;
        border-left: 3px solid transparent;
        border-radius: 12px;
        margin: {row_margin_v} 8px;
    }}
    row.package-row:hover {{
        background: alpha(#{c['primary']}, 0.12);
        border-color: alpha(#{c['primary']}, 0.26);
    }}
    row.package-row:selected {{
        background: alpha(#{c['primary']}, 0.17);
        border-color: alpha(#{c['primary']}, 0.35);
        border-left-color: #{c['primary']};
    }}
    .package-row-box {{ padding: {row_pad_v} 12px; }}
    .package-row-box.compact {{ padding: 5px 12px; }}
    .package-icon {{ color: #{c['primary']}; }}
    .package-name {{ font-weight: 750; font-size: 15px; color: #{c['text']}; }}
    .repo-meta {{ color: #{c['muted']}; font-size: 12px; font-weight: 600; }}
    row.github-row {{ background: alpha(#{c['surface_high']}, 0.72); }}
    row.github-row:hover {{ background: alpha(#{c['primary']}, 0.15); }}
    .pill {{
        background: alpha(#{c['primary']}, 0.16);
        color: #{c['primary']};
        border-radius: 999px;
        padding: 3px 9px;
        font-size: 11px;
        font-weight: 700;
    }}
    .installed-pill {{ background: alpha(#{c['success']}, 0.18); color: #{c['success']}; }}
    .orphan-pill {{ background: alpha(#{c['error']}, 0.22); color: #{c['error']}; }}
    .explicit-pill {{ background: alpha(#{c['primary']}, 0.22); color: #{c['primary']}; }}
    .star-pill {{ background: alpha(#{c['primary']}, 0.20); color: #{c['primary']}; }}
    .status-pill {{ background: alpha(#{c['success']}, 0.18); color: #{c['success']}; }}
    .danger {{ color: #{c['error']}; }}
    button.danger {{
        background: alpha(#{c['error']}, 0.18);
        color: #{c['error']};
        border-color: alpha(#{c['error']}, 0.5);
    }}
    button.danger:hover {{ background: alpha(#{c['error']}, 0.32); }}
    progressbar trough {{
        min-height: 8px;
        border-radius: 999px;
        background: alpha(#{c['surface_high']}, 0.86);
        border: 1px solid alpha(#{c['outline']}, 0.72);
    }}
    progressbar progress {{
        min-height: 8px;
        border-radius: 999px;
        background: #{c['primary']};
    }}
    progressbar text {{ color: #{c['text']}; font-size: 11px; font-weight: 650; }}
    .detail-meta {{
        background: alpha(#{c['surface_high']}, 0.55);
        border: 1px solid alpha(#{c['outline']}, 0.5);
        border-radius: 12px;
        padding: 8px 10px;
        font-size: 12px;
    }}
    .detail-actions {{
        padding: 0;
    }}
    textview, textview text {{
        background: transparent;
        color: #{c['text']};
        font-family: monospace;
        font-size: 12px;
    }}
    textview.readme-text, textview.readme-text text {{
        color: #{c['text']};
        font-family: sans-serif;
        font-size: 13px;
    }}
    scrollbar {{
        background: transparent;
    }}
    scrollbar slider {{
        background: alpha(#{c['outline']}, 0.75);
        border-radius: 999px;
        min-width: 6px;
    }}

    /* Navigation rail: quiet by default, obvious when you look for it. */
    .nav-rail {{
        background: alpha(#{c['surface']}, 0.58);
        border-right: 1px solid alpha(#{c['outline']}, 0.55);
        min-width: 58px;
    }}
    .rail-separator {{ background: alpha(#{c['outline']}, 0.55); }}
    button.nav-icon {{
        min-width: 44px;
        min-height: 44px;
        padding: 0;
        border-radius: 12px;
        border-left: 3px solid transparent;
        background: transparent;
        color: #{c['muted']};
    }}
    button.nav-icon:hover {{
        background: alpha(#{c['primary']}, 0.10);
        color: #{c['text']};
    }}
    button.nav-icon.active {{
        background: alpha(#{c['primary']}, 0.16);
        border-left-color: #{c['primary']};
        color: #{c['primary']};
    }}
    button.nav-icon.active .nav-icon-image {{ color: #{c['primary']}; }}
    .nav-badge {{
        background: #{c['primary']};
        color: #{c['on_primary']};
        border-radius: 999px;
        padding: 0 5px;
        font-size: 10px;
        font-weight: 800;
        min-width: 16px;
    }}
    button.nav-icon.has-badge .nav-badge {{ background: #{c['error']}; color: #{c['background']}; }}
    button.rail-strip {{
        min-width: 10px;
        min-height: 0;
        padding: 0;
        border-radius: 0;
        border: 0;
        border-right: 1px solid alpha(#{c['outline']}, 0.45);
        background: alpha(#{c['surface']}, 0.42);
    }}
    button.rail-strip:hover {{ background: alpha(#{c['primary']}, 0.28); }}
    .empty-state {{ color: #{c['muted']}; padding: 32px 18px; }}
    .empty-state-title {{ font-size: 16px; font-weight: 700; color: #{c['text']}; }}
    .settings-page, .settings-sidebar {{ background: alpha(#{c['surface']}, 0.42); }}
    .app-root {{ background: transparent; }}
    .status-card {{ padding: 2px 0; }}
    button.danger {{ font-weight: 650; }}
    """

    display = Gdk.Display.get_default()
    if display:
        if CURRENT_CSS_PROVIDER:
            try:
                Gtk.StyleContext.remove_provider_for_display(display, CURRENT_CSS_PROVIDER)
            except Exception:
                pass
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        CURRENT_CSS_PROVIDER = provider


def hex_rgb(value: str, fallback: str = "ffffff") -> tuple[float, float, float]:
    """Convert a CSS-style hex colour to Cairo's zero-to-one RGB tuple."""
    clean = value.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(channel * 2 for channel in clean)
    if len(clean) != 6:
        clean = fallback
    try:
        channels = tuple(int(clean[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        channels = tuple(int(fallback[index:index + 2], 16) / 255 for index in (0, 2, 4))
    return channels


def pacman_frame(phase: float, width: float) -> tuple[float, tuple[float, ...]]:
    """Return mouth angle and moving pellet positions for one animation frame."""
    mouth = math.radians(8 + 22 * (0.5 + 0.5 * math.sin(phase * 0.9)))
    track_start = 31.0
    pellet_gap = 18.0
    offset = (phase * 2.8) % pellet_gap
    pellet_x = track_start + pellet_gap - offset
    positions: list[float] = []
    while pellet_x < max(track_start + pellet_gap, width - 4):
        positions.append(pellet_x)
        pellet_x += pellet_gap
    return mouth, tuple(positions)


class PacmangrLogo(Gtk.DrawingArea):
    """Compact themed Pac-Man mark for the application header."""

    def __init__(self, colours: dict[str, str]) -> None:
        super().__init__()
        self._body = hex_rgb(colours["primary"])
        self._eye = hex_rgb(colours["on_primary"])
        self._pellet = hex_rgb(colours["success"])
        self.set_content_width(30)
        self.set_content_height(30)
        self.set_size_request(30, 30)
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, height: int) -> None:
        center_x, center_y = 13.5, height / 2
        radius = 12.5
        mouth = math.radians(24)
        context.set_source_rgb(*self._body)
        context.move_to(center_x, center_y)
        context.arc(center_x, center_y, radius, mouth, math.tau - mouth)
        context.close_path()
        context.fill()
        context.set_source_rgb(*self._eye)
        context.arc(center_x + 1.0, center_y - 5.5, 1.5, 0, math.tau)
        context.fill()
        context.set_source_rgb(*self._pellet)
        context.arc(width - 3.0, center_y, 2.2, 0, math.tau)
        context.fill()
