"""The control text every writer is asked to write, split into chunks, with a coverage check.

Decisions this implements (docs/PROJECT_PLAN.md): tiered coverage with the core session
first; English + digits + the full Greek alphabet + math symbols + all 247 Tamil letters;
English built from **real common words only** (no made-up filler strings) so that every
*natural* letter pair is covered; chunks of about a minute so each can be sent to the laptop
as soon as it is written.

A letter pair is *natural* if at least `prompts.natural_min_words` words of the word list
contain it. Natural pairs are covered `prompts.pair_min` times by the fewest letters the
greedy search can find. Pairs that real English almost never uses (bq, dq, pz...) are left
to the extended session and listed in the output as `deferred_pairs`.

The word list is not part of the repository (its licence allows research use but says
nothing clear about redistribution): fetch it with `python tools/fetch_wordlist.py`.
Only the generated text, with the list of natural pairs it was built to cover, is
committed, so the coverage check needs no word list.

Pure and deterministic: the same config and word list always give the same text
(`prompts.seed`). `python -m laxthya_ink.capture.prompts` rebuilds `prompts/<id>.json`;
`--check` verifies the committed file is covered (and current, if the word list is present).

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

from ..exceptions import WordListError

PACKAGE_DIR = Path(__file__).resolve().parent
PROMPT_DIR = PACKAGE_DIR / "prompts"

FORMAT_VERSION = 2
STYLE = "natural"                     # the core set is the writer's natural hand

LOWER = string.ascii_lowercase
ALL_PAIRS = [a + b for a in LOWER for b in LOWER]
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


# --- English: real words that cover the natural letter pairs -----------------

def _pairs(word: str) -> list[str]:
    return [word[i:i + 2] for i in range(len(word) - 1)]


def load_words(path: Path) -> list[str]:
    """A frequency-ordered word list: lowercase a-z only, unique, most frequent first.

    Raises `WordListError` if the file is missing or holds no usable word.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise WordListError(
            f"cannot read the word list {path} ({exc.strerror or exc}); "
            f"download it with: python tools/fetch_wordlist.py"
        ) from exc
    seen: dict[str, None] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue                                      # comment line
        for w in line.split():
            if len(w) >= 2 and all(c in LOWER for c in w):
                seen.setdefault(w)
    if not seen:
        raise WordListError(f"{path} contains no usable words (lowercase a-z, one or more per line)")
    return list(seen)


_VOWELS = "aeiouy"


def is_plausible_word(word: str, max_consonant_run: int) -> bool:
    """A word a person would write as a word: it has a vowel and no long run of consonants.

    This drops the acronyms and brand codes a web-derived list is full of (gtk, wto, xhtml).
    """
    if not any(c in _VOWELS for c in word):
        return False
    run = 0
    for c in word:
        run = 0 if c in _VOWELS else run + 1
        if run > max_consonant_run:
            return False
    return True


def candidate_pool(words: list[str], config: dict) -> list[str]:
    """The words the greedy search may pick from: the most frequent `pool_size`, long enough,
    and plausible as words."""
    p = config["prompts"]
    return [w for w in words[: p["pool_size"]]
            if len(w) >= p["min_word_length"] and is_plausible_word(w, p["max_consonant_run"])]


def natural_pairs(pool: list[str], min_words: int) -> list[str]:
    """Letter pairs that occur in at least `min_words` different words of the pool, sorted."""
    support: Counter = Counter()
    for w in pool:
        support.update(set(_pairs(w)))
    return sorted(p for p in ALL_PAIRS if support[p] >= min_words)


def pick_words(pool: list[str], needed: list[str], pair_min: int) -> tuple[list[str], Counter]:
    """Greedily choose words until every needed pair appears `pair_min` times.

    Each step takes the word that adds the most still-missing pair occurrences per letter
    written (shorter and more useful first); ties go to the more frequent word. Returns
    (chosen words, pair counts over them). Stops early if some pair cannot be reached.
    """
    deficit = {p: pair_min for p in needed}
    useful = {w: Counter(p for p in _pairs(w) if p in deficit) for w in pool}
    counts: Counter = Counter()
    chosen: list[str] = []
    remaining = [w for w in pool if useful[w]]
    while any(d > 0 for d in deficit.values()):
        best, best_key = None, (0.0, 0)
        for index, w in enumerate(remaining):
            gain = sum(min(deficit[p], c) for p, c in useful[w].items() if deficit[p] > 0)
            if gain == 0:
                continue
            key = (gain / len(w), gain)
            if best is None or key > best_key:               # strict: earlier (more frequent) word wins ties
                best, best_key = (index, w), key
        if best is None:
            break
        index, word = best
        chosen.append(word)
        remaining.pop(index)
        counts.update(_pairs(word))
        for p in useful[word]:
            if deficit[p] > 0:
                deficit[p] -= useful[word][p]
    return chosen, counts


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


def _english(words: list[str], config: dict) -> tuple[list[str], list[str], list[str]]:
    """(chosen words, natural pairs, deferred pairs) for the given frequency-ordered word list."""
    p = config["prompts"]
    pool = candidate_pool(words, config)
    natural = natural_pairs(pool, p["natural_min_words"])
    chosen, counts = pick_words(pool, natural, p["pair_min"])
    short = [pair for pair in natural if counts[pair] < p["pair_min"]]
    if short:
        raise WordListError(f"the word list cannot cover {len(short)} natural pairs {p['pair_min']} times: {' '.join(short[:15])}")
    return chosen, natural, [pair for pair in ALL_PAIRS if pair not in set(natural)]


def _sections(config: dict, chosen: list[str]) -> list[dict]:
    """Build every section's lines from the chosen English words."""
    p = config["prompts"]
    w = p["units_per_glyph"]
    rng = random.Random(p["seed"])
    line_units, repeats = p["line_units"], p["glyph_repeats"]

    words = list(chosen)
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
         "lines": latin(digit_tokens(), w["digit"])},
        {"id": "punctuation", "script": "symbol", "intro": "Punctuation and signs.",
         "lines": _text_lines(punct_lines, w["symbol"])},
        {"id": "greek", "script": "greek", "intro": "Greek letters and math signs, one at a time.",
         "lines": _pack(greek_tokens, lambda t: w["greek"], 0.0, line_units)},
        {"id": "greek-use", "script": "greek", "intro": "Engineering notation.",
         "lines": _text_lines(greek_use, w["greek"])},
        {"id": "tamil", "script": "tamil", "intro": "Tamil letters, one at a time. Write each as you normally would.",
         "lines": _pack(_shuffled_repeats(tamil_letters(), repeats, rng), lambda t: w["tamil"], 0.0, line_units)},
    ]


def build_prompt_set(config: dict, words: list[str] | None = None, set_id: str | None = None) -> dict:
    """Generate the whole control text as a JSON-ready dict.

    `words` is a frequency-ordered word list; by default it is read from `prompts.word_list`.
    """
    from ..config import resolve_path

    p = config["prompts"]
    set_id = set_id or config["capture"]["prompt_set_id"]
    if not _SET_ID_RE.match(set_id):
        raise ValueError(f"prompt set id must be lowercase letters, digits and dashes, got {set_id!r}")
    if words is None:
        words = load_words(resolve_path(p["word_list"]))
    chosen, natural, deferred = _english(words, config)
    sections = _sections(config, chosen)

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
        "params": {k: p[k] for k in ("seed", "pair_min", "natural_min_words", "pool_size", "min_word_length",
                                     "max_consonant_run", "glyph_repeats", "chunk_units", "line_units")},
        "word_source": Path(p["word_list"]).name,
        "english_words": len(chosen),
        "natural_pairs": natural,
        "deferred_pairs": deferred,
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
    `{"problems": [...], "stats": {...}}`; no problems means fully covered.

    Needs no word list: the natural pairs the text was built to cover are stored in it.
    """
    p = config["prompts"]
    problems: list[str] = []

    required = prompt_set.get("natural_pairs", [])
    if not required:
        problems.append("the prompt set lists no natural letter pairs, so English coverage cannot be checked")
    pair_counts: Counter = Counter()
    for line in _section_text(prompt_set, "en-words"):
        for word in line.split():
            pair_counts.update(_pairs(word))
    short = [pp for pp in required if pair_counts[pp] < p["pair_min"]]
    if short:
        problems.append(f"{len(short)} natural letter pairs appear fewer than {p['pair_min']} times: {' '.join(short[:20])}")

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
            "english_words": prompt_set.get("english_words"),
            "natural_pairs": len(required),
            "deferred_pairs": len(prompt_set.get("deferred_pairs", [])),
            "min_natural_pair_count": min((pair_counts[pp] for pp in required), default=0),
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
                        help="do not write; verify the committed file is covered (and current, if the word list is present)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    config = load_config()
    set_id = config["capture"]["prompt_set_id"]

    if args.check:
        committed = load_prompt_set(set_id)
        report = check_coverage(committed, config)
        for problem in report["problems"]:
            print("PROBLEM:", problem)
        print("stats:", json.dumps(report["stats"], ensure_ascii=False))
        try:
            current = build_prompt_set(config)
        except WordListError as exc:
            print(f"note: not comparing with a fresh build ({exc})")
            return 1 if report["problems"] else 0
        if current != committed:
            print(f"FAIL: {prompt_path(set_id)} is out of date - run without --check to regenerate")
            return 1
        return 1 if report["problems"] else 0

    try:
        built = build_prompt_set(config)
    except WordListError as exc:
        print("FAIL:", exc)
        return 1
    report = check_coverage(built, config)
    for problem in report["problems"]:
        print("PROBLEM:", problem)
    print("stats:", json.dumps(report["stats"], ensure_ascii=False))
    if report["problems"]:
        return 1
    print("wrote", save_prompt_set(built))
    return 0


if __name__ == "__main__":
    sys.exit(main())
