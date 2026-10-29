"""Configuration loading: `config.yaml` + an optional git-ignored `config.local.yaml`.

`config.local.yaml` sits next to `config.yaml` and is deep-merged over it at load
time, so machine-specific values (real COM port, measured pen offset and pen-down
Z) never touch the tracked file.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

#: (section, key) pairs that must be present and numeric (int/float, not bool).
_NUMERIC_KEYS: tuple[tuple[str, str], ...] = (
    ("printer", "baud"), ("printer", "ack_timeout_s"), ("printer", "connect_settle_s"),
    ("machine", "x_max"), ("machine", "y_max"), ("machine", "z_max"),
    ("paper", "origin_x"), ("paper", "origin_y"), ("paper", "width_mm"), ("paper", "height_mm"),
    ("pen", "offset_x"), ("pen", "offset_y"), ("pen", "down_z"), ("pen", "lift_mm"),
    ("pen", "min_z"), ("pen", "down_dwell_ms"),
    ("writing", "scale_mm_per_unit"), ("writing", "line_spacing_mm"),
    ("writing", "simplify_tolerance_mm"), ("writing", "min_point_spacing_mm"),
    ("motion", "draw_feed"), ("motion", "travel_feed"), ("motion", "z_feed"),
    ("park", "x"), ("park", "y"), ("park", "safe_z"),
    ("sim", "contact_tolerance_mm"), ("sim", "command_delay_s"),
)

#: (section, key) pairs that must be present and boolean.
_BOOL_KEYS: tuple[tuple[str, str], ...] = (
    ("pen", "down_z_calibrated"),
    ("start", "home"),
    ("gcode", "use_line_numbers"),
)

#: numeric keys that must be strictly positive
_POSITIVE_KEYS: tuple[tuple[str, str], ...] = (
    ("printer", "baud"), ("printer", "ack_timeout_s"),
    ("machine", "x_max"), ("machine", "y_max"), ("machine", "z_max"),
    ("paper", "width_mm"), ("paper", "height_mm"),
    ("pen", "lift_mm"),
    ("writing", "scale_mm_per_unit"), ("writing", "line_spacing_mm"),
    ("motion", "draw_feed"), ("motion", "travel_feed"), ("motion", "z_feed"),
)

#: numeric keys that must be >= 0
_NON_NEGATIVE_KEYS: tuple[tuple[str, str], ...] = (
    ("printer", "connect_settle_s"), ("pen", "min_z"), ("pen", "down_dwell_ms"),
    ("writing", "simplify_tolerance_mm"), ("writing", "min_point_spacing_mm"),
    ("sim", "contact_tolerance_mm"), ("sim", "command_delay_s"),
)


def _deep_merge(base: dict, over: dict) -> dict:
    """Return a new dict: `over` merged onto `base`, recursing into nested dicts."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _require(config: dict, section: str, key: str) -> Any:
    if not isinstance(config.get(section), dict) or key not in config[section]:
        raise KeyError(f"config is missing required key: {section}.{key}")
    return config[section][key]


def _validate(config: dict) -> None:
    port = _require(config, "printer", "port")
    if not isinstance(port, str) or not port.strip():
        raise ValueError(f"config printer.port must be a non-empty string, got {port!r}")

    for section, key in _NUMERIC_KEYS:
        value = _require(config, section, key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"config {section}.{key} must be a number, got {value!r}")

    for section, key in _BOOL_KEYS:
        value = _require(config, section, key)
        if not isinstance(value, bool):
            raise ValueError(f"config {section}.{key} must be true or false, got {value!r}")

    for section, key in _POSITIVE_KEYS:
        if config[section][key] <= 0:
            raise ValueError(f"config {section}.{key} must be > 0, got {config[section][key]!r}")
    for section, key in _NON_NEGATIVE_KEYS:
        if config[section][key] < 0:
            raise ValueError(f"config {section}.{key} must be >= 0, got {config[section][key]!r}")

    pen, park, machine = config["pen"], config["park"], config["machine"]
    pen_up_z = pen["down_z"] + pen["lift_mm"]
    if pen["down_z"] < pen["min_z"]:
        raise ValueError(
            f"config pen.down_z ({pen['down_z']}) must be >= pen.min_z ({pen['min_z']})"
        )
    if park["safe_z"] < pen_up_z:
        raise ValueError(
            f"config park.safe_z ({park['safe_z']}) must clear the pen-up Z ({pen_up_z})"
        )
    if park["safe_z"] > machine["z_max"]:
        raise ValueError(
            f"config park.safe_z ({park['safe_z']}) exceeds machine.z_max ({machine['z_max']})"
        )
    if not (0 <= park["x"] <= machine["x_max"] and 0 <= park["y"] <= machine["y_max"]):
        raise ValueError("config park.x / park.y must lie inside the machine volume")


def local_config_path(path: str | Path | None = None) -> Path:
    """Where `config.local.yaml` lives for a given base `config.yaml` path."""
    base_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    return base_path.with_name("config.local.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the base config, deep-merge `config.local.yaml` if present, validate.

    `path` overrides the base file location (mainly for tests).
    """
    base_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with open(base_path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    local_path = local_config_path(base_path)
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
        config = _deep_merge(config, local)

    _validate(config)
    return config
