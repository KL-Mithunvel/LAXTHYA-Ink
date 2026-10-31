"""The control text every writer is asked to write, split into chunks, with a coverage check.

Decisions this implements (docs/PROJECT_PLAN.md): tiered coverage with the core session
first; English + digits + the full Greek alphabet + math symbols + all 247 Tamil letters;
English built from real common words plus short filler strings only for letter pairs the
words miss; chunks of about a minute so each can be sent to the laptop as soon as it is
written.

Pure and deterministic: the same config always produces the same text (`prompts.seed`).
The generated file `prompts/<id>.json` is committed; `python -m laxthya_ink.capture.prompts`
rebuilds it and `--check` verifies the committed file is current and fully covered.

Sections, in writing order:  en-words, en-capitals, digits, punctuation, greek, greek-use,
tamil. A chunk never spans two sections. Effort is counted in *units* (one Latin character
= 1; other scripts weigh more, `prompts.units_per_glyph`) so a chunk is about the same
writing time whatever it holds. The time estimate rests on `prompts.writing_units_per_minute`,
an assumption to be measured on the first writers.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import string
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROMPT_DIR = PACKAGE_DIR / "prompts"
WORDS_FILE = PACKAGE_DIR / "words_en.txt"

FORMAT_VERSION = 1
STYLE = "natural"                     # the core set is the writer's natural hand

LOWER = string.ascii_lowercase
ALL_PAIRS = [a + b for a in LOWER for b in LOWER]
_VOWELS = "aeiouy"
_SET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# --- content ----------------------------------------------------------------

#: first-name / place pairs, one for each capital letter (each used twice, as the capital's two samples)
CAPITAL_WORDS = {
    "A": ("Anna", "Alan"), "B": ("Bella", "Boston"), "C": ("Carol", "Cairo"), "D": ("David", "Delhi"),
    "E": ("Emma", "Egypt"), "F": ("Frank", "France"), "G": ("Grace", "Greece"), "H": ("Henry", "Hawaii"),
    "I": ("Irene", "India"), "J": ("James", "Japan"), "K": ("Karen", "Kenya"), "L": ("Laura", "London"),
    "M": ("Mary", "Mumbai"), "N": ("Nora", "Nepal"), "O": ("Oscar", "Oman"), "P": ("Paul", "Paris"),
    "Q": ("Quinn", "Qatar"), "R": ("Rita", "Rome"), "S": ("Samuel", "Spain"), "T": ("Tom", "Tokyo"),
    "U": ("Uma", "Uganda"), "V": ("Vera", "Venice"), "W": ("Wendy", "Wales"), "X": ("Xavier", "Xian"),
    "Y": ("Yusuf", "Yemen"), "Z": ("Zoe", "Zurich"),
}

PUNCTUATION = ".,;:!?'\"()-/+=%@#&*_[]<>"
#: lines that put each mark in context; every mark in PUNCTUATION appears in at least one
PUNCTUATION_LINES = (
    "Yes, no; maybe: why? Wow!",
    "It's \"fine\" (really) - ok.",
    "3 + 4 = 7   8 - 2 = 6",
    "10 / 5 = 2   50 % of 20",
    "a@b.c   #7   R&D   5 * 6",
    "x_1   [a]   <b>   1,000   3.14",
)

GREEK_LOWER = "αβγδεζηθικλμνξοπρσςτυφχψω"      # 24 letters + final sigma
GREEK_UPPER = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
MATH_SYMBOLS = "°±×÷√∞≈≠≤≥∫∂∇→∠⊥∥"

#: engineering phrases that put the symbols in context (Greek and math glyphs only; plain digits and letters around them)
GREEK_USE_LINES = (
    "R = 10 kΩ ± 5 %",
    "C = 4.7 μF   L = 33 μH",
    "C = 2 π r",
    "θ = 45°   φ = 30°",
    "ω = 2 π f",
    "λ = c / f",
    "Δx / Δt",
    "σ = F / A   ρ = m / V",
    "x ≈ 3.14   y ≠ 0",
    "a ≤ b ≤ c   d ≥ 0",
    "√ 2 ≈ 1.414",
    "∞   ∫ f dx   ∂ f / ∂ x",
    "∇ · F   ∠ A ⊥ B",
    "V → 5 V   I = V / R",
    "ε   η   τ   γ   β   α",
)

# Tamil: 12 vowels + aytham + 18 consonants (with pulli) + 18 x 12 consonant-vowel letters = 247
TAMIL_VOWELS = ("அ", "ஆ", "இ", "ஈ", "உ", "ஊ", "எ", "ஏ", "ஐ", "ஒ", "ஓ", "ஔ")
TAMIL_AYTHAM = "ஃ"
TAMIL_CONSONANT_BASES = ("க", "ங", "ச", "ஞ", "ட", "ண", "த", "ந", "ப", "ம", "ய", "ர", "ல", "வ", "ழ", "ள", "ற", "ன")
TAMIL_PULLI = "்"
#: the 11 vowel signs; the 12th form of each consonant is the bare consonant (inherent "a")
TAMIL_VOWEL_SIGNS = ("ா", "ி", "ீ", "ு", "ூ", "ெ", "ே", "ை", "ொ", "ோ", "ௌ")


def tamil_letters() -> list[str]:
    """All 247 Tamil letters in teaching order: vowels, aytham, consonants, then each consonant's 12 forms."""
    letters = list(TAMIL_VOWELS) + [TAMIL_AYTHAM]
    letters += [c + TAMIL_PULLI for c in TAMIL_CONSONANT_BASES]
    for c in TAMIL_CONSONANT_BASES:
        letters.append(c)
        letters += [c + sign for sign in TAMIL_VOWEL_SIGNS]
    return letters


# --- English letter pairs ---------------------------------------------------

def _pairs(word: str) -> list[str]:
    return [word[i:i + 2] for i in range(len(word) - 1)]


def load_words(path: Path = WORDS_FILE) -> list[str]:
    """The word list: lowercase a-z only, unique, in file order; `#` lines are comments."""
    seen: dict[str, None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        for w in line.split():
            if len(w) >= 2 and all(c in LOWER for c in w):
                seen.setdefault(w)
    return list(seen)


def pick_words(words: list[str], pair_min: int) -> tuple[list[str], Counter]:
    """Greedily choose words until no remaining word adds coverage; returns (chosen, pair counts)."""
    counts: Counter = Counter()
    pool = list(words)
    chosen: list[str] = []
    while True:
        best, best_gain = None, 0
        for w in pool:
            gain = sum(min(pair_min - counts[p], c) for p, c in Counter(_pairs(w)).items() if counts[p] < pair_min)
            if gain > best_gain or (gain == best_gain and gain > 0 and best is not None and len(w) < len(best)):
                best, best_gain = w, gain
        if best is None:
            return chosen, counts
        chosen.append(best)
        pool.remove(best)
        counts.update(_pairs(best))


def make_fillers(counts: Counter, pair_min: int) -> list[str]:
    """Short strings that cover the pairs still below `pair_min` (the words never reach them).

    Needed pairs are chained when one ends where the next starts, up to six letters, and a
    string with no vowel gets an 'a' so it can be written as a word. Padding can add pairs,
    which only helps coverage.
    """
    need = {p: pair_min - counts[p] for p in ALL_PAIRS if counts[p] < pair_min}
    fillers: list[str] = []
    while need:
        pair = min(need)
        word = pair
        _consume(need, pair)
        while len(word) < 6:
            nxt = [q for q in sorted(need) if q[0] == word[-1]]
            if not nxt:
                break
            word += nxt[0][1]
            _consume(need, nxt[0])
        if not any(c in _VOWELS for c in word):
            word += "a"
        fillers.append(word)
    return fillers


def _consume(need: dict[str, int], pair: str) -> None:
    need[pair] -= 1
    if need[pair] <= 0:
        del need[pair]


def de_bruijn_digits() -> str:
    """101 digits in which every ordered digit pair (00..99) appears exactly once, contiguously."""
    k, n = 10, 2
    a = [0] * (k * n)
    sequence: list[int] = []

    def db(t: int, p: int) -> None:
        if t > n:
            if n % p == 0:
                sequence.extend(a[1:p + 1])
        else:
            a[t] = a[t - p]
            db(t + 1, p)
            for j in range(a[t - p] + 1, k):
                a[t] = j
                db(t + 1, t)

    db(1, 1)
    digits = "".join(str(d) for d in sequence)
    return digits + digits[0]                       # close the cycle so the wrap-around pair is covered


def digit_tokens() -> list[str]:
    """The digit stream as 5-digit tokens overlapping by one digit, so no pair falls between tokens."""
    stream = de_bruijn_digits()
    return [stream[i:i + 5] for i in range(0, len(stream) - 1, 4) if len(stream[i:i + 5]) >= 2]


# --- packing into lines and chunks -------------------------------------------

Line = tuple[str, float]                             # text, writing units


def _pack(tokens: list[str], unit_of: Callable[[str], float], gap: float, max_units: float) -> list[Line]:
    """Join tokens with spaces into lines of at most `max_units` (a token is never split)."""
    lines: list[Line] = []
    cur: list[str] = []
    cur_units = 0.0
    for tok in tokens:
        u = unit_of(tok)
        add = u + (gap if cur else 0.0)
        if cur and cur_units + add > max_units:
            lines.append((" ".join(cur), cur_units))
            cur, cur_units, add = [], 0.0, u
        cur.append(tok)
        cur_units += add
    if cur:
        lines.append((" ".join(cur), cur_units))
    return lines


def _text_lines(texts: list[str], weight: float) -> list[Line]:
    """Free-text lines whose effort is their non-space character count times `weight`."""
    return [(t, len(t.replace(" ", "")) * weight) for t in texts]


def _shuffled_repeats(tokens: list[str], repeats: int, rng: random.Random) -> list[str]:
    """`repeats` passes over the tokens: the first in teaching order, the rest shuffled."""
    out = list(tokens)
    for _ in range(repeats - 1):
        extra = list(tokens)
        rng.shuffle(extra)
        out += extra
    return out


def _sections(config: dict) -> tuple[list[dict], list[str]]:
    """Build every section's lines. Returns (sections, filler strings used)."""
    p = config["prompts"]
    w = p["units_per_glyph"]
    rng = random.Random(p["seed"])
    line_units, repeats = p["line_units"], p["glyph_repeats"]

    chosen, counts = pick_words(load_words(), p["pair_min"])
    fillers = make_fillers(counts, p["pair_min"])
    words = chosen + fillers
    rng.shuffle(words)

    caps = [word for pair in CAPITAL_WORDS.values() for word in pair]
    rng.shuffle(caps)

    greek_tokens = _shuffled_repeats(list(GREEK_LOWER) + list(GREEK_UPPER) + list(MATH_SYMBOLS), repeats, rng)
    punct_lines = list(PUNCTUATION_LINES) * repeats
    rng.shuffle(punct_lines)
    greek_use = list(GREEK_USE_LINES)
    rng.shuffle(greek_use)

    def latin(tokens: list[str], weight: float) -> list[Line]:
        return _pack(tokens, lambda t: len(t) * weight, weight, line_units)

    return [
        {"id": "en-words", "script": "latin", "intro": "English words. Write them in your normal handwriting, as you would on paper.",
         "lines": latin(words, w["latin"])},
        {"id": "en-capitals", "script": "latin", "intro": "Names and places with capital letters.",
         "lines": latin(caps, w["latin"])},
        {"id": "digits", "script": "digit", "intro": "Numbers. Write each group exactly as shown.",
         "lines": latin(_shuffled_repeats(digit_tokens(), 1, rng), w["digit"])},
        {"id": "punctuation", "script": "symbol", "intro": "Punctuation and signs.",
         "lines": _text_lines(punct_lines, w["symbol"])},
        {"id": "greek", "script": "greek", "intro": "Greek letters and math signs, one at a time.",
         "lines": _pack(greek_tokens, lambda t: w["greek"], 0.0, line_units)},
        {"id": "greek-use", "script": "greek", "intro": "Engineering notation.",
         "lines": _text_lines(greek_use, w["greek"])},
        {"id": "tamil", "script": "tamil", "intro": "Tamil letters, one at a time. Write each as you normally would.",
         "lines": _pack(_shuffled_repeats(tamil_letters(), repeats, rng), lambda t: w["tamil"], 0.0, line_units)},
    ], fillers


def build_prompt_set(config: dict, set_id: str | None = None) -> dict:
    """Generate the whole control text as a JSON-ready dict."""
    p = config["prompts"]
    set_id = set_id or config["capture"]["prompt_set_id"]
    if not _SET_ID_RE.match(set_id):
        raise ValueError(f"prompt set id must be lowercase letters, digits and dashes, got {set_id!r}")
    sections, fillers = _sections(config)

    chunks: list[dict] = []
    for sec in sections:
        cur: list[Line] = []
        first = True

        def flush() -> None:
            nonlocal cur, first
            if not cur:
                return
            chunks.append({
                "id": f"{set_id}-{len(chunks) + 1:03d}",
                "section": sec["id"],
                "script": sec["script"],
                "intro": sec["intro"] if first else "",
                "lines": [t for t, _ in cur],
                "units": round(sum(u for _, u in cur), 1),
            })
            cur, first = [], False

        for line in sec["lines"]:
            cur.append(line)
            if sum(u for _, u in cur) >= p["chunk_units"]:
                flush()
        flush()

    total = sum(c["units"] for c in chunks)
    return {
        "id": set_id,
        "format": FORMAT_VERSION,
        "style": STYLE,
        "params": {k: p[k] for k in ("seed", "pair_min", "glyph_repeats", "chunk_units", "line_units")},
        "fillers": fillers,
        "total_units": round(total, 1),
        "estimated_minutes": round(total / p["writing_units_per_minute"], 1),
        "break_every_chunks": p["break_every_chunks"],
        "max_pending_chunks": p["max_pending_chunks"],
        "chunks": chunks,
    }


# --- coverage check ---------------------------------------------------------

def _section_text(prompt_set: dict, section: str) -> list[str]:
    return [line for c in prompt_set["chunks"] if c["section"] == section for line in c["lines"]]


def check_coverage(prompt_set: dict, config: dict) -> dict:
    """Verify the text really contains what the decisions promised. Returns
    `{"problems": [...], "stats": {...}}`; no problems means fully covered."""
    p = config["prompts"]
    problems: list[str] = []

    pair_counts: Counter = Counter()
    for line in _section_text(prompt_set, "en-words"):
        for word in line.split():
            pair_counts.update(_pairs(word))
    short = sorted(pp for pp in ALL_PAIRS if pair_counts[pp] < p["pair_min"])
    if short:
        problems.append(f"{len(short)} letter pairs appear fewer than {p['pair_min']} times: {' '.join(short[:20])}")

    initials: Counter = Counter(w[0] for line in _section_text(prompt_set, "en-capitals") for w in line.split())
    missing_caps = [c for c in string.ascii_uppercase if initials[c] < 2]
    if missing_caps:
        problems.append(f"capital letters written fewer than 2 times: {' '.join(missing_caps)}")

    digit_pairs: Counter = Counter()
    digit_chars: Counter = Counter()
    for line in _section_text(prompt_set, "digits"):
        for tok in line.split():
            digit_pairs.update(_pairs(tok))
            digit_chars.update(tok)
    absent = [f"{a}{b}" for a in "0123456789" for b in "0123456789" if digit_pairs[f"{a}{b}"] < 1]
    if absent:
        problems.append(f"{len(absent)} digit pairs never written: {' '.join(absent[:20])}")
    few = [d for d in "0123456789" if digit_chars[d] < p["glyph_repeats"]]
    if few:
        problems.append(f"digits written fewer than {p['glyph_repeats']} times: {' '.join(few)}")

    punct_text = "".join(_section_text(prompt_set, "punctuation"))
    weak = [c for c in PUNCTUATION if punct_text.count(c) < p["glyph_repeats"]]
    if weak:
        problems.append(f"punctuation marks written fewer than {p['glyph_repeats']} times: {' '.join(weak)}")

    greek_tokens: Counter = Counter(t for line in _section_text(prompt_set, "greek") for t in line.split())
    greek_missing = [g for g in GREEK_LOWER + GREEK_UPPER + MATH_SYMBOLS if greek_tokens[g] < p["glyph_repeats"]]
    if greek_missing:
        problems.append(f"Greek/math glyphs written fewer than {p['glyph_repeats']} times: {' '.join(greek_missing)}")

    tamil_tokens: Counter = Counter(t for line in _section_text(prompt_set, "tamil") for t in line.split())
    letters = tamil_letters()
    tamil_missing = [t for t in letters if tamil_tokens[t] < p["glyph_repeats"]]
    if len(set(letters)) != 247:
        problems.append(f"internal: expected 247 distinct Tamil letters, built {len(set(letters))}")
    if tamil_missing:
        problems.append(f"{len(tamil_missing)} Tamil letters written fewer than {p['glyph_repeats']} times: {' '.join(tamil_missing[:20])}")

    over = [c["id"] for c in prompt_set["chunks"] if c["units"] > 2 * p["chunk_units"]]
    if over:
        problems.append(f"chunks far longer than the target: {' '.join(over)}")

    by_section: Counter = Counter(c["section"] for c in prompt_set["chunks"])
    return {
        "problems": problems,
        "stats": {
            "chunks": len(prompt_set["chunks"]),
            "chunks_by_section": dict(by_section),
            "fillers": len(prompt_set["fillers"]),
            "min_pair_count": min(pair_counts[pp] for pp in ALL_PAIRS),
            "tamil_letters": len(set(letters)),
            "total_units": prompt_set["total_units"],
            "estimated_minutes": prompt_set["estimated_minutes"],
        },
    }


# --- load / save --------------------------------------------------------------

def prompt_path(set_id: str) -> Path:
    if not _SET_ID_RE.match(set_id):
        raise ValueError(f"invalid prompt set id {set_id!r}")
    return PROMPT_DIR / f"{set_id}.json"


def load_prompt_set(set_id: str) -> dict:
    return json.loads(prompt_path(set_id).read_text(encoding="utf-8"))


def save_prompt_set(prompt_set: dict) -> Path:
    path = prompt_path(prompt_set["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prompt_set, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    from ..config import load_config

    parser = argparse.ArgumentParser(prog="python -m laxthya_ink.capture.prompts")
    parser.add_argument("--check", action="store_true",
                        help="do not write; verify the committed file is current and fully covered")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = load_config()
    built = build_prompt_set(config)
    report = check_coverage(built, config)
    for problem in report["problems"]:
        print("PROBLEM:", problem)
    print("stats:", json.dumps(report["stats"], ensure_ascii=False))

    if args.check:
        committed = load_prompt_set(built["id"])
        if committed != built:
            print(f"FAIL: {prompt_path(built['id'])} is out of date - run without --check to regenerate")
            return 1
        return 1 if report["problems"] else 0
    if report["problems"]:
        return 1
    print("wrote", save_prompt_set(built))
    return 0


if __name__ == "__main__":
    sys.exit(main())
