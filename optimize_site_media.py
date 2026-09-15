"""Generate website previews. Install: pip install Pillow imageio-ffmpeg."""
from pathlib import Path
import subprocess

from PIL import Image, ImageOps
import imageio_ffmpeg


def main():
  root = Path(__file__).resolve().parent / "assets"
  original_bytes = preview_bytes = 0
  for name in ("backpack", "nuby"):
    folder = root / name
    previews = folder / "preview"
    previews.mkdir(exist_ok=True)
    images = sorted(p for p in folder.iterdir()
                    if p.suffix.lower() in (".jpg", ".webp", ".png"))
    for source in images:
      target = previews / (source.stem + ".webp")
      with Image.open(source) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((300, 300), Image.Resampling.LANCZOS)
        im.save(target, "WEBP", quality=80, method=6)
      original_bytes += source.stat().st_size
      preview_bytes += target.stat().st_size
    source = folder / "slideshow.mp4"
    target = folder / "slideshow-web.mp4"
    temporary = folder / "slideshow-web.tmp.mp4"
    subprocess.run([
      imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(source),
      "-vf", "scale=480:480:force_original_aspect_ratio=decrease:force_divisible_by=2",
      "-c:v", "libx264", "-preset", "medium", "-crf", "26",
      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
      "-movflags", "+faststart", str(temporary),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    temporary.replace(target)
    print(f"{name}: video {source.stat().st_size:,} -> {target.stat().st_size:,} bytes")
  print(f"Image previews: {original_bytes:,} -> {preview_bytes:,} bytes")


if __name__ == "__main__":
  main()
