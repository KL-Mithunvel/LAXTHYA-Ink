import string
from collections import Counter

import pytest

from laxthya_ink.capture import prompts as P
from laxthya_ink.config import load_config, resolve_path
from laxthya_ink.exceptions import WordListError

WORD_LIST = resolve_path(load_config()["prompts"]["word_list"])
needs_word_list = pytest.mark.skipif(
    not WORD_LIST.exists(), reason="word list not downloaded: run python tools/fetch_wordlist.py")

#: a small frequency-ordered list with enough variety to cover some pairs several times
SMALL_WORDS = ("there which would other about their these thing think those where right never every still after "
               "water small house world great three never light might night sight right flight bright fright "
               "quick quiet queen quote square equal liquid until under above again along among around").split()


@pytest.fixture
def small_config(config):
    config["prompts"].update(pool_size=1000, natural_min_words=2, min_word_length=4, max_consonant_run=3, pair_min=2)
    return config


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


# --- real words, natural pairs ----------------------------------------------------

@pytest.mark.parametrize("word,ok", [
    ("rhythm", True), ("strengths", False),        # 'y' is a vowel; "ngths" is five consonants in a row
    ("gtk", False), ("xhtml", False), ("usb", True), ("bmw", False), ("queen", True), ("zzz", False),
])
def test_plausible_words_have_a_vowel_and_no_long_consonant_run(word, ok):
    assert P.is_plausible_word(word, 3) is ok


def test_pool_is_the_most_frequent_long_plausible_words(small_config):
    small_config["prompts"]["pool_size"] = 6
    words = ["the", "gtk", "about", "their", "usb", "which", "other", "there"]
    assert P.candidate_pool(words, small_config) == ["about", "their", "which"]        # first 6, 4+ letters, no gtk


def test_natural_pairs_need_support_from_several_different_words():
    pool = ["thing", "think", "this", "zzzy", "quit"]
    # 'th' and 'hi' are each in thing, think and this; 'in' is only in two words, 'zz' in one
    assert P.natural_pairs(pool, 3) == ["hi", "th"]
    assert P.natural_pairs(pool, 2) == ["hi", "in", "th"]


def test_natural_pairs_counts_words_not_occurrences():
    assert P.natural_pairs(["aaaa", "aaab"], 2) == ["aa"]       # 'aa' appears in both words; once per word counts
    assert P.natural_pairs(["aaaa"], 2) == []                  # many occurrences in ONE word is still one word


def test_pick_words_reaches_every_needed_pair_with_the_fewest_letters_it_can():
    pool = ["thing", "think", "there", "which", "quick", "queen"]
    needed = ["th", "qu"]
    chosen, counts = P.pick_words(pool, needed, 2)
    assert all(counts[p] >= 2 for p in needed)
    assert len(chosen) == 4 and len(set(chosen)) == len(chosen)         # two words for 'th', two for 'qu'; 'which' is useless


def test_pick_words_prefers_the_more_frequent_word_on_a_tie():
    chosen, _ = P.pick_words(["abxy", "abzw"], ["ab"], 1)
    assert chosen == ["abxy"]                                  # equal gain per letter: the earlier (more frequent) one


def test_pick_words_stops_when_a_pair_is_unreachable():
    chosen, counts = P.pick_words(["abab", "cdcd"], ["ab", "zz"], 1)
    assert chosen == ["abab"] and counts["zz"] == 0


def test_load_words_reads_a_frequency_list_and_skips_noise(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("# comment\nthe of AND x1 e-mail\nabout\nthe\n", encoding="utf-8")
    assert P.load_words(f) == ["the", "of", "about"]           # lowercase a-z only, 2+ letters, no duplicates


def test_a_missing_word_list_says_how_to_get_it(tmp_path):
    with pytest.raises(WordListError, match="fetch_wordlist"):
        P.load_words(tmp_path / "nope.txt")
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(WordListError, match="no usable words"):
        P.load_words(empty)


def test_building_from_a_small_list_covers_what_it_says_it_covers(small_config):
    ps = P.build_prompt_set(small_config, words=SMALL_WORDS)
    assert ps["natural_pairs"] and set(ps["natural_pairs"]).isdisjoint(ps["deferred_pairs"])
    assert len(ps["natural_pairs"]) + len(ps["deferred_pairs"]) == 676
    assert P.check_coverage(ps, small_config)["problems"] == []


def test_a_list_too_poor_to_cover_its_own_natural_pairs_is_an_error(small_config):
    small_config["prompts"]["min_word_length"] = 4
    with pytest.raises(WordListError):
        P._english(["abab"], {**small_config, "prompts": {**small_config["prompts"], "pair_min": 2, "natural_min_words": 1}})


# --- the committed set (needs no word list) -----------------------------------------

@pytest.fixture(scope="module")
def committed():
    config = load_config()
    return config, P.load_prompt_set(config["capture"]["prompt_set_id"])


def test_committed_set_passes_its_own_coverage_check(committed):
    config, ps = committed
    report = P.check_coverage(ps, config)
    assert report["problems"] == []
    assert report["stats"]["min_natural_pair_count"] >= config["prompts"]["pair_min"]
    assert report["stats"]["tamil_letters"] == 247


def test_committed_english_is_real_words_only(committed):
    _, ps = committed
    words = [w for c in ps["chunks"] if c["section"] == "en-words" for line in c["lines"] for w in line.split()]
    assert len(words) == ps["english_words"] and len(set(words)) == len(words)
    assert all(w.isascii() and w.islower() and w.isalpha() for w in words)
    assert all(P.is_plausible_word(w, ps["params"]["max_consonant_run"]) for w in words)     # no gtk, wto, xhtml...
    assert all(len(w) >= ps["params"]["min_word_length"] for w in words)


def test_natural_and_deferred_pairs_partition_all_676_pairs(committed):
    _, ps = committed
    assert sorted(ps["natural_pairs"] + ps["deferred_pairs"]) == sorted(P.ALL_PAIRS)
    assert {"th", "he", "in", "er", "qu", "ck", "ng", "sh"} <= set(ps["natural_pairs"])
    assert {"bq", "dq", "pz"}.isdisjoint(ps["natural_pairs"])


def test_chunks_have_stable_ids_one_section_each_and_sensible_size(committed):
    config, ps = committed
    ids = [c["id"] for c in ps["chunks"]]
    assert ids == [f"{ps['id']}-{i:03d}" for i in range(1, len(ids) + 1)]
    sections = [c["section"] for c in ps["chunks"]]
    assert sections == sorted(sections, key=sections.index)           # contiguous: never interleaved
    assert all(c["units"] <= 2 * config["prompts"]["chunk_units"] for c in ps["chunks"])
    assert all(c["lines"] for c in ps["chunks"])


def test_only_the_first_chunk_of_a_section_has_an_intro(committed):
    _, ps = committed
    seen = set()
    for c in ps["chunks"]:
        assert bool(c["intro"]) == (c["section"] not in seen)
        seen.add(c["section"])


def test_capitals_and_punctuation_are_all_present(committed):
    _, ps = committed
    caps = " ".join(l for c in ps["chunks"] if c["section"] == "en-capitals" for l in c["lines"])
    assert all(any(w.startswith(L) for w in caps.split()) for L in string.ascii_uppercase)
    punct = "".join(l for c in ps["chunks"] if c["section"] == "punctuation" for l in c["lines"])
    assert all(m in punct for m in P.PUNCTUATION)


def test_the_check_notices_a_missing_glyph(committed):
    config, ps = committed
    broken = {**ps, "chunks": [dict(c, lines=[l.replace("ψ", "") for l in c["lines"]]) if c["section"] == "greek" else c
                               for c in ps["chunks"]]}
    assert any("ψ" in problem for problem in P.check_coverage(broken, config)["problems"])


def test_the_check_notices_a_missing_natural_pair(committed):
    config, ps = committed
    pair = ps["natural_pairs"][0]
    broken = {**ps, "chunks": [dict(c, lines=[" ".join(w for w in l.split() if pair not in w) for l in c["lines"]])
                               if c["section"] == "en-words" else c for c in ps["chunks"]]}
    assert any("natural letter pairs" in problem for problem in P.check_coverage(broken, config)["problems"])


def test_the_check_refuses_a_set_that_lists_no_natural_pairs(committed):
    config, ps = committed
    assert any("no natural letter pairs" in p for p in P.check_coverage({**ps, "natural_pairs": []}, config)["problems"])


def test_set_ids_are_validated_before_touching_the_filesystem():
    for bad in ("../x", "A", "", "a/b"):
        with pytest.raises(ValueError):
            P.prompt_path(bad)


# --- regenerating from the real word list (skipped where it is not downloaded) -----------

@needs_word_list
def test_committed_file_matches_what_the_builder_makes_from_the_real_list(committed):
    """If this fails the config or word list changed: run `python -m laxthya_ink.capture.prompts`."""
    config, ps = committed
    assert P.build_prompt_set(config) == ps


@needs_word_list
def test_build_is_deterministic_and_a_new_seed_changes_order_not_coverage(committed):
    config, ps = committed
    other = {**config, "prompts": {**config["prompts"], "seed": 1}}
    again = P.build_prompt_set(other)
    assert again["chunks"][0]["lines"] != ps["chunks"][0]["lines"]
    assert P.check_coverage(again, other)["problems"] == []
