"""Regenerate PWA + iOS home-screen icons from a single programmatic design.

Run when the icon design changes; commits the PNGs. Not a runtime dependency —
Pillow only needs to be installed on machines regenerating icons:

    pip install Pillow
    python -m scripts.generate_icons

Design: solid iOS-blue rounded square with a white speech bubble in the center.
No text — text at 192px would be illegible on a home-screen icon anyway.
Corners are kept square for the apple-touch-icon (iOS masks them itself); the
maskable PWA variant leaves a wide safe-zone margin (Android's adaptive-icon
mask may clip 10-20% of the edges into a circle)."""
from pathlib import Path

from PIL import Image, ImageDraw

# Matches --user-bubble-bg in chatbox.html so the icon color feels consistent
# with the app's primary accent.
BRAND_BLUE = (0, 122, 255, 255)
WHITE = (255, 255, 255, 255)

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"


def _draw_chat_bubble(img: Image.Image, size: int, safe_zone_ratio: float = 1.0):
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
            fill=BRAND_BLUE,
        )


def render_icon(size: int, out_path: Path, *, rounded: bool = False, safe_zone_ratio: float = 1.0):
    img = Image.new("RGBA", (size, size), BRAND_BLUE)
    if rounded:
        # Web-only PWA icons look better with rounded corners baked in; iOS
        # doesn't need this (Springboard masks it), and would show a small
        # transparent halo if we rounded the apple-touch-icon.
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=int(size * 0.22), fill=255)
        rounded_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rounded_img.paste(img, (0, 0), mask=mask)
        img = rounded_img
    _draw_chat_bubble(img, size, safe_zone_ratio=safe_zone_ratio)
    img.save(out_path, format="PNG", optimize=True)
    print(f"  wrote {out_path.relative_to(OUT_DIR.parent.parent)} ({size}x{size})")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"generating icons into {OUT_DIR}")
    # Standard PWA icons — rounded corners baked in for browser-tab / A2HS
    # display on Android/desktop.
    render_icon(192, OUT_DIR / "icon-192.png", rounded=True)
    render_icon(512, OUT_DIR / "icon-512.png", rounded=True)
    # Maskable variant — full-bleed background, content shrunk into the
    # 80% safe zone so adaptive-icon clipping doesn't chop the bubble.
    render_icon(512, OUT_DIR / "icon-512-maskable.png", rounded=False, safe_zone_ratio=0.75)
    # iOS home-screen icon — square, no transparency, no rounding (Springboard
    # applies the squircle mask itself).
    render_icon(180, OUT_DIR / "apple-touch-icon.png", rounded=False)


if __name__ == "__main__":
    main()
