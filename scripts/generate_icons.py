"""Regenerate PWA + iOS home-screen icons from a single programmatic design.

Run when the icon design changes, or when a school's theme color changes;
commits the PNGs. Not a runtime dependency — Pillow only needs to be
installed on machines regenerating icons:

    pip install Pillow
    python -m scripts.generate_icons

Design: solid rounded square with a white speech bubble in the center. No
text — text at 192px would be illegible on a home-screen icon anyway.
Corners are kept square for the apple-touch-icon (iOS masks them itself); the
maskable PWA variant leaves a wide safe-zone margin (Android's adaptive-icon
mask may clip 10-20% of the edges into a circle).

Per-school variants (#52): in addition to the generic DUSD icon set, this
also renders one branded set per school that has a `primary_bubble_color` in
its school.json (data/schools/<id>/school.json), named icon-192-<id>.png etc.
/manifest.webmanifest?school=<id> references these so a school-scoped PWA
install gets that school's color on the home screen instead of the generic
blue. Schools without a theme color yet are skipped — the generic icon set
is still used as their fallback."""
from pathlib import Path

from PIL import Image, ImageDraw

from app.schools import load_schools

# Matches the default --user-bubble-bg in chatbox.html so the generic icon's
# color feels consistent with the app's default accent when no school is
# pinned.
BRAND_BLUE = (0, 122, 255, 255)
WHITE = (255, 255, 255, 255)

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"


def _hex_to_rgba(hex_color: str) -> tuple:
    """'#00695c' -> (0, 105, 92, 255). Raises ValueError on malformed input —
    deliberately not swallowed, so a typo'd theme_color in school.json fails
    icon generation loudly instead of silently shipping a wrong-colored icon."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, 255)


def _draw_chat_bubble(img: Image.Image, size: int, safe_zone_ratio: float = 1.0, dot_color=BRAND_BLUE):
    """Draw a white speech bubble centered on img. safe_zone_ratio < 1 shrinks
    the drawing so it survives Android's adaptive-icon mask cropping."""
    draw = ImageDraw.Draw(img)
    scale = safe_zone_ratio
    # Bubble body: rounded rect occupying middle of the canvas.
    pad_x = int(size * (0.22 + (1 - scale) * 0.5))
    pad_y = int(size * (0.24 + (1 - scale) * 0.5))
    right = size - pad_x
    bottom = int(size * (0.62 + (1 - scale) * 0.25))
    radius = int(size * 0.08)
    draw.rounded_rectangle([pad_x, pad_y, right, bottom], radius=radius, fill=WHITE)

    # Bubble tail: a triangle pointing down from the bottom-left of the body.
    tail_x = pad_x + int(size * 0.10 * scale)
    tail_top = bottom - 1  # -1 to overlap so no seam shows on some renderers
    tail_bottom = int(size * (0.78 + (1 - scale) * 0.1))
    tail_width = int(size * 0.10 * scale)
    draw.polygon(
        [
            (tail_x, tail_top),
            (tail_x + tail_width, tail_top),
            (tail_x + tail_width // 3, tail_bottom),
        ],
        fill=WHITE,
    )

    # Three dots inside the bubble to hint "chat / typing".
    dot_r = max(int(size * 0.028), 2)
    dot_y = (pad_y + bottom) // 2
    center_x = (pad_x + right) // 2
    spacing = int(size * 0.10)
    for cx in (center_x - spacing, center_x, center_x + spacing):
        draw.ellipse(
            [cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r],
            fill=dot_color,
        )


def render_icon(
    size: int,
    out_path: Path,
    *,
    rounded: bool = False,
    safe_zone_ratio: float = 1.0,
    brand_color=BRAND_BLUE,
):
    img = Image.new("RGBA", (size, size), brand_color)
    if rounded:
        # Web-only PWA icons look better with rounded corners baked in; iOS
        # doesn't need this (Springboard masks it), and would show a small
        # transparent halo if we rounded the apple-touch-icon.
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=int(size * 0.22), fill=255)
        rounded_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rounded_img.paste(img, (0, 0), mask=mask)
        img = rounded_img
    _draw_chat_bubble(img, size, safe_zone_ratio=safe_zone_ratio, dot_color=brand_color)
    img.save(out_path, format="PNG", optimize=True)
    print(f"  wrote {out_path.relative_to(OUT_DIR.parent.parent)} ({size}x{size})")


def _render_icon_set(suffix: str, *, brand_color=BRAND_BLUE):
    """Renders the four icon variants (192, 512, 512-maskable, apple-touch)
    sharing a suffix — "" for the generic set, "-<school id>" for a branded
    one — so the generic and per-school code paths can't drift apart."""
    render_icon(192, OUT_DIR / f"icon-192{suffix}.png", rounded=True, brand_color=brand_color)
    render_icon(512, OUT_DIR / f"icon-512{suffix}.png", rounded=True, brand_color=brand_color)
    # Maskable variant — full-bleed background, content shrunk into the
    # 80% safe zone so adaptive-icon clipping doesn't chop the bubble.
    render_icon(
        512, OUT_DIR / f"icon-512-maskable{suffix}.png", rounded=False, safe_zone_ratio=0.75, brand_color=brand_color
    )
    # iOS home-screen icon — square, no transparency, no rounding (Springboard
    # applies the squircle mask itself).
    render_icon(180, OUT_DIR / f"apple-touch-icon{suffix}.png", rounded=False, brand_color=brand_color)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"generating icons into {OUT_DIR}")
    _render_icon_set("")

    for school in load_schools().values():
        if not school.primary_bubble_color:
            continue
        print(f"generating branded icons for {school.id} ({school.primary_bubble_color})")
        _render_icon_set(f"-{school.id}", brand_color=_hex_to_rgba(school.primary_bubble_color))


if __name__ == "__main__":
    main()
