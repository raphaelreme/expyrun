"""Run experiment given a configuration file

The config is expected to have a special `__run__` section.

Command lines arguments are used to overwrite the given configuration.

When an experiment is launched:
1- First the config is built from the config file and args
2- Then the output directory is created.
3- It's then filled with
    a- The built configuration file (with resolved dependencies): config.yml
    b- Frozen requirements: frozen_requirements.txt
    c- Copy of all the code in the package of the main function
4- The output directory is registered as the current directory and is set in sys.path.
   You can therefore write directly in the current directory in the main function.
5- Finally the main function is loaded and run.

WARNING:
    In the current version, a wrapper around stdout and stderr redirects logs into a file.
    It's ugly and can probably broke some codes


In DEBUG mode, the code is not copied in the output dir, the code is directly run from the current
directory
"""


import argparse
import importlib
import os
import pathlib
import sys
from typing import cast, List, TextIO, Union
import warnings

from pip._internal.operations import freeze

from . import config


CODE_FILES_EXTENSIONS = [".py"]


class MultiIO(TextIO):  # pylint: disable=abstract-method
    """Small hacky multi IO writer"""

    def __init__(self, ios: List[TextIO]):
        self.ios = ios

    def write(self, s: str) -> int:
        ret = 0
        for io_ in self.ios:
            ret = io_.write(s)
        return ret

    def flush(self) -> None:
        for io_ in self.ios:
            io_.flush()

    def close(self) -> None:
        for io_ in self.ios:
            io_.close()


def convert_as(default: Union[config.Value, List[config.Value]], arg: str) -> Union[config.Value, List[config.Value]]:
    """Convert the argument to the same type found in the config

    Args:
        original (Union[Value, List[Value]]): Default value in the config file
        arg (str): Argument value

    Returns:
        Union[Value, List[Value]]: The converted value
    """
    if isinstance(default, list):
        values = arg.split(",")
        if len(values) != len(default):
            if len(default) > 0:
                return [cast(config.Value, convert_as(default[0], value)) for value in values]
            return [config.convert_if_possible(value) for value in values]
        return [cast(config.Value, convert_as(default[j], value)) for j, value in enumerate(values)]

    if isinstance(default, bool):
        if arg.lower() in {"false", "0"}:
            return False
        if arg.lower() in {"true", "1"}:
            return True
        raise ValueError(f"Unable to convert to boolean: {arg}")

    converted: config.Value = arg
    if isinstance(default, int):
        converted = int(arg)
    elif isinstance(default, float):
        converted = float(arg)
    elif default is None:
        converted = config.convert_if_possible(arg)

    return converted


def build_config(config_file: str, args: List[str]) -> config.Config:
    """Build the configuration given a config file and extra args

    Args:
        config_file (str): path to configuration file
        args (List[str]): List of additional args
            Expected format: [--my.entire.key, value, --my.other.key, other_value, ...]
            This feature support only simple types (converted with `convert_as`)

    Returns:
        Config: The config for this run
    """
    cfg = config.load_config(config_file)
    cfg = config.config_flatten(cfg)

    # Parse args to build a cfg
    assert len(args) % 2 == 0, "Args should be even, missing a value or a key"

    key = ""
    for i, arg in enumerate(args):
        if i % 2 == 0:
            assert arg[:2] == "--", "Expected key format: --my.entire.key"
            key = arg[2:]
            continue

        if key not in cfg:
            raise KeyError(f"Unexpected key when merging args: {key}")

        cfg[key] = convert_as(cfg[key], arg)

    return config.Parser(cfg).parse()


def _code_copy(src_path: pathlib.Path, dest_path: pathlib.Path) -> None:
    """Probably inefficient folder search but do the job"""
    dest_path = dest_path / src_path.name
    if dest_path.exists():
        raise RuntimeError("Copying files into an existing location...")

    if src_path.is_file():
        if src_path.suffix in CODE_FILES_EXTENSIONS:
            dest_path.write_bytes(src_path.read_bytes())
        return

    if not src_path.is_dir():
        warnings.warn(f"Unhandled path in code duplication: {src_path}")

    dest_path.mkdir()  # Can create empty dir, but fine
    for child_path in src_path.iterdir():
        _code_copy(child_path, dest_path)


def duplicate_code(code_dir: pathlib.Path, output_dir: pathlib.Path, module_name: str) -> None:
    """Duplicate the package containing the running code.

    Args:
        code_dir (Path): Path to the code
        output_dir (Path): Path to where copy the code
        module_name (str): Name of the main module to run
    """
    package_path = code_dir / module_name.split(".", maxsplit=1)[0]
    _code_copy(package_path, output_dir)


def main(cfg: dict, debug: bool):
    """Prepare and launch the experiment

    Args:
        cfg (dict): Configuration
        debug (bool): Use DEBUG mode
    """
    # Load the run data
    module_name, func_name = str(cfg["__run__"]["__main__"]).split(":")
    experiment_name = str(cfg["__run__"]["__name__"])
    output_dir = pathlib.Path(cfg["__run__"]["__output_dir__"])
    code_dir = pathlib.Path(cfg["__run__"].get("__code__", os.getcwd()))

    # Compute true output dir
    if debug:
        output_dir = output_dir / "DEBUG" / experiment_name / "exp.0"
    else:
        output_dir = output_dir / experiment_name / "exp.0"

    i = 0
    while output_dir.exists():
        i += 1
        output_dir = output_dir.with_suffix(f".{i}")

    # Create the true output dir and fill it
    os.makedirs(output_dir, exist_ok=False)

    if debug:  # In debug mode, do not copy the code
        sys.path.insert(0, str(code_dir))
    else:
        duplicate_code(code_dir, output_dir, module_name)
        cfg["__run__"]["__code__"] = str(output_dir)
        sys.path.insert(0, str(output_dir))

    config.save_config(cfg, output_dir / "config.yml")
    (output_dir / "frozen_requirements.txt").write_text("\n".join(freeze.freeze()))

    os.chdir(output_dir)

    cfg.pop("__run__")

    # Find the main function. Should take the name and the configuration as input
    module = importlib.import_module(module_name)
    _main = getattr(module, func_name)

    # FIXME: Hacky output redirection. (Not reliable. Should find a better way)
    with open(output_dir / "outputs.log", "w") as log_file:
        sys.stdout = MultiIO([sys.stdout, log_file])  # type: ignore
        sys.stderr = MultiIO([sys.stderr, log_file])  # type: ignore

        # Launch the experiment
        _main(experiment_name, cfg)

        sys.stdout = sys.stdout.ios[0]
        sys.stderr = sys.stderr.ios[0]


def entry_point() -> None:
    parser = argparse.ArgumentParser(description="Launch an experiment from a yaml configuration file")
    parser.add_argument(
        "config", help="Configuration file that defines the experiment. It should contain a __run__ section."
    )
    parser.add_argument("--debug", help="Switch to DEBUG mode. The code is not copied.", action="store_true")
    parser.add_argument(
        "args",
        help="Additional arguments that overrides the configuration file\n"
        "Expected format [--my.entire.key value] ...\n"
        "If the expected value is an iterable, use --my.entire.key value1,value2,value3\n"
        "Types are inferred from the configuration file. New keys are not allowed",
        nargs=argparse.REMAINDER,
    )

    args = parser.parse_args()
    # Hacky counter to the behavior of argparse. Just don't use debug as a config key
    # if --debug is specified after the config file, it will end up with additionnal args...
    if not args.debug and "--debug" in args.args:
        args.args.remove("--debug")
        args.debug = True

    main(build_config(args.config, args.args), args.debug)
