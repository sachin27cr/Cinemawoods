"""Voice-over for Reels. Text in, an audio file and its length out.

Engines (VOICE_ENGINE):
  edge    Microsoft Edge neural voices through the free `edge-tts` package - Indian English
          (en-IN-NeerjaNeural female, en-IN-PrabhatNeural male). Needs internet, no key. Default.
  kokoro  offline model (kokoro-onnx), used only if installed.
If the engine fails, speak() returns None and the Reel is made without a voice-over.
"""

import asyncio
import os
import re
import subprocess

VOICE_ENGINE = os.environ.get("VOICE_ENGINE", "edge").lower()
VOICE_NAME = os.environ.get("VOICE_NAME", "en-IN-NeerjaNeural")
VOICE_RATE = os.environ.get("VOICE_RATE", "-4%")          # a touch slower than normal speech reads better
KOKORO_DIR = os.environ.get("KOKORO_DIR", "/tmp/kk")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "hm_psi")   # male

_counter = [0]

# Spoken spellings for names and words the voices get wrong. Built-in list is used by the offline engine only;
# anything you add to assets/pronunciations.txt (one  Written = how it should sound  per line) is used by both.
BUILTIN = {
    "Telugu": "Telugoo", "Tamil": "Taamil", "Malayalam": "Malayaalam", "Kannada": "Kannadaa", "Kollywood": "Kolly wood",
    "Tollywood": "Tolly wood", "Mollywood": "Molly wood", "Sandalwood": "Sandal wood", "Diwali": "Divaali",
    "Hyderabad": "Haidaraabaad", "Kerala": "Keralaa", "Karnataka": "Karnaataka", "Chennai": "Chennai",
    "Itlu": "Itloo", "Arjuna": "Arjunaa", "Thaman": "Thaaman", "Kantara": "Kaantaara", "Salaar": "Saalaar",
    "Prabhas": "Prabhaas", "Devara": "Devaraa", "Pushpa": "Pushpaa", "Uppala": "Uppalaa", "Das": "Daas",
    "Ajith": "Ajit", "Dhanush": "Dhanush", "Mohanlal": "Mohan laal", "Mammootty": "Mammootty", "Yash": "Yash",
    "Rajinikanth": "Rajini kaanth", "Allu": "Alloo", "Ram Charan": "Raam Charan", "Jr NTR": "Junior N T R",
    "NTR": "N T R", "SS Rajamouli": "S S Raajamouli", "Rajamouli": "Raajamouli", "Pondicherry": "Pondicherry",
}


def _user_map():
    out = {}
    for p in (os.path.join("assets", "pronunciations.txt"),):
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8"):
                if "=" in ln and not ln.lstrip().startswith("#"):
                    a, b = ln.split("=", 1)
                    if a.strip() and b.strip():
                        out[a.strip()] = b.strip()
    return out


def respell(text):
    table = dict(BUILTIN) if VOICE_ENGINE == "kokoro" else {}
    table.update(_user_map())
    for word in sorted(table, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", table[word], text)
    return text


def clean(text):
    """Written text -> what should be spoken."""
    t = text or ""
    t = re.sub(r"[#@]", "", t)
    t = re.sub(r"₹\s*([\d,.]+)\s*(cr|crore)s?\b\.?", r"\1 crore rupees", t, flags=re.I)
    t = re.sub(r"₹\s*([\d,.]+)\s*(l|lakh)s?\b\.?", r"\1 lakh rupees", t, flags=re.I)
    t = re.sub(r"₹\s*([\d,.]+)", r"\1 rupees", t)
    t = re.sub(r"\bRs\.?\s*([\d,.]+)", r"\1 rupees", t)
    t = re.sub(r"\bCr\b", "crore", t)
    t = t.replace("&", " and ").replace("–", ", ").replace("—", ", ")
    t = re.sub(r"\bOTT\b", "O T T", t)
    t = re.sub(r"\s+", " ", t).strip()
    return respell(t)


def _duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _edge(text, path):
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, VOICE_NAME, rate=VOICE_RATE).save(path)
    asyncio.run(go())


def _kokoro(text, path):
    import soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(os.path.join(KOKORO_DIR, "kokoro-v1.0.int8.onnx"), os.path.join(KOKORO_DIR, "voices-v1.0.bin"))
    samples, sr = k.create(text, voice=KOKORO_VOICE, speed=0.92, lang="en-us")
    sf.write(path, samples, sr)


def speak(text, out_dir):
    """Returns (path, seconds) or None."""
    text = clean(text)
    if not text or VOICE_ENGINE in ("off", "none", "0"):
        return None
    _counter[0] += 1
    ext = "wav" if VOICE_ENGINE == "kokoro" else "mp3"
    path = os.path.join(out_dir, f"vo-{os.getpid()}-{_counter[0]}.{ext}")
    try:
        (_kokoro if VOICE_ENGINE == "kokoro" else _edge)(text, path)
    except Exception as e:
        print(f"  [voice] {VOICE_ENGINE} failed: {type(e).__name__}: {str(e)[:120]}")
        return None
    dur = _duration(path)
    if dur <= 0.2:
        return None
    return path, dur
