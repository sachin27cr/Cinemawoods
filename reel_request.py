"""
Reels on request. Send photos (one album, up to 10) with a caption that starts with a template name:

  ott:     OTT releases this week      (one line per film:  Title | Platform | Date | Language)
  news:    exciting news / update      (first line = headline, next lines = key points)
  poster:  new poster reveal           (first line = film name, next lines = notes such as the release date)
  bo:      box office                  (first line = film, second = figure | label, more lines = breakdown rows)
  reel:    your text word for word, headline made for you (same as before)

Anything after a line with  ---  is posted as the caption word for word. Without it, the caption is built
from your lines (plain caps heading, no emojis, exact dates). The bot renders the Reel and sends a preview
with Post Reel / Discard.
"""

import hashlib
import os
import re
import time

import config
import deps
import notify_telegram as tg

PREFIX_RE = re.compile(
    r"(?is)^\s*(?:/(ott|news|poster|bo|boxoffice|reel)(?:@\w+)?\b|(ott|news|poster|bo|box\s*office|reel)\s*[:\-])\s*")
KIND = {"ott": "ott", "news": "news", "poster": "poster", "bo": "bo", "boxoffice": "bo", "reel": "reel"}

HELP = (
    "Reel templates - send photos as one album with a caption that starts with:\n\n"
    "ott:  OTT releases this week (posters in the same order as the films)\n"
    "  ott: OCT 31 – NOV 6\n"
    "  Lucky Baskhar | Netflix | Nov 1 | Telugu\n"
    "  Amaran | Prime Video | Oct 31 | Tamil\n\n"
    "news:  headline, then 2-4 key points (one per line)\n"
    "  news: Salaar 2 shoot begins on December 12\n"
    "  Prabhas joins the sets in Hyderabad.\n"
    "  The first schedule runs for 45 days.\n\n"
    "poster:  film name, then notes\n"
    "  poster: Devara Part 2\n"
    "  Releasing in theatres on January 14, 2027\n\n"
    "bo:  film, figure | label, then breakdown rows\n"
    "  bo: Kantara Chapter 1\n"
    "  ₹400 Cr | Worldwide gross in 7 days\n"
    "  Karnataka | ₹150 Cr\n\n"
    "reel:  your text word for word, I add the headline.\n\n"
    "Optional: add a line with --- and everything below it is posted as the caption word for word."
)

INDUSTRY_TAGS = {"TELUGU": ["#Tollywood", "#TeluguCinema"], "TAMIL": ["#Kollywood", "#TamilCinema"],
                 "KANNADA": ["#Sandalwood", "#KannadaCinema"], "MALAYALAM": ["#Mollywood", "#MalayalamCinema"]}


def is_reel_request(text: str) -> bool:
    return bool(PREFIX_RE.match(text or ""))


# ------------------------------------------------------------------ parsing

def _split(text):
    m = PREFIX_RE.match(text or "")
    kind = KIND[re.sub(r"\s+", "", (m.group(1) or m.group(2)).lower())]
    body = text[m.end():].strip()
    caption = ""
    parts = re.split(r"(?m)^\s*-{3,}\s*$", body, maxsplit=1)
    if len(parts) == 2:
        body, caption = parts[0].strip(), parts[1].strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return kind, body, lines, caption


def _cells(line):
    return [c.strip() for c in line.split("|")]


def _tag(name):
    t = re.sub(r"[^A-Za-z0-9]", "", name.title())
    return f"#{t}" if 3 <= len(t) <= 30 else ""


def _hashtags(text, extra=()):
    import graphic_gen as g
    tags = [t for t in extra if t]
    low = text.lower()
    for ind, words in (("TELUGU", "telugu"), ("TAMIL", "tamil"), ("KANNADA", "kannada"), ("MALAYALAM", "malayalam")):
        if words in low:
            tags += INDUSTRY_TAGS[ind]
    ind = g._detect_industry(text)
    if ind:
        tags += INDUSTRY_TAGS[ind]
    tags = tags[:1] + ["#SouthCinema"] + tags[1:] + ["#CinemaWoods"]
    seen, out = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return " ".join(out[:9])


def _sentence(s):
    s = s.strip()
    return s if s[-1:] in ".!?" else s + "."


def parse(text):
    """Returns (kind, spec, caption, missing) - spec has no images yet; missing explains bad input."""
    import reel_templates as rt
    kind, body, lines, caption = _split(text)
    if not lines:
        return kind, None, "", "empty"

    if kind == "ott":
        rng = ""
        if "|" not in lines[0]:
            rng, lines = lines[0], lines[1:]
        films = []
        for ln in lines:
            c = _cells(ln) + ["", "", ""]
            if c[0]:
                films.append({"title": c[0], "platform": c[1], "date": c[2], "language": c[3]})
        if not films:
            return kind, None, "", "Add one line per film:  Title | Platform | Date | Language"
        if not rng:
            dates = [d for d in (rt.parse_day(f["date"]) for f in films) if d]
            rng = rt.fmt_range(dates) if len(dates) == len(films) else ""
        rng = rng.upper()
        if not caption:
            rows = []
            for f in films:
                lang = f" ({f['language']})" if f["language"] else ""
                where = ", ".join(x for x in (f["platform"], f"from {f['date']}" if f["date"] else "") if x)
                rows.append(f"{f['title']}{lang}" + (f" - {where}" if where else ""))
            plats = [_tag(f["platform"]) for f in films if f["platform"]]
            caption = (f"OTT RELEASES THIS WEEK{': ' + rng if rng else ''}\n\n" + "\n".join(rows)
                       + "\n\nWhich one is first on your watchlist?\n\n"
                       + _hashtags(" ".join(f["language"] + " " + f["title"] for f in films),
                                   ["#OTTReleases", *plats]))
        return kind, {"range": rng, "films": films}, caption, ""

    if kind == "poster":
        film, notes = lines[0], lines[1:3]
        low = body.lower()
        label = ("FIRST LOOK" if "first look" in low else "RELEASE DATE" if "release" in low
                 else "OTT POSTER" if any(w in low for w in ("ott", "streaming", "netflix", "prime")) else "NEW POSTER")
        if not caption:
            caption = (f"{film.upper()}: {label}\n\n" + " ".join(_sentence(n) for n in notes)).strip() \
                      + "\n\n" + _hashtags(body, [_tag(film)])
        return kind, {"film": film, "label": label, "notes": notes}, caption, ""

    if kind == "bo":
        film = lines[0]
        if len(lines) < 2:
            return kind, None, "", "Second line needs the figure, for example:  ₹400 Cr | Worldwide gross in 7 days"
        c = _cells(lines[1])
        try:
            fig = rt.Figure(c[0])
        except ValueError:
            return kind, None, "", "I couldn't read the figure. Write it like  ₹400 Cr  or  ₹1,250 Cr+"
        label = c[1] if len(c) > 1 else fig.rest
        rows = []
        for ln in lines[2:8]:
            rc = _cells(ln)
            if len(rc) >= 2 and rc[0] and rc[1]:
                rows.append((rc[0], rc[1]))
        if not caption:
            head = f"{fig.fmt()} {label} FOR {film}".upper()
            caption = head + ("\n\n" + "\n".join(f"{a}: {b}" for a, b in rows) if rows else "") \
                + "\n\n" + _hashtags(body, ["#BoxOffice", _tag(film)])
        return kind, {"film": film, "figure": c[0], "label": label, "rows": rows}, caption, ""

    # news / reel
    if kind == "news" and len(lines) >= 2:
        headline, points = lines[0], lines[1:5]
        if not caption:
            caption = f"{headline.upper()}\n\n" + " ".join(_sentence(p) for p in points) \
                + "\n\n" + _hashtags(body)
    else:  # one paragraph: your words are the caption, the headline is written for you
        from caption_gen import headline_for
        headline = headline_for(body)
        points = [rt._shorten(s) for s in rt._sentences(body) if rt._overlap(s, headline) < 0.7][:3]
        caption = caption or body
    import graphic_gen as g
    cat = g._detect_category(headline)
    ind = g._detect_industry(headline + " " + body)
    category = cat if cat != "CINEMA NEWS" else (g.INDUSTRIES[ind]["label"] if ind else "SOUTH CINEMA")
    return "news", {"headline": headline, "category": category, "points": points}, caption, ""


# ------------------------------------------------------------------ preview + handler

def send_preview(item_id: str, item: dict, path: str, old_message_id=None, seconds=None, template=""):
    """Sends the Reel preview with Post / Discard buttons and records it on the item."""
    length = f"{seconds:.0f}s" if seconds else f"{config.REEL_SECONDS}s+"
    name = f" - {template}" if template else ""
    rows = [[{"text": "⬇️ Download HD", "callback_data": f"hd:{item_id}"},
             {"text": "🗑 Discard", "callback_data": f"dr:{item_id}"}]]
    note = "Download HD sends the full-quality file and the caption, ready to post from your phone."
    if config.REEL_AUTO_POST:
        rows.append([{"text": "✅ Post to Instagram + Facebook", "callback_data": f"pr:{item_id}"}])
    mid = tg.send_video(path, f"🎬 Reel preview{name} ({length})\n\n{item['title']}\n\n{note}", rows)
    if old_message_id and mid:
        tg.set_status(config.TELEGRAM_CHAT_ID, old_message_id, "🎬 Replaced by a newer preview")
    item["reel"] = {"status": "rendered", "path": path, "message_id": mid, "posted": {}}
    if not mid:
        tg.send_text("The Reel was made but Telegram would not take the preview. Please send it again.")
    return mid


def _download(file_ids, item_id, out_dir):
    from graphic_gen import save_source_copy
    sources = []
    for i, fid in enumerate(file_ids[:config.REEL_MAX_IMAGES]):
        data = tg.download_file(fid)
        if not data:
            continue
        raw = os.path.join(out_dir, f"{item_id}-dl{i}.tmp")
        with open(raw, "wb") as f:
            f.write(data)
        try:
            sources.append(save_source_copy(raw, os.path.join(out_dir, f"{item_id}-s{i}.jpg")))
        except Exception as e:
            print(f"  [WARN] picture {i + 1} unusable: {type(e).__name__}")
        finally:
            os.remove(raw)
    return sources


def handle_reel_request(message: dict, store: dict, file_ids: list) -> bool:
    """Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()
    deps.ensure_pillow()
    deps.ensure_numpy()
    import reel_maker
    import reel_templates as rt
    from graphic_gen import OUT_DIR, make_headline_card, make_photo_card

    kind, spec, caption, missing = parse(text)
    if not spec:
        tg.send_text(HELP if missing == "empty" else f"{missing}\n\nSend  /reel  for all the formats.")
        return False

    item_id = hashlib.sha1(f"{text}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Reel request ({kind}): {text[:80]!r} with {len(file_ids)} picture(s)")
    sources = _download(file_ids, item_id, OUT_DIR)
    if file_ids and not sources:
        tg.send_text("I couldn't read those pictures. Please send them again as photos (JPG or PNG).")
        return False
    if len(file_ids) > config.REEL_MAX_IMAGES:
        tg.send_text(f"Using the first {config.REEL_MAX_IMAGES} pictures (the limit per Reel).")

    if kind == "ott":
        for f, src in zip(spec["films"], sources):
            f["image"] = src
        if len(sources) < len(spec["films"]):
            tg.send_text(f"{len(spec['films'])} films but {len(sources)} poster(s): the films without a poster "
                         "get a text slide. Posters are matched to films in the order you list them.")
        title = f"OTT releases this week {spec['range']}".strip()
    elif kind == "poster":
        if not sources:
            tg.send_text("A poster reveal needs the poster - send it as a photo with the  poster:  caption.")
            return False
        spec["images"] = sources[:3]
        title = f"{spec['film']}: {spec['label'].title()}"
    elif kind == "bo":
        spec["images"] = sources[:1]
        title = f"{rt.Figure(spec['figure']).fmt()} {spec['label']} - {spec['film']}"
    else:
        spec["images"] = sources[:4]
        title = spec["headline"]

    # the card is the item's thumbnail / fallback picture
    card_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    if sources:
        make_photo_card(title, sources[0], card_path)
    else:
        make_headline_card(title, "", out_path=card_path)

    path = os.path.join(reel_maker.REEL_DIR, f"{item_id}.mp4")
    try:
        seconds = rt.render(kind, spec, path)
    except Exception as e:
        print(f"[ERROR] Reel render failed: {e}")
        tg.send_text(f"⚠️ I couldn't make the Reel: {str(e)[:250]}")
        return False
    finally:
        for extra in sources[1:]:  # keep only the first picture (used if you tap Make Reel again)
            try:
                os.remove(extra)
            except OSError:
                pass

    item = {
        "title": title, "caption": caption, "link": "", "source": "Your reel",
        "image": card_path.replace(os.sep, "/"),
        "src_image": sources[0].replace(os.sep, "/") if sources else "",
        "status": "reel", "message_id": None, "created_ts": time.time(), "posted": {},
    }
    send_preview(item_id, item, path, seconds=seconds, template=rt.NAMES[kind])
    store["items"][item_id] = item
    return True
