import string
from collections import Counter

import pytest

from laxthya_ink.capture import prompts as P


def _pair_counts(chunks):
    counts = Counter()
    for c in chunks:
        if c["section"] == "en-words":
            for line in c["lines"]:
                for word in line.split():
                    counts.update(P._pairs(word))
    return counts


@pytest.fixture(scope="module")
def built(request):
    from laxthya_ink.config import load_config
    config = load_config()
    return config, P.build_prompt_set(config)


# --- the content itself ------------------------------------------------------

def test_tamil_has_exactly_247_distinct_letters():
    letters = P.tamil_letters()
    assert len(letters) == 247 == len(set(letters))
    assert letters[:12] == list(P.TAMIL_VOWELS) and letters[12] == "ஃ"
    assert letters[13] == "க்"                                        # consonants carry the pulli
    assert "கொ" in letters and "ழௌ" in letters                      # two of the 216 combined letters


def test_de_bruijn_digits_cover_every_pair_exactly_once():
    stream = P.de_bruijn_digits()
    pairs = Counter(stream[i:i + 2] for i in range(len(stream) - 1))
    assert len(stream) == 101
    assert set(pairs) == {f"{a}{b}" for a in range(10) for b in range(10)}
    assert set(pairs.values()) == {1}


def test_digit_tokens_overlap_so_no_pair_falls_between_them():
    tokens = P.digit_tokens()
    pairs = {t[i:i + 2] for t in tokens for i in range(len(t) - 1)}
    assert len(pairs) == 100 and all(len(t) == 5 for t in tokens)


def test_word_list_is_clean():
    words = P.load_words()
    assert len(words) > 500 and all(w.isascii() and w.islower() and w.isalpha() for w in words)
    assert len(words) == len(set(words))


def test_every_pair_is_either_covered_by_words_or_gets_a_filler():
    chosen, counts = P.pick_words(P.load_words(), 2)
    fillers = P.make_fillers(counts, 2)
    for f in fillers:
        counts.update(P._pairs(f))
    assert all(counts[p] >= 2 for p in P.ALL_PAIRS)
    assert all(any(c in "aeiouy" for c in f) for f in fillers)       # every filler can be pronounced


def test_fillers_cover_what_they_were_asked_to_even_when_a_pair_is_needed_twice():
    fillers = P.make_fillers(Counter(), 2)                            # nothing covered yet: worst case
    counts = Counter()
    for f in fillers:
        counts.update(P._pairs(f))
    assert all(counts[p] >= 2 for p in P.ALL_PAIRS)


def test_pick_words_stops_when_nothing_adds_coverage():
    chosen, counts = P.pick_words(["ab", "ab", "ab", "cd"], 1)
    assert chosen == ["ab", "cd"] and counts["ab"] == 1


# --- the generated set ---------------------------------------------------------

def test_generated_set_passes_its_own_coverage_check(built):
    config, ps = built
    report = P.check_coverage(ps, config)
    assert report["problems"] == []
    assert report["stats"]["min_pair_count"] >= config["prompts"]["pair_min"]
    assert report["stats"]["tamil_letters"] == 247


def test_committed_file_matches_what_the_builder_makes(built):
    """If this fails the config or word list changed: run `python -m laxthya_ink.capture.prompts`."""
    config, ps = built
    assert P.load_prompt_set(config["capture"]["prompt_set_id"]) == ps


def test_build_is_deterministic(built):
    config, ps = built
    assert P.build_prompt_set(config) == ps


def test_different_seed_changes_the_order_not_the_coverage(built):
    config, ps = built
    other = {**config, "prompts": {**config["prompts"], "seed": 1}}
    again = P.build_prompt_set(other)
    assert again["chunks"][0]["lines"] != ps["chunks"][0]["lines"]
    assert P.check_coverage(again, other)["problems"] == []


def test_chunks_have_stable_ids_one_section_each_and_sensible_size(built):
    config, ps = built
    ids = [c["id"] for c in ps["chunks"]]
    assert ids == [f"core-v1-{i:03d}" for i in range(1, len(ids) + 1)]
    sections = [c["section"] for c in ps["chunks"]]
    assert sections == sorted(sections, key=sections.index)           # contiguous: never interleaved
    target = config["prompts"]["chunk_units"]
    assert all(c["units"] <= 2 * target for c in ps["chunks"])
    assert all(c["lines"] for c in ps["chunks"])


def test_only_the_first_chunk_of_a_section_has_an_intro(built):
    _, ps = built
    seen = set()
    for c in ps["chunks"]:
        assert bool(c["intro"]) == (c["section"] not in seen)
        seen.add(c["section"])


def test_capitals_digits_and_punctuation_are_all_present(built):
    _, ps = built
    caps = " ".join(l for c in ps["chunks"] if c["section"] == "en-capitals" for l in c["lines"])
    assert all(any(w.startswith(L) for w in caps.split()) for L in string.ascii_uppercase)
    punct = "".join(l for c in ps["chunks"] if c["section"] == "punctuation" for l in c["lines"])
    assert all(m in punct for m in P.PUNCTUATION)


def test_the_check_notices_a_missing_glyph(built):
    config, ps = built
    broken = {**ps, "chunks": [dict(c, lines=[l.replace("ψ", "") for l in c["lines"]]) if c["section"] == "greek" else c
                               for c in ps["chunks"]]}
    assert any("ψ" in problem for problem in P.check_coverage(broken, config)["problems"])


def test_the_check_notices_a_missing_letter_pair(built):
    config, ps = built
    broken = {**ps, "chunks": [dict(c, lines=[l.replace("qu", "ku") for l in c["lines"]]) if c["section"] == "en-words" else c
                               for c in ps["chunks"]]}
    assert any("letter pairs" in problem for problem in P.check_coverage(broken, config)["problems"])


def test_set_ids_are_validated_before_touching_the_filesystem():
    for bad in ("../x", "A", "", "a/b"):
        with pytest.raises(ValueError):
            P.prompt_path(bad)
