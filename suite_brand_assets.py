"""Approved suite logos; presentation only, with local assets and no network requests."""
from functools import lru_cache
from pathlib import Path
import base64
import html

ROOT = Path(__file__).resolve().parent

def brand_asset_path(name: str) -> Path:
    if name not in {"command_emblem_96", "command_emblem_256", "command_full", "investment_emblem_96", "investment_emblem_256", "investment_full"}:
        raise ValueError("Unknown approved brand asset")
    return ROOT / "static" / "branding" / (name + (".webp" if name.endswith("_full") else ".png"))

@lru_cache(maxsize=8)
def brand_data_uri(name: str) -> str:
    path = brand_asset_path(name)
    if not path.is_file():
        return ""
    mime = "image/webp" if path.suffix == ".webp" else "image/png"
    return "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")

def render_command_center_brand_link(target, label: str, url: str) -> bool:
    """Decorate the already-resolved navigation URL without changing its query or target."""
    logo = brand_data_uri("command_emblem_96")
    if not logo or not callable(getattr(target, "markdown", None)):
        return False
    target.markdown(
        '<a href="' + html.escape(url, quote=True) + '" target="_blank" rel="noopener noreferrer" '
        'style="display:flex;align-items:center;justify-content:center;gap:0.55rem;'
        'padding:0.5rem 0.65rem;border:1px solid #94a3b8;border-radius:0.5rem;'
        'text-decoration:none;color:inherit;min-height:44px;box-sizing:border-box">'
        '<img src="' + logo + '" alt="" aria-hidden="true" width="32" height="32" '
        'style="object-fit:contain;background:white;border-radius:6px;flex-shrink:0">'
        '<span>' + html.escape(label) + '</span></a>', unsafe_allow_html=True,
    )
    return True
