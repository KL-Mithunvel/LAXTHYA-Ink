import json

import pytest

from laxthya_ink.exceptions import StrokeDataError
from laxthya_ink.strokes import load_strokes, parse_lines


def test_sample_file_loads(sample_strokes_path):
    lines = load_strokes(sample_strokes_path)
    assert len(lines) == 2
    assert [len(line) for line in lines] == [2, 2]
    first = lines[1][1].points[0]
    assert (first.x, first.y, first.t, first.pressure) == (2.0, 0.0, 0.0, 0.4)
    assert lines[0][0].points[0].t is None             # optional fields default to None


def _doc(**overrides):
    doc = {"version": 1, "lines": [{"strokes": [[[0, 0], [1, 1]]]}]}
    doc.update(overrides)
    return doc


@pytest.mark.parametrize("doc,fragment", [
    ([], "JSON object"),
    (_doc(version=2), "version"),
    (_doc(lines=[]), "non-empty"),
    (_doc(lines=[{"nope": 1}]), "'strokes'"),
    (_doc(lines=[{"strokes": [[]]}]), "at least one point"),
    (_doc(lines=[{"strokes": [[[1]]]}]), "[x, y"),
    (_doc(lines=[{"strokes": [[["a", 1]]]}]), "finite numbers"),
    (_doc(lines=[{"strokes": [[[1, float("nan")]]]}]), "finite numbers"),
    (_doc(lines=[{"strokes": [[[True, 1]]]}]), "finite numbers"),
])
def test_bad_documents_rejected(doc, fragment):
    with pytest.raises(StrokeDataError, match=fragment.replace("[", r"\[")):
        parse_lines(doc)


def test_invalid_json_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(StrokeDataError, match="not valid JSON"):
        load_strokes(bad)


def test_roundtrip_through_file(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(_doc()), encoding="utf-8")
    assert load_strokes(path)[0][0].points[1].y == 1.0
