from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packaging" / "wmm.ico"


def point(value: tuple[int, int], scale: float) -> tuple[int, int]:
    return round(value[0] * scale), round(value[1] * scale)


def main() -> int:
    size = 1024
    scale = size / 128
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    shield = [
        point((64, 7), scale),
        point((112, 25), scale),
        point((112, 60), scale),
        point((108, 79), scale),
        point((98, 96), scale),
        point((84, 110), scale),
        point((64, 122), scale),
        point((44, 110), scale),
        point((30, 96), scale),
        point((20, 79), scale),
        point((16, 60), scale),
        point((16, 25), scale),
    ]
    draw.polygon(shield, fill="#120d0c", outline="#c49a50", width=round(7 * scale))
    inner = [
        point((64, 15), scale),
        point((104, 30), scale),
        point((104, 60), scale),
        point((101, 75), scale),
        point((92, 90), scale),
        point((79, 103), scale),
        point((64, 113), scale),
        point((49, 103), scale),
        point((36, 90), scale),
        point((27, 75), scale),
        point((24, 60), scale),
        point((24, 30), scale),
    ]
    draw.line(inner + [inner[0]], fill="#5d381d", width=round(2 * scale), joint="curve")

    w_points = [
        point((35, 39), scale),
        point((48, 87), scale),
        point((64, 56), scale),
        point((80, 87), scale),
        point((93, 39), scale),
    ]
    draw.line(w_points, fill="#b73538", width=round(10 * scale), joint="curve")
    radius = round(7 * scale)
    center = point((64, 31), scale)
    draw.ellipse(
        (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        fill="#d6b86d",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
