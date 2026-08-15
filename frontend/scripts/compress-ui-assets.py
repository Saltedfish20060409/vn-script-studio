from pathlib import Path
from PIL import Image


def compress(path: Path, max_w: int) -> None:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    if w > max_w:
        nh = int(h * (max_w / w))
        im = im.resize((max_w, nh), Image.Resampling.LANCZOS)
    # Palette compress while keeping alpha via adaptive RGB + alpha reattach
    alpha = im.getchannel("A")
    rgb = im.convert("RGB")
    pal = rgb.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    out = pal.convert("RGBA")
    out.putalpha(alpha.resize(out.size, Image.Resampling.NEAREST))
    before = path.stat().st_size
    out.save(path, format="PNG", optimize=True, compress_level=9)
    after = path.stat().st_size
    print(
        f"{path.name}: {before // 1024}KB -> {after // 1024}KB "
        f"({w}x{h} -> {out.size[0]}x{out.size[1]})"
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "public"
    for p in (root / "writers").glob("*.png"):
        compress(p, 384)
    agent = root / "agent"
    compress(agent / "agent-dialog-frame.png", 1280)
    compress(agent / "agent-dossier-tab.png", 160)
    empty = agent / "agent-empty-stage.png"
    if empty.exists():
        empty.unlink()
        print("removed agent-empty-stage.png")
    workshop = root / "workshop"
    if (workshop / "workshop-empty.png").exists():
        compress(workshop / "workshop-empty.png", 640)
    ui = root / "ui"
    if (ui / "ui-chrome-strip.png").exists():
        compress(ui / "ui-chrome-strip.png", 960)
    print("done")


if __name__ == "__main__":
    main()
