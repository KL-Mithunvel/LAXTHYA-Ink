import copy

import pytest
import yaml

from laxthya_ink.config import DEFAULT_CONFIG_PATH, _validate, load_config


def test_default_config_loads_and_pen_is_uncalibrated():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg["printer"]["baud"] == 115200
    # Dev Rule 4: the committed default must never claim a calibrated pen.
    assert cfg["pen"]["down_z_calibrated"] is False


def test_local_override_is_deep_merged(tmp_path):
    base = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text(
        yaml.safe_dump({"printer": {"port": "COM7"}, "pen": {"down_z": 1.25}}), encoding="utf-8"
    )
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg["printer"]["port"] == "COM7"
    assert cfg["printer"]["baud"] == 115200          # untouched sibling survives
    assert cfg["pen"]["down_z"] == 1.25


def test_missing_key_is_named(config):
    del config["pen"]["lift_mm"]
    with pytest.raises(KeyError, match="pen.lift_mm"):
        _validate(config)


@pytest.mark.parametrize("section,key,value", [
    ("motion", "draw_feed", 0),
    ("pen", "lift_mm", -1),
    ("paper", "width_mm", "wide"),
    ("pen", "down_z_calibrated", "yes"),
    ("printer", "baud", True),
])
def test_bad_values_rejected(config, section, key, value):
    config[section][key] = value
    with pytest.raises(ValueError, match=f"{section}.{key}"):
        _validate(config)


def test_safe_z_must_clear_pen_up(config):
    cfg = copy.deepcopy(config)
    cfg["park"]["safe_z"] = cfg["pen"]["down_z"] + cfg["pen"]["lift_mm"] - 0.5
    with pytest.raises(ValueError, match="safe_z"):
        _validate(cfg)


def test_down_z_below_min_z_rejected(config):
    config["pen"]["min_z"] = 2.0
    config["pen"]["down_z"] = 1.0
    with pytest.raises(ValueError, match="min_z"):
        _validate(config)
