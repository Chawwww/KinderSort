"""
show_enhancement.py — Generate a before/after visual comparison of low-light enhancement.

Saves a side-by-side image to enhancement_comparison.png that you can
insert directly into your report as evidence that the enhancement works.

Usage:
    python show_enhancement.py
"""

from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont
import numpy as np

HERE = Path(__file__).parent.resolve()
EVENTS_FOLDER = HERE / "Events" / "Sports_Day"
OUTPUT_PATH = HERE / "enhancement_comparison.png"


def apply_enhancement(img: Image.Image) -> Image.Image:
    """Same logic as sorter.py _enhance_low_light."""
    grayscale = img.convert("L")
    mean_brightness = float(np.array(grayscale).mean())

    if mean_brightness < 70:
        boost_factor = min(120.0 / max(mean_brightness, 1.0), 4.0)
        arr = np.array(img).astype(np.float32) / 255.0
        arr = np.power(arr, 0.6)
        gamma_img = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8))
        return ImageEnhance.Brightness(gamma_img).enhance(boost_factor * 0.5)
    return img


def add_label(img: Image.Image, text: str, brightness: float) -> Image.Image:
    """Add a label bar at the bottom of the image."""
    bar_height = 40
    new_img = Image.new("RGB", (img.width, img.height + bar_height), (30, 30, 30))
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)

    # Draw label text
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    draw.text((10, img.height + 10), text, fill=(255, 255, 255), font=font)
    draw.text((img.width - 120, img.height + 10),
              f"Mean: {brightness:.0f}", fill=(200, 200, 200), font=font)
    return new_img


def main() -> None:
    # Find dark photos
    dark_photos = sorted(EVENTS_FOLDER.glob("DARK_*.jpg"))
    if not dark_photos:
        raise SystemExit(
            "No DARK_ photos found in Events/Sports_Day/\n"
            "Please run setup_test_data.py first."
        )

    # Use first 3 dark photos for comparison
    samples = dark_photos[:3]
    panels = []

    for dark_path in samples:
        with Image.open(dark_path) as img:
            img = img.convert("RGB")
            # Resize to consistent height for display
            display_h = 250
            ratio = display_h / img.height
            display_w = int(img.width * ratio)
            img = img.resize((display_w, display_h), Image.LANCZOS)

            dark_arr = np.array(img.convert("L"))
            dark_mean = float(dark_arr.mean())

            enhanced = apply_enhancement(img.copy())
            enhanced_arr = np.array(enhanced.convert("L"))
            enhanced_mean = float(enhanced_arr.mean())

        # Add labels
        dark_labeled = add_label(img, "BEFORE (dark)", dark_mean)
        enhanced_labeled = add_label(enhanced, "AFTER (enhanced)", enhanced_mean)

        # Arrow panel
        arrow_w = 50
        arrow_panel = Image.new("RGB", (arrow_w, dark_labeled.height), (240, 240, 240))
        draw = ImageDraw.Draw(arrow_panel)
        mid_y = dark_labeled.height // 2
        draw.text((8, mid_y - 8), "→", fill=(50, 120, 200))

        # Combine before + arrow + after
        row_w = dark_labeled.width + arrow_w + enhanced_labeled.width
        row = Image.new("RGB", (row_w, dark_labeled.height), (240, 240, 240))
        row.paste(dark_labeled, (0, 0))
        row.paste(arrow_panel, (dark_labeled.width, 0))
        row.paste(enhanced_labeled, (dark_labeled.width + arrow_w, 0))
        panels.append(row)

    # Stack rows vertically with separator
    sep = 6
    total_h = sum(p.height for p in panels) + sep * (len(panels) - 1)
    max_w = max(p.width for p in panels)
    final = Image.new("RGB", (max_w, total_h + 60), (240, 240, 240))

    # Title bar
    draw = ImageDraw.Draw(final)
    try:
        title_font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        title_font = ImageFont.load_default()
    draw.text((10, 15), "KinderSort Lite — Low-Light Enhancement Comparison",
              fill=(20, 20, 80), font=title_font)

    y = 55
    for panel in panels:
        final.paste(panel, (0, y))
        y += panel.height + sep

    final.save(str(OUTPUT_PATH))
    print(f"✅ Saved: {OUTPUT_PATH}")
    print(f"   Size : {OUTPUT_PATH.stat().st_size // 1024} KB")
    print(f"\nInsert enhancement_comparison.png into your report under")
    print(f"'AI Enhancement Approach' or 'Performance Evaluation' section.")


if __name__ == "__main__":
    main()