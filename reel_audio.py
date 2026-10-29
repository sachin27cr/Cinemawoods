"""
Sound for the Reels, generated in code (original audio, so there is no licence question).

  beat   drums + 808 bass + soft pad at REEL_BPM, so the video cuts land on the beat
  sfx    whoosh (transitions), impact (headline slams / reveals), riser (before a reveal),
         tick (box-office counter), pop (text and badges appearing)

If assets/music/ has tracks you are allowed to use, reel_templates mixes one of them under the effects
instead of the generated beat.
"""

import math
import wave

import numpy as np

SR = 44100
BPM = 120
BEAT = 60.0 / BPM

_rng = np.random.default_rng()


# ------------------------------------------------------------------ building blocks

def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def _noise(seconds: float) -> np.ndarray:
    return _rng.uniform(-1, 1, int(seconds * SR))


def _band(sig: np.ndarray, lo: float = 0.0, hi: float = 20000.0) -> np.ndarray:
    """Band-pass by FFT mask (soft edges so it doesn't ring)."""
    if len(sig) == 0:
        return sig
    spec = np.fft.rfft(sig)
    f = np.fft.rfftfreq(len(sig), 1 / SR)
    mask = np.ones_like(f)
    if lo > 0:
        mask *= 1 / (1 + (lo / np.maximum(f, 1)) ** 4)
    if hi < SR / 2:
        mask *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(spec * mask, len(sig))


def _place(buf: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    if i < 0:
        sig, i = sig[-i:], 0
    n = min(len(sig), len(buf) - i)
    buf[i:i + n] += sig[:n] * gain


def _norm(sig: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(sig)) if len(sig) else 0
    return sig / peak if peak > 0 else sig


# ------------------------------------------------------------------ instruments

def _kick() -> np.ndarray:
    t = _t(0.45)
    phase = 2 * np.pi * (45 * t + 110 / 28 * (1 - np.exp(-28 * t)))
    body = np.sin(phase) * np.exp(-t * 7)
    click = _band(_noise(0.45), 1500, 8000) * np.exp(-t * 400) * 0.5
    return np.tanh((body + click) * 1.6)


def _clap() -> np.ndarray:
    t = _t(0.3)
    n = _band(_noise(0.3), 900, 5000)
    env = np.exp(-t * 28)
    for d in (0.008, 0.017):  # the little flam that makes it sound like a clap
        env = env + np.where(t >= d, np.exp(-(t - d) * 120) * 0.6, 0) * (t < d + 0.02)
    return _norm(n * env)


def _hat(open_: bool = False) -> np.ndarray:
    dur = 0.22 if open_ else 0.06
    t = _t(dur)
    return _norm(_band(_noise(dur), 7000) * np.exp(-t * (18 if open_ else 90)))


def _bass(freq: float, dur: float) -> np.ndarray:
    t = _t(dur)
    f = freq * (1 + 0.6 * np.exp(-t * 40))  # small pitch drop at the start, 808 style
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.minimum(1, t / 0.005) * np.exp(-t * 2.0)
    return np.tanh(np.sin(phase) * env * 1.8)


def _pad_chord(freqs, dur: float) -> np.ndarray:
    t = _t(dur)
    sig = np.zeros_like(t)
    for fr in freqs:
        for det in (-0.6, 0.6):
            sig += np.sin(2 * np.pi * (fr + det) * t) + 0.3 * np.sin(2 * np.pi * 2 * (fr + det) * t)
    env = np.minimum(1, t / 0.25) * np.minimum(1, (dur - t) / 0.3)
    return _norm(sig) * np.clip(env, 0, 1)


# A minor: Am - F - C - G (one chord per bar of 4 beats)
_ROOTS = [55.0, 43.65, 65.41, 49.0]
_CHORDS = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]


def beat(total: float, drums_from: float = 0.0) -> np.ndarray:
    """Drums + bass + pad for `total` seconds. Drums/bass start at `drums_from` (pad only before that)."""
    n = int(total * SR)
    drums = np.zeros(n)
    bass = np.zeros(n)
    pad = np.zeros(n)
    kick, clap, hat_c, hat_o = _kick(), _clap(), _hat(), _hat(True)
    bar = 4 * BEAT
    bars = int(math.ceil(total / bar)) + 1
    duck = np.ones(n)
    for b in range(bars):
        t0 = b * bar
        k = b % 4
        _place(pad, _pad_chord(_CHORDS[k], bar + 0.3), t0)
        if t0 + bar <= drums_from:
            continue
        for kb in (0, 2, 2.75):  # kick pattern (in beats)
            at = t0 + kb * BEAT
            if at >= drums_from:
                _place(drums, kick, at, 0.95)
                i = int(at * SR)
                seg = np.exp(-_t(0.35) * 9)
                end = min(n, i + len(seg))
                if i < n:
                    duck[i:end] = np.minimum(duck[i:end], 1 - 0.65 * seg[:end - i])
        for cb in (1, 3):
            at = t0 + cb * BEAT
            if at >= drums_from:
                _place(drums, clap, at, 0.55)
        steps = 16 if b % 4 == 3 else 8  # a hi-hat roll at the end of every 4th bar
        for h in range(steps):
            at = t0 + h * bar / steps
            if at >= drums_from:
                _place(drums, hat_o if (steps == 8 and h % 2 == 1 and h % 4 == 3) else hat_c, at,
                       0.16 if steps == 8 else 0.11)
        for bb, ln in ((0, 1.4), (2.5, 1.0)):
            at = t0 + bb * BEAT
            if at >= drums_from:
                _place(bass, _bass(_ROOTS[k], ln), at, 0.55)
    pad = _band(pad, 120, 2400) * 0.09
    mix = drums + (bass + pad) * duck
    return mix


# ------------------------------------------------------------------ effects

def _whoosh() -> np.ndarray:
    dur = 0.5
    t = _t(dur)
    u = t / dur
    n = _noise(dur)
    low, high = _band(n, 200, 900), _band(n, 1800, 9000)
    sweep = np.clip(u * 1.6, 0, 1)
    env = np.sin(np.pi * u) ** 2
    return _norm((low * (1 - sweep) + high * sweep) * env)


def _impact() -> np.ndarray:
    dur = 1.4
    t = _t(dur)
    phase = 2 * np.pi * (34 * t + 40 / 9 * (1 - np.exp(-9 * t)))
    boom = np.sin(phase) * np.exp(-t * 2.6)
    crack = _band(_noise(dur), 80, 1800) * np.exp(-t * 14)
    tail = _band(_noise(dur), 300, 4000) * np.exp(-t * 4) * 0.15
    return np.tanh((boom * 1.2 + crack * 0.8 + tail) * 1.4)


def _riser(dur: float) -> np.ndarray:
    t = _t(dur)
    u = t / dur
    noise = _band(_noise(dur), 1500, 12000) * (u ** 2.2)
    f = 180 + 1100 * u ** 2
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * (u ** 1.5) * 0.35
    return _norm(noise + tone)


def _tick() -> np.ndarray:
    t = _t(0.03)
    return np.sin(2 * np.pi * 1900 * t) * np.exp(-t * 220)


def _pop() -> np.ndarray:
    t = _t(0.09)
    f = 520 + 900 * (t / 0.09)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45)


_GAIN = {"whoosh": 0.55, "impact": 0.9, "tick": 0.22, "pop": 0.28}


def sfx(total: float, events) -> np.ndarray:
    """events: (time, kind) or (time, 'riser', duration). A whoosh/impact is centred so its peak hits `time`."""
    buf = np.zeros(int(total * SR))
    cache = {}
    for ev in events:
        at, kind = ev[0], ev[1]
        if kind == "riser":
            dur = ev[2] if len(ev) > 2 else 1.0
            _place(buf, _riser(dur), at - dur, 0.42)
            continue
        if kind not in cache:
            cache[kind] = {"whoosh": _whoosh, "impact": _impact, "tick": _tick, "pop": _pop}[kind]()
        offset = 0.25 if kind == "whoosh" else 0.0
        _place(buf, cache[kind], at - offset, _GAIN[kind])
    return buf


# ------------------------------------------------------------------ output

def write_wav(path: str, sig: np.ndarray, fade_out: float = 0.8) -> str:
    sig = np.asarray(sig, dtype=np.float64)
    n = len(sig)
    f = int(fade_out * SR)
    if 0 < f < n:
        sig[-f:] *= np.linspace(1, 0, f)
    sig = np.tanh(sig * 1.1)
    peak = np.max(np.abs(sig)) or 1.0
    sig = sig / peak * 0.89
    pcm = (sig * 32767).astype("<i2")
    stereo = np.column_stack([pcm, pcm]).ravel()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    return path
