"""
Shared headline classification used by the story picker and the card designer:
which industry a story belongs to, what kind of story it is, and whether two
headlines are about the same topic (same film or star).
"""

import re

import config

INDUSTRIES = {
    "TELUGU": {
        "label": "TELUGU CINEMA", "color": (255, 122, 26),
        "explicit": ["telugu", "tollywood"],
        "words": ["telugu", "tollywood", "prabhas", "allu arjun", "mahesh babu", "jr ntr", "ntr",
                  "ram charan", "pawan kalyan", "chiranjeevi", "nagarjuna", "rajamouli", "pushpa",
                  "baahubali", "salaar", "devara", "nani", "vijay deverakonda", "game changer",
                  "sukumar", "trivikram", "balakrishna"],
    },
    "TAMIL": {
        "label": "TAMIL CINEMA", "color": (230, 57, 70),
        "explicit": ["tamil", "kollywood"],
        "words": ["tamil", "kollywood", "rajinikanth", "kamal haasan", "vijay", "ajith", "suriya",
                  "dhanush", "karthi", "sivakarthikeyan", "jailer", "coolie", "thug life",
                  "lokesh kanagaraj", "atlee", "nayanthara", "trisha", "mani ratnam"],
    },
    "KANNADA": {
        "label": "KANNADA CINEMA", "color": (244, 180, 0),
        "explicit": ["kannada", "sandalwood"],
        "words": ["kannada", "sandalwood", "yash", "darshan", "sudeep", "rishab shetty", "kantara",
                  "kgf", "shiva rajkumar", "puneeth rajkumar", "prashanth neel"],
    },
    "MALAYALAM": {
        "label": "MALAYALAM CINEMA", "color": (0, 184, 148),
        "explicit": ["malayalam", "mollywood"],
        "words": ["malayalam", "mollywood", "mohanlal", "mammootty", "dulquer salmaan",
                  "fahadh faasil", "prithviraj", "tovino thomas", "nivin pauly"],
    },
}

CATEGORIES = [
    ("BOX OFFICE", ["box office", "collection", "crore", "crores", "day 1", "opening", "blockbuster", "worldwide", "gross"]),
    ("TRAILER", ["trailer"]),
    ("TEASER", ["teaser", "glimpse"]),
    ("FIRST LOOK", ["first look", "poster", "motion poster"]),
    ("RELEASE DATE", ["release date", "to release", "releasing", "release on"]),
    ("OTT", ["ott", "netflix", "prime video", "hotstar", "zee5", "sonyliv", "streaming"]),
    ("SONG", ["song", "lyrical", "first single"]),
    ("BIGG BOSS", ["bigg boss"]),
    ("CASTING", ["joins", "roped in", "to star", "cast as"]),
]

DEFAULT_CATEGORY = "CINEMA NEWS"

# Words that appear in many headlines and say nothing about the topic.
GENERIC_WORDS = set("""
the and for with from about after before over under into out off new latest big biggest massive huge
top first second third last next day days week weeks box office collection collections worldwide
global india indian film films movie movies cinema cinemas actor actress star stars hero heroine
director producer makers fans fan trailer teaser glimpse poster look release releases released
releasing date ott song songs review reviews update updates record records crore crores gross
opening hit flop budget verdict streaming announce announced announces announcement shoot shooting
begins wraps wrap start starts launch launches launched ever see check here know everything all you
need telugu tollywood tamil kollywood kannada sandalwood malayalam mollywood south pan says said
confirms confirmed reveals revealed gets get gives given takes taken makes made will may now today
tomorrow live watch video twitter reaction reactions fans celebrate celebrates internet viral
january february march april june july august september october november december
""".split())


def _compile(terms):
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b", re.IGNORECASE)


_STAR_RE = _compile(config.STAR_NAMES)


def detect_industry(title: str):
    t = title.lower()
    best, best_score = None, 0
    for name, info in INDUSTRIES.items():
        score = 0
        for word in info["words"]:
            if re.search(r"\b" + re.escape(word) + r"\b", t):
                score += 3 if word in info["explicit"] else 1
        if score > best_score:
            best, best_score = name, score
    return best


def detect_category(title: str) -> str:
    t = title.lower()
    for label, words in CATEGORIES:
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", t):
                return label
    return DEFAULT_CATEGORY


def strong_entities(title: str) -> set:
    """Known stars / film names mentioned in the headline."""
    return {m.lower() for m in _STAR_RE.findall(title)}


def content_tokens(title: str) -> set:
    """Distinctive words (names, film titles) once generic cinema words are removed."""
    return {w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in GENERIC_WORDS}


def same_topic(a: str, b: str) -> bool:
    """True when two different headlines are about the same film or star."""
    if strong_entities(a) & strong_entities(b):
        return True
    ta, tb = content_tokens(a), content_tokens(b)
    if ta and tb:
        return len(ta & tb) / len(ta | tb) >= 0.4
    return False


def pick_diverse(items, n):
    """Chooses up to n stories from a best-first list: never two on the same
    topic, and spread across industries and story types."""
    chosen, pool = [], list(items)
    while pool and len(chosen) < n:
        best, best_adjusted = None, None
        for item in pool:
            if any(same_topic(item.title, c.title) for c in chosen):
                continue
            industry = detect_industry(item.title)
            category = detect_category(item.title)
            penalty = 0.0
            for c in chosen:
                if industry and detect_industry(c.title) == industry:
                    penalty += config.DIVERSITY_INDUSTRY_PENALTY
                if category != DEFAULT_CATEGORY and detect_category(c.title) == category:
                    penalty += config.DIVERSITY_CATEGORY_PENALTY
            adjusted = item.score - penalty
            if best is None or adjusted > best_adjusted:
                best, best_adjusted = item, adjusted
        if best is None:
            break
        chosen.append(best)
        pool.remove(best)
    return chosen
