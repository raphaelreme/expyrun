"""Run experiment given a configuration file

The config is expected to have a special `__run__` section.

Command lines arguments are used to overwrite the given configuration.

When an experiment is launched:
1- First the config is built from the config file and args
2- Then the output directory is created.
3- It's then filled with
    a- The built configuration file (with resolved dependencies): config.yml
    b- The built configuration file but unparsed: raw_config.yml
    c- Frozen requirements: frozen_requirements.txt
    d- Copy of all the code in the package of the main function
4- The output directory is registered as the current directory and is set in sys.path.
   You can therefore write directly in the current directory in the main function.
5- Finally the main function is loaded and run.

In DEBUG mode, the code is not copied in the output dir, the code is directly run from the current
directory
"""

import argparse
import atexit
import importlib
import os
import pathlib
import subprocess
import sys
from typing import Dict, cast, List, TextIO, Union
import warnings

from . import config


CODE_FILES_EXTENSIONS = [".py"]


class StdMultiplexer:
    """Patch a writable text stream and multiplexes the outputs to several others

    Only write and flush are redirected. Other actions are done only on the main stream.
    It will therefore have the same properties as the main stream.
    """

    def __init__(self, main_stream: TextIO, ios: List[TextIO]):
        self.main_stream = main_stream
        self.ios = ios

    def write(self, string: str) -> int:
        """Write to all the streams"""
        ret = self.main_stream.write(string)

        for io_ in self.ios:
            io_.write(string)

        return ret

    def flush(self) -> None:
        """Flush all the streams"""
        self.main_stream.flush()

        for io_ in self.ios:
            io_.flush()

    def __getattr__(self, attr: str):
        return getattr(self.main_stream, attr)


class StdFileRedirection:
    """Multiplexes stdout and stderr to a file

    The code could potentially break other libraries trying to redirects sys.stdout and sys.stderr.
    It has been made compatible with Neptune. Any improvements are welcome.
    """

    def __init__(self, path: Union[pathlib.Path, str]) -> None:
        self.file = open(path, "w", encoding="utf-8")  # pylint: disable=consider-using-with
        self.stdout = StdMultiplexer(sys.stdout, [self.file])
        self.stderr = StdMultiplexer(sys.stderr, [self.file])
        sys.stdout = self.stdout  # type: ignore
        sys.stderr = self.stderr  # type: ignore
        atexit.register(self.close)

    def close(self):
        """Close the std file redirection (Reset sys.stdout/sys.stderr)"""
        sys.stdout = self.stdout.main_stream
        sys.stderr = self.stderr.main_stream
        self.file.close()


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
    flatten = config.config_flatten(cfg)

    # Parse args to build a cfg
    assert len(args) % 2 == 0, "Args should be even, missing a value or a key"

    key = ""
    for i, arg in enumerate(args):
        if i % 2 == 0:
            assert arg[:2] == "--", "Expected key format: --my.entire.key"
            key = arg[2:]
            continue

        if key not in flatten:
            raise KeyError(f"Unexpected key when merging args: {key}")

        flatten[key] = convert_as(flatten[key], arg)

    return config.config_unflatten(flatten)


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


def save_requirements(output_dir: pathlib.Path) -> None:
    """Save the requirements using pip freeze into a requirements.txt"""
    subprocess.run("pip freeze > requirements.txt", check=False, cwd=output_dir, shell=True)
    # OLD: Importing pip blocks setuptools (cf : https://github.com/pypa/setuptools/issues/3044)
    # from pip._internal.operations import freeze
    # (output_dir / "requirements.txt").write_text("\n".join(freeze.freeze()), encoding="utf-8")


def main(cfg: config.Config, debug: bool):
    """Prepare and launch the experiment

    Args:
        cfg (dict): Configuration
        debug (bool): Use DEBUG mode
    """
    # Save the current cwd in case it is really needed (Will be changed in a few lines)
    os.environ["EXPYRUN_CWD"] = os.getcwd()

    raw_cfg = cfg
    cfg = config.Parser(cfg).parse()  # Resolve self and env references

    # Load the run data
    module_name, func_name = cast(Dict[str, str], cfg["__run__"])["__main__"].split(":")
    experiment_name = cast(Dict[str, str], cfg["__run__"])["__name__"]
    output_dir = pathlib.Path(cast(Dict[str, str], cfg["__run__"])["__output_dir__"])
    code_dir = pathlib.Path(cast(Dict[str, str], cfg["__run__"]).get("__code__", os.getcwd()))

    # Set output_dir as an absolute path
    output_dir = output_dir.absolute()
    cast(Dict[str, str], raw_cfg["__run__"])["__output_dir__"] = str(output_dir)
    cast(Dict[str, str], cfg["__run__"])["__output_dir__"] = str(output_dir)

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

    if debug:  # In debug mode, do not copy the code nor the requirements
        sys.path.insert(0, str(code_dir))
    else:
        save_requirements(output_dir)
        duplicate_code(code_dir, output_dir, module_name)
        cast(Dict[str, str], raw_cfg["__run__"])["__code__"] = str(output_dir)
        cast(Dict[str, str], cfg["__run__"])["__code__"] = str(output_dir)
        sys.path.insert(0, str(output_dir))

    config.save_config(cfg, output_dir / "config.yml")
    config.save_config(raw_cfg, output_dir / "raw_config.yml")

    # Execute inside output_dir
    os.chdir(output_dir)

    # Redirects logs
    StdFileRedirection("outputs.log")

    # Find the main function. Should take the name and the configuration as input
    module = importlib.import_module(module_name)
    _main = getattr(module, func_name)

    # Launch the experiment
    cfg.pop("__run__")
    _main(experiment_name, cfg)


def entry_point() -> None:
    """expyrun entry point"""
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
