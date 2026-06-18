"""Render the REAL demo output into a paced terminal-cinematic trailer (frames -> mp4).

  python demo/make_trailer.py /tmp/demo_ansi.txt /tmp/trailer_silent.mp4 [target_seconds]

Parses the demo's ANSI output, reveals it line-by-line in a styled terminal window, writes
per-line-duration frames, and muxes them with ffmpeg. Lay the VO over it separately.
"""
import re
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
BG = (13, 17, 23)
BAR = (28, 33, 40)
MARGIN_X, TOP = 44, 70
FS, LH = 21, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

COLORS = {  # ANSI code -> rgb
    "36": (86, 182, 194), "32": (63, 185, 80), "31": (248, 81, 73),
    "37": (230, 237, 243), "2": (110, 118, 129), "0": (201, 209, 217),
}
DEFAULT = (201, 209, 217)
ANSI = re.compile(r"\033\[([0-9;]*)m")


def parse(line: str):
    """-> list of (text, color, bold). Honors the codes demo.py emits."""
    out, color, bold, i = [], DEFAULT, False, 0
    for m in ANSI.finditer(line):
        if m.start() > i:
            out.append((line[i:m.start()], color, bold))
        codes = m.group(1).split(";")
        if "0" in codes or codes == [""]:
            color, bold = DEFAULT, False
        if "1" in codes:
            bold = True
        if "2" in codes:
            color = COLORS["2"]
        for c in codes:
            if c in COLORS and c not in ("1", "2"):
                color = COLORS[c]
        i = m.end()
    if i < len(line):
        out.append((line[i:], color, bold))
    return out


def main():
    src, out_mp4 = sys.argv[1], sys.argv[2]
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 58.0
    raw_lines = Path(src).read_text().split("\n")
    lines = [parse(l) for l in raw_lines]

    font = ImageFont.truetype(FONT, FS)
    fontb = ImageFont.truetype(FONT_B, FS)

    # per-line dwell weights -> scaled so the whole thing hits `target` seconds
    def weight(raw):
        t = ANSI.sub("", raw).strip()
        if t.startswith("=="):
            return 2.4
        if "ALL GREEN" in t or t.startswith("✗") or "FAIL" in t or "SOLVENT" in t.upper():
            return 2.2
        if t == "":
            return 0.5
        return 1.0
    weights = [weight(l) for l in raw_lines]
    hold = 2.5  # final hold
    unit = (target - hold) / max(sum(weights), 1)
    durs = [max(0.25, w * unit) for w in weights]

    frames_dir = Path("/tmp/trailer_frames")
    frames_dir.mkdir(exist_ok=True)
    for f in frames_dir.glob("*.png"):
        f.unlink()

    concat = []
    for i in range(len(lines)):
        img = Image.new("RGB", (W, H), BG)
        dr = ImageDraw.Draw(img)
        # window chrome
        dr.rectangle([0, 0, W, 36], fill=BAR)
        for k, c in enumerate([(248, 81, 73), (240, 184, 60), (63, 185, 80)]):
            dr.ellipse([20 + k * 22, 13, 32 + k * 22, 25], fill=c)
        dr.text((W // 2 - 70, 10), "solvent — live demo", font=font, fill=(139, 148, 158))
        # revealed lines so far
        y = TOP
        for seg in lines[: i + 1]:
            x = MARGIN_X
            for text, color, bold in seg:
                dr.text((x, y), text, font=(fontb if bold else font), fill=color)
                x += int(dr.textlength(text, font=(fontb if bold else font)))
            y += LH
        p = frames_dir / f"f{i:03d}.png"
        img.save(p)
        concat.append((p, durs[i] + (hold if i == len(lines) - 1 else 0)))

    # ffmpeg concat demuxer with per-image durations
    cf = frames_dir / "concat.txt"
    with open(cf, "w") as fh:
        for p, d in concat:
            fh.write(f"file '{p}'\nduration {d:.3f}\n")
        fh.write(f"file '{concat[-1][0]}'\n")  # last frame must repeat for duration to apply

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(cf),
        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", out_mp4,
    ], check=True, capture_output=True)
    print(f"wrote {out_mp4}  ({sum(d for _, d in concat):.1f}s, {len(lines)} reveals)")


if __name__ == "__main__":
    main()
