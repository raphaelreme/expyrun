"""Handle yaml configuration files

Read a yaml file and convert it into a dict.
The format is a bit more restrictive than yaml, you cannot build list of Objects,
only list of values (int, float, bool, str). "." cannot be used inside a key name.

Also some specific keys are used by this library in the root level. See README.md about this.
"""

import copy
import os
import pathlib
import re
from typing import Set, cast, Dict, List, Union
import warnings

import yaml


Value = Union[bool, int, float, str]

Config = Dict[str, Union[Value, List[Value], "Config"]]


def load_config(config_file: Union[str, pathlib.Path]) -> Config:
    """Load a configuration from a given file

    Args:
        config_file (Union[str, Path]): The configuration file name

    Returns:
        Config: The loaded configuration. Parsing is not performed at loading time.
    """
    path = pathlib.Path(config_file)
    cfg: Config = yaml.safe_load(path.read_text(encoding="utf-8"))

    try:
        defaults = cast(Union[str, List[str]], cfg.pop("__default__"))
    except KeyError:
        return cfg

    try:
        new_key_policy = cfg.pop("__new_key_policy__")
    except KeyError:
        new_key_policy = "warn"

    if isinstance(defaults, str):
        defaults = [defaults]

    default_cfg: Config = {}
    for default_path in defaults:
        if pathlib.Path(default_path).is_absolute() or default_path[0] != ".":  # Absolute or from cwd
            default_cfg = merge(default_cfg, load_config(default_path), "pass")
        else:  # Relative to the current config
            default_cfg = merge(default_cfg, load_config(path.parent / default_path), "pass")

    cfg = merge(default_cfg, cfg, new_key_policy)

    return cfg


def save_config(cfg: Config, config_file: Union[str, pathlib.Path]) -> None:
    """Save the configuration

    Args:
        cfg (Config): Configuration to save
        config_file (Union[str, Path]): Save to this destination
    """
    path = pathlib.Path(config_file)
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


def config_flatten(cfg: Config) -> Dict[str, Union[Value, List[Value]]]:
    """Flatten a config

    {
        "hello": {
            "world": True,
            "values": {
                "train": [1, 2, 3],
                "test": 3.5,
            }
        }
    }

    =>

    {
        "hello.world": True,
        "hello.values.train": [1, 2, 3],
        "hello.values.test": 3.5,
    }

    Args:
        cfg (Config): A config to flatten

    Returns:
        Config: The flattened config
    """
    flattened: Dict[str, Union[Value, List[Value]]] = {}
    _flatten(cfg, flattened)

    return flattened


def _flatten(cfg: Config, flattened: Dict[str, Union[Value, List[Value]]], prefix: str = "") -> None:
    for key, value in cfg.items():
        true_key = f"{prefix}.{key}"
        if not prefix:
            true_key = key

        # If dict: continue with the new prefix
        if isinstance(value, dict):
            _flatten(value, flattened, true_key)
            continue

        # Else: Let's register the value
        if true_key in flattened:
            raise ValueError(f"{true_key} is already set. Should not override it")
        flattened[true_key] = value


def config_unflatten(cfg: Dict[str, Union[Value, List[Value]]]) -> Config:
    """Unflatten a config (Reverse flatten)

    Key containing "." are split. And sub dictionnaries are created.

    Args:
        cfg (Dict[str, Union[Value, List[Value]]]): The config to unflatten.

    Returns:
        Config: The unflattened config
    """
    unflattened_cfg: Config = {}
    for key, value in cfg.items():
        current_cfg = unflattened_cfg

        keys = key.split(".")

        for k in keys[:-1]:
            if k not in current_cfg:
                current_cfg[k] = {}

            next_cfg = current_cfg[k]
            if isinstance(next_cfg, dict):
                current_cfg = next_cfg
            else:
                raise ValueError(f"Key {key} is already set. Can't override it (Found a value for {k})")

        k = keys[-1]
        if k in current_cfg:
            raise ValueError(f"Key {key} is already set. Can't override it")
        current_cfg[k] = value

    return unflattened_cfg


def merge(cfg_1: Config, cfg_2: Config, new_key_policy="warn") -> Config:
    """Merge cfg_2 into cfg_1.

    cfg_1 is not modified. (Nor cfg_2)

    Args:
        cfg_1 (Config): First configuration
        cfg_2 (Config): Second configuration
        new_key_policy (str): Policy when adding new keys
            "raise": Raise KeyError when a key in cfg_2 is not in cfg_1
            "warn": Add the new key but raise a warning
            "pass": Add the new key

    Returns:
        Config: The merged configuration
    """
    assert new_key_policy in ["raise", "warn", "pass"]

    cfg = copy.deepcopy(cfg_1)

    for key, value in cfg_2.items():
        value = copy.deepcopy(value)

        if key not in cfg:
            if "__" == key[:2]:  # Allow specific keys to be new
                cfg[key] = value
                continue
            if new_key_policy == "raise":
                raise KeyError(f"Unexpected key when merging configs: {key}")
            if new_key_policy == "warn":
                warnings.warn(f"Adding new key to configuration: {key}")
            cfg[key] = value
            continue

        previous_value = cfg[key]

        if not isinstance(value, type(previous_value)):
            warnings.warn(
                f"Key `{key}` has been overloaded with a different type: {type(previous_value)} -> {type(value)}"
            )
            cfg[key] = value
            continue

        # Same type. If dict, let's merge, if not just replace
        if isinstance(previous_value, dict):
            cfg[key] = merge(previous_value, cast(dict, value), new_key_policy)
        else:
            cfg[key] = value

    return cfg


def convert_if_possible(value: str) -> Value:
    """Try to convert the string to another type if possible

    Try to convert as much a possible without losing information.
    You should probably use dataclass with dacite to ensure that eveything is well typed

    Args:
        value (str): Value to be converted

    Returns:
        Value: Converted value
    """
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            if value.lower() == "false":
                return False
            if value.lower() == "true":
                return True
            return value


class Parser:
    """Parse a configuration and handles environement variables and self references

    Attrs:
        NO_PARSE_STRING (str): Add this string to the begining of the value to prevent parsing
        ENV_VAR_REGEXP, ENV_VAR_REGEXP_BRACKET (str): Regexp for environement variables matching
            A bit too simple, but will do the job
        SELF_REF_REGEXP (str): Regexp for self references. A bit permissive, but fine.
    """

    NO_PARSE_STRING = "!P"
    ENV_VAR_REGEXP = "\\$([a-zA-Z][a-zA-Z1-9_]*)"
    ENV_VAR_REGEXP_BRACKET = "\\$\\{([a-zA-Z][a-zA-Z1-9_]*)\\}"
    SELF_REF_REGEXP = "\\{([a-zA-Z1-9_.]+)\\}"

    def __init__(self, config: Config) -> None:
        self.config = config_flatten(config)
        self.parsing: Set[str] = set()
        self.parsed: Set[str] = set()

    def parse(self) -> Config:
        """Parse each key/value of the configuration"""
        for key in self.config:  # Flatten, there is only one level
            self.parse_key(key)

        return config_unflatten(self.config)

    def parse_key(self, key: str):
        """Parse a single key/value of the configuration

        (can lead to other keys being parsed if the value depends on them)

        Args:
            key (str): Key of the value to parse
        """
        if key in self.parsed:
            return

        if key in self.parsing:
            raise RuntimeError(f"Cyclic references in configuration: Unable to resolve {key}")

        self.parsing.add(key)
        self.config[key] = self.format(self.config[key])

        self.parsing.remove(key)
        self.parsed.add(key)

    def format(self, value: Union[Value, List[Value]]) -> Union[Value, List[Value]]:
        """Parse and format a value

        Args:
            value (Union[Value, List[Value]]): A value to parse

        Returns:
            Union[Value, List[Value]]: Parsed value
        """
        if isinstance(value, list):
            return list(map(self.format, value))  # type: ignore

        if not isinstance(value, str):  # Only strings can be parsed
            return value

        # Allow a simple directive to prevent parsing
        if self.NO_PARSE_STRING == value[: len(self.NO_PARSE_STRING)]:
            return value[len(self.NO_PARSE_STRING) :]

        # SKip as much as possible parsing as I coded it badly
        if "$" in value:
            value = self.replace_env_reference(value)
            if not isinstance(value, str):
                return value

        if "{" in value:
            value = self.replace_self_reference(value)

        return value

    def replace_env_reference(self, value: str) -> Union[Value, List[Value]]:
        """Solve environment variables references for the given value

        Args:
            value (str): String to parse

        Returns
            Union[Value, List[Value]]: Parsed value (converted if possible)
        """

        def env_replace(match):
            env_key = match.group(1)
            if env_key in os.environ:
                return os.environ[env_key]
            warnings.warn(f"Environment variable {env_key} not define")
            return ""

        value = re.sub(self.ENV_VAR_REGEXP, env_replace, value)
        value = re.sub(self.ENV_VAR_REGEXP_BRACKET, env_replace, value)
        return convert_if_possible(value)

    def replace_self_reference(self, value: str) -> Union[Value, List[Value]]:
        """Solve configuration references for the given value

        Args:
            value (str): String to parse

        Returns
            Union[Value, List[Value]]: Parsed value (converted if total match)
        """

        def self_replace(match):
            key = match.group(1)
            if key in self.config:
                self.parse_key(key)
                return str(self.config[key])
            warnings.warn(f"Unable to resolve reference {key}.")
            return ""

        # Handle full match differently to cast to the right value
        match = re.fullmatch(self.SELF_REF_REGEXP, value)
        if match:
            key = match.group(1)
            if key in self.config:
                self.parse_key(key)
                return copy.deepcopy(self.config[key])  # Keep type if full match

        value = re.sub(self.SELF_REF_REGEXP, self_replace, value)
        return value
