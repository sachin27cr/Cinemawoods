"""
Turns a draft's picture into a short vertical video (Reel): 1080x1920, H.264 + AAC MP4.

  0.0s  the picture, slowly zooming in (Ken Burns), logo + tag at the top
  1.0s  the headline fades in
  3.0s  a short line of the post text fades in
  end   "FOLLOW @handle"

Needs ffmpeg (preinstalled on GitHub runners, otherwise the workflow installs it).
Music: any .mp3/.m4a/.wav/.aac in assets/music/ is used (add tracks you are allowed to use).
With none there, a soft generated ambient pad is used - it is original, so there is no licence question.
"""

import glob
import os
import random
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import config
import graphic_gen as g

RW, RH = 1080, 1920
FPS = 30
REEL_DIR = "reels"
MUSIC_DIR = os.path.join("assets", "music")


# ------------------------------------------------------------------ text helpers

def summary_line(caption: str, limit: int = 150) -> str:
    """First sentence(s) of the post text, without hashtags/credits, short enough for the screen."""
    lines = [ln.strip() for ln in caption.splitlines()]
    body = " ".join(ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("📸"))
    body = re.sub(r"#\w+|https?://\S+", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    sentences = re.split(r"(?<=[.!?])\s+", body)
    out = ""
    for s in sentences:
        if not s:
            continue
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
        if len(out) >= 70:
            break
    if len(out) > limit:
        out = out[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return out


# ------------------------------------------------------------------ pictures

def _base_frame(src_path: str, is_card: bool) -> Image.Image:
    """The 1080x1920 picture that gets the slow zoom."""
    src = ImageOps.exif_transpose(Image.open(src_path)).convert("RGB")
    portrait = src.width / src.height < 0.75
    if not is_card and portrait:
        return ImageOps.fit(src, (RW, RH), Image.LANCZOS, centering=(0.5, 0.3))
    # landscape/square pictures and finished cards: show the whole picture on a blurred, darkened copy of itself
    bg = ImageOps.fit(src, (RW, RH), Image.LANCZOS).filter(ImageFilter.GaussianBlur(50))
    bg = Image.blend(bg, Image.new("RGB", (RW, RH), (10, 10, 14)), 0.55)
    width = 960 if is_card else RW
    pic = src.resize((width, int(src.height * width / src.width)), Image.LANCZOS)
    top = 250 if is_card else 300
    bg.paste(pic, ((RW - width) // 2, top))
    return bg


def _gradient(height: int, top_alpha: float, bottom_alpha: float) -> Image.Image:
    col = Image.new("L", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        col.putpixel((0, y), int(255 * (top_alpha + (bottom_alpha - top_alpha) * t)))
    return col.resize((RW, height))


def _overlay_fixed(accent, label) -> Image.Image:
    """Logo + industry tag at the top (stays on screen the whole time)."""
    ov = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    shade = Image.new("RGBA", (RW, 360), (6, 6, 10, 255))
    shade.putalpha(_gradient(360, 0.6, 0.0))
    ov.alpha_composite(shade, (0, 0))
    draw = ImageDraw.Draw(ov)
    y = 190  # below Instagram's own top bar
    import branding
    branding.lockup(ov, 56, y, 110)
    f = g._font(g.BOLD_FONTS, 26)
    tw = g._text_w(draw, label, f)
    draw.rounded_rectangle([RW - 60 - tw - 44, y + 22, RW - 60, y + 74], radius=26,
                           fill=(10, 10, 14, 235), outline=accent, width=3)
    draw.text((RW - 60 - tw - 22, y + 30), label, font=f, fill=accent)
    return ov


def _overlay_headline(title, accent, category, with_text=True) -> Image.Image:
    ov = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    shade = Image.new("RGBA", (RW, 900), (6, 6, 10, 255))
    shade.putalpha(_gradient(900, 0.0, 0.93))
    ov.alpha_composite(shade, (0, RH - 900))
    if not with_text:
        return ov
    draw = ImageDraw.Draw(ov)
    font, lines, line_h = g._fit(draw, title, g.HEAD_FONTS, 880, 300, max_size=78, min_size=48)
    block = line_h * len(lines)
    y0 = 1190 - block  # headline block ends at y=1190; the summary panel sits under it
    g._chip(draw, 60, y0 - 80, category, accent, "left")
    y = y0
    for ln in lines:
        draw.text((60, y), ln, font=font, fill=g.WHITE)
        y += line_h
    return ov


def _overlay_summary(text, accent, top=1240, pill=True) -> Image.Image:
    ov = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    if not text:
        return ov
    draw = ImageDraw.Draw(ov)
    font, lines, line_h = g._fit(draw, text, g.REG_FONTS, 840, 190, max_size=42, min_size=30, spacing=1.25)
    panel_h = line_h * len(lines) + 70
    draw.rounded_rectangle([50, top, 930, top + panel_h], radius=28, fill=(14, 14, 20, 220))
    draw.rectangle([50, top + 24, 58, top + panel_h - 24], fill=accent)
    y = top + 34
    for ln in lines:
        draw.text((92, y), ln, font=font, fill=g.WHITE)
        y += line_h
    f2 = g._font(g.BOLD_FONTS, 30)
    if pill:
        import branding
        branding.follow_pill(ov, top + panel_h + 26, cx=RW // 2, scale=1.1)
    return ov


# ------------------------------------------------------------------ audio

def _music_input(seconds: int):
    """ffmpeg args for the audio input + its filter chain."""
    tracks = [p for ext in ("mp3", "m4a", "wav", "aac", "ogg") for p in glob.glob(os.path.join(MUSIC_DIR, f"*.{ext}"))]
    fade = f"afade=t=in:st=0:d=0.8,afade=t=out:st={seconds - 1.2:.1f}:d=1.2"
    if tracks:
        track = random.choice(tracks)
        print(f"  [reel] music: {os.path.basename(track)}")
        return ["-stream_loop", "-1", "-i", track], f"volume=0.9,{fade}"
    expr = ("0.05*sin(2*PI*220*t)+0.04*sin(2*PI*330*t)+"
            "0.03*sin(2*PI*440*t)*(0.6+0.4*sin(2*PI*0.25*t))+0.02*sin(2*PI*110*t)")
    print("  [reel] music: generated ambient pad (add your own tracks to assets/music/)")
    return ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds}"], f"lowpass=f=1200,{fade}"


# ------------------------------------------------------------------ render

def make_reel(item_id: str, title: str, caption: str, card_path: str, src_path: str = "",
              out_path: str = "", images=None) -> str:
    """Renders the Reel and returns its path (reels/<id>.mp4). Raises RuntimeError on failure.
    images: several source pictures -> a slideshow with cross-fades; otherwise src_path (one picture)
    or, when there is none, the finished card."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed on this runner")
    out_path = out_path or os.path.join(REEL_DIR, f"{item_id}.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    sources = [p for p in (images or ([src_path] if src_path else [])) if p and os.path.exists(p)]
    sources = sources[:config.REEL_MAX_IMAGES]
    use_src = bool(sources)
    n = max(1, len(sources))
    fade = 0.5
    if n == 1:
        seconds = config.REEL_SECONDS
        per = float(seconds)
    else:
        seconds = int(round(max(config.REEL_SECONDS, n * config.REEL_SECONDS_PER_IMAGE)))
        per = seconds / n
    clip_len = per + (fade if n > 1 else 0)

    industry = g._detect_industry(title)
    accent = g.INDUSTRIES[industry]["color"] if industry else g._hex_to_rgb(config.ACCENT_COLOR)
    label = g.INDUSTRIES[industry]["label"] if industry else "SOUTH CINEMA"
    category = g._detect_category(title)

    with tempfile.TemporaryDirectory() as tmp:
        base_paths = []
        for i, sp in enumerate(sources or [card_path]):
            bp = os.path.join(tmp, f"base{i}.png")
            _base_frame(sp, is_card=not use_src).resize((int(RW * 1.5), int(RH * 1.5)), Image.LANCZOS).save(bp)
            base_paths.append(bp)
        fixed_p, head_p, sum_p = (os.path.join(tmp, nme) for nme in ("fixed.png", "head.png", "sum.png"))
        if use_src:
            _overlay_fixed(accent, label).save(fixed_p)
            _overlay_headline(title, accent, category).save(head_p)
            _overlay_summary(summary_line(caption), accent, top=1240).save(sum_p)
        else:
            # a finished card already carries the logo and its headline, so only the summary is added
            Image.new("RGBA", (RW, RH), (0, 0, 0, 0)).save(fixed_p)
            Image.new("RGBA", (RW, RH), (0, 0, 0, 0)).save(head_p)
            _overlay_summary(summary_line(caption), accent, top=1480, pill=False).save(sum_p)

        audio_in, audio_filter = _music_input(seconds)
        frames = max(2, int(clip_len * FPS))
        zoom = (f"zoompan=z='1+0.09*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={RW}x{RH}:fps={FPS},setsar=1,format=yuv420p")
        parts = [f"[{i}:v]{zoom}[v{i}]" for i in range(len(base_paths))]
        last = "v0"
        for i in range(1, len(base_paths)):
            parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade}:offset={per * i:.3f}[x{i}]")
            last = f"x{i}"
        k = len(base_paths)  # input index where the overlays start
        parts += [
            f"[{k}:v]format=rgba[fx]",
            f"[{k + 1}:v]format=rgba,fade=t=in:st=1.0:d=0.6:alpha=1[hl]",
            f"[{k + 2}:v]format=rgba,fade=t=in:st=3.0:d=0.6:alpha=1[sm]",
            f"[{last}][fx]overlay=0:0:format=auto[a]",
            "[a][hl]overlay=0:0:format=auto[b]",
            "[b][sm]overlay=0:0:format=auto,format=yuv420p[v]",
            f"[{k + 3}:a]{audio_filter}[aout]",
        ]
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for bp in base_paths:
            cmd += ["-framerate", str(FPS), "-loop", "1", "-t", f"{clip_len:.3f}", "-i", bp]
        for ov in (fixed_p, head_p, sum_p):
            cmd += ["-loop", "1", "-t", str(seconds), "-i", ov]
        cmd += [*audio_in,
                "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[aout]",
                "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "21",
                "-maxrate", "5M", "-bufsize", "10M", "-r", str(FPS), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                "-t", str(seconds), "-movflags", "+faststart", out_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError(f"ffmpeg failed: {(res.stderr or '')[-300:]}")
    print(f"  [reel] rendered {out_path} ({os.path.getsize(out_path) // 1024} KB, {n} picture(s), {seconds}s)")
    return out_path
