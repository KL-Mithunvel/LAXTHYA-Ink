import copy
from pathlib import Path

import pytest

from laxthya_ink.config import load_config

SAMPLE_STROKES = Path(__file__).parent / "data" / "sample_strokes.json"


@pytest.fixture
def config() -> dict:
    """A private copy of the committed default configuration (safe to mutate)."""
    return copy.deepcopy(load_config())


@pytest.fixture
def sample_strokes_path() -> Path:
    return SAMPLE_STROKES
