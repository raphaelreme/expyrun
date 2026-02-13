# tests/test_config_parser.py
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import pytest

from expyrun.config import (
    Parser,
    config_flatten,
    config_unflatten,
    convert_if_possible,
    load_config,
    merge,
    save_config,
)

if TYPE_CHECKING:
    from expyrun.config import (
        Config,
    )

###########
# FLATTEN #
###########


def test_flatten_then_unflatten_roundtrip():
    cfg: Config = {
        "hello": {
            "world": True,
            "values": {"train": [1, 2, 3], "test": 3.5},
        }
    }
    flat = config_flatten(cfg)
    assert flat == {
        "hello.world": True,
        "hello.values.train": [1, 2, 3],
        "hello.values.test": 3.5,
    }

    unflat = config_unflatten(flat)
    assert unflat == cfg


def test_unflatten_raises_on_overwrite_value():
    # "a" is already a value, cannot also be a dict parent for "a.b"
    with pytest.raises(ValueError, match=r"Can't override it"):
        config_unflatten({"a": 1, "a.b": 2})


def test_flatten_raises_on_overwrite_value():
    # "a" is already a value, cannot also be a dict parent for "a.b"
    with pytest.raises(ValueError, match=r"Can't override it"):
        config_flatten({"a": {"b": 1}, "a.b": 2})


#########
# MERGE #
#########


def test_merge_pass_allows_new_keys_without_warning():
    cfg1: Config = {"a": 1}
    cfg2: Config = {"b": 2}
    out = merge(cfg1, cfg2, new_key_policy="pass")
    assert out == {"a": 1, "b": 2}
    assert cfg1 == {"a": 1}
    assert cfg2 == {"b": 2}


def test_merge_warn_warns_on_new_keys():
    cfg1: Config = {"a": 1}
    cfg2: Config = {"b": 2}
    with pytest.warns(UserWarning, match=r"Adding new key"):
        out = merge(cfg1, cfg2, new_key_policy="warn")
    assert out == {"a": 1, "b": 2}


def test_merge_raise_raises_on_new_keys():
    cfg1: Config = {"a": 1}
    cfg2: Config = {"b": 2}
    with pytest.raises(KeyError, match=r"Unexpected key"):
        merge(cfg1, cfg2, new_key_policy="raise")


def test_merge_allows_dunder_keys_even_with_raise():
    cfg1: Config = {"a": 1}
    cfg2: Config = {"__run__": {"__main__": "hello:main"}}
    out = merge(cfg1, cfg2, new_key_policy="raise")
    assert out["__run__"] == {"__main__": "hello:main"}


def test_merge_warns_on_type_change_and_replaces():
    cfg1: Config = {"a": 1}
    cfg2: Config = {"a": "one"}
    with pytest.warns(UserWarning, match=r"overloaded with a different type"):
        out = merge(cfg1, cfg2, new_key_policy="raise")
    assert out["a"] == "one"


def test_merge_recursively_merges_dicts():
    cfg1: Config = {"a": {"x": 1, "y": 2}}
    cfg2: Config = {"a": {"y": 10, "z": 3}}

    # z is a new key under a -> warn by default
    with pytest.warns(UserWarning, match=r"Adding new key"):
        out = merge(cfg1, cfg2)

    assert out == {"a": {"x": 1, "y": 10, "z": 3}}

    # Ensure inputs unchanged
    assert cfg1 == {"a": {"x": 1, "y": 2}}
    assert cfg2 == {"a": {"y": 10, "z": 3}}


def test_merge_rejects_unknown_policy():
    with pytest.raises(ValueError, match=r"Unknown `new_key_policy`"):
        merge({"a": 1}, {"a": 2}, new_key_policy="nope")


###########
# CONVERT #
###########


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),
        (" -2", -2),
        ("3.14", 3.14),
        ("-0.001", -0.001),
        ("true", True),
        ("TRUE", True),
        ("false", False),
        ("FaLsE", False),
        ("hello", "hello"),
        ("01", 1),  # int conversion
    ],
)
def test_convert_if_possible(raw, expected):
    assert convert_if_possible(raw) == expected


##########
# PARSER #
##########


def test_parser_env_var_replacement_and_type_cast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTV", "123")
    monkeypatch.setenv("FLOATV", "0.5")
    monkeypatch.setenv("BOOLV", "true")
    monkeypatch.setenv("STRV", "abc")

    cfg: Config = {
        "a": "$INTV",
        "b": "${FLOATV}",
        "c": "x_${STRV}_y",
        "d": "$BOOLV",
    }
    out = Parser(cfg).parse()
    assert out["a"] == 123  # noqa: PLR2004
    assert out["b"] == 0.5  # noqa: PLR2004
    assert out["c"] == "x_abc_y"
    assert out["d"] is True


def test_parser_warns_on_missing_env_var_and_replaces_with_empty_string():
    cfg: Config = {"a": "$MISSING_ENV"}
    with pytest.warns(UserWarning, match=r"Environment variable .* not define"):
        out = Parser(cfg).parse()
    assert out["a"] == ""


def test_parser_self_reference_full_match_preserves_type():
    cfg: Config = {
        "seed": 666,
        "training": {"seed": "{seed}"},
    }
    out: Config = Parser(cfg).parse()
    assert isinstance(out["training"], dict)
    assert out["training"]["seed"] == out["seed"] == cfg["seed"]


def test_parser_self_reference_partial_match_stringifies():
    cfg: Config = {
        "seed": 666,
        "name": "exp-{seed}",
    }
    out = Parser(cfg).parse()
    assert out["name"] == "exp-666"  # string interpolation


def test_parser_warns_on_missing_self_reference_and_replaces_with_empty_string():
    cfg: Config = {"name": "exp-{unknown.key}"}
    with pytest.warns(UserWarning, match=r"Unable to resolve reference"):
        out = Parser(cfg).parse()
    assert out["name"] == "exp-"


def test_parser_detects_cycles():
    cfg: Config = {"a": "{b}", "b": "{a}"}
    with pytest.raises(RuntimeError, match=r"Cyclic references"):
        Parser(cfg).parse()


def test_parser_no_parse_prefix_disables_parsing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("X", "123")
    cfg: Config = {"a": "!P$X", "b": "!P{a}"}
    out = Parser(cfg).parse()
    assert out["a"] == "$X"
    assert out["b"] == "{a}"


def test_parser_parses_lists_of_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V", "2")
    cfg: Config = {"vals": ["1", "$V", True, "hello", "{missing}"]}
    with pytest.warns(UserWarning, match=r"Unable to resolve reference"):
        out = Parser(cfg).parse()
    assert out["vals"] == ["1", 2, True, "hello", ""]


######
# IO #
######


def test_save_then_load_config_roundtrip(tmp_path: pathlib.Path):
    cfg: Config = {"a": 1, "b": {"c": [1, 2, 3], "d": "x"}}
    save_config(cfg, tmp_path / "cfg.yml")
    loaded = load_config(tmp_path / "cfg.yml")
    assert loaded == cfg


def test_load_config_without_default_returns_config(tmp_path: pathlib.Path):
    (tmp_path / "cfg.yml").write_text("a: 1\nb:\n  c: 2\n  d: 1.e-5")
    assert load_config(tmp_path / "cfg.yml") == {"a": 1, "b": {"c": 2, "d": 1e-5}}


def test_load_config_with_default_relative_to_current_file(tmp_path: pathlib.Path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "sub").mkdir()

    save_config({"a": 1}, tmp_path / "configs" / "base.yml")
    save_config({"b": 2.0}, tmp_path / "configs" / "sub" / "first.yml")
    save_config({"__default__": ["../base.yml", "./first.yml"]}, tmp_path / "configs" / "sub" / "second.yml")

    loaded = load_config(tmp_path / "configs" / "sub" / "second.yml")
    assert loaded == {"a": 1, "b": 2.0}


def test_load_config_with_default_absolute_path(tmp_path: pathlib.Path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "sub").mkdir()

    save_config({"a": 1}, tmp_path / "configs" / "base.yml")
    save_config({"b": 2.0}, tmp_path / "configs" / "sub" / "first.yml")
    save_config(
        {"__default__": [str(tmp_path / "configs" / "base.yml"), str(tmp_path / "configs" / "sub" / "first.yml")]},
        tmp_path / "configs" / "sub" / "second.yml",
    )

    loaded = load_config(tmp_path / "configs" / "sub" / "second.yml")
    assert loaded == {"a": 1, "b": 2.0}


def test_load_config_with_default_cwd_path(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "sub").mkdir()

    save_config({"a": 1}, tmp_path / "configs" / "base.yml")
    save_config(
        {
            "__new_key_policy__": "pass",
            "__default__": str(pathlib.Path("configs") / "base.yml"),
            "b": "2.0",
        },
        tmp_path / "configs" / "sub" / "second.yml",
    )

    loaded = load_config(tmp_path / "configs" / "sub" / "second.yml")
    assert loaded == {"a": 1, "b": "2.0"}


def test_load_config_default_order_last_wins(tmp_path: pathlib.Path):
    """Later defaults should override earlier ones."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "sub").mkdir()

    save_config({"a": 1, "z": "z"}, tmp_path / "configs" / "base.yml")
    save_config({"a": 2, "b": 2.0}, tmp_path / "configs" / "sub" / "first.yml")
    save_config({"__default__": ["../base.yml", "./first.yml"]}, tmp_path / "configs" / "sub" / "second.yml")

    loaded = load_config(tmp_path / "configs" / "sub" / "second.yml")
    assert loaded == {"a": 2, "b": 2.0, "z": "z"}
