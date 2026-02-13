from __future__ import annotations

import atexit
import io
import os
import pathlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

from expyrun import main

if TYPE_CHECKING:
    from expyrun import config


def make_package(root: pathlib.Path, pkg: str = "src", module: str = "runner") -> str:
    """Create a minimal importable package.

    Structure:
      root/
        src/
          __init__.py
          runner.py  (contains function run(name, cfg))

    Returns:
      str: module_name (i.e. pkg.module)

    """
    pkg_dir = root / pkg
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / f"{module}.py").write_text(
        """
from __future__ import annotations
import pathlib

def run(name: str, cfg: dict) -> None:
    # mark that the function was executed and record inputs
    pathlib.Path("ran.txt").write_text(f"{name}\\n{cfg.get('x', '')}\\n", encoding="utf-8")
    print("hello from run")
""".lstrip(),
        encoding="utf-8",
    )

    return f"{pkg}.{module}"


def minimal_cfg(module_name: str, output_dir: pathlib.Path, code_dir: pathlib.Path | None = None) -> config.Config:
    run_section: config.Config = {
        "__main__": f"{module_name}:run",
        "__name__": "exp_name",
        "__output_dir__": str(output_dir),
    }
    if code_dir is not None:
        run_section["__code__"] = str(code_dir)
    return {"__run__": run_section, "x": 42}


class NoStdRedirect:
    """No-op replacement for StdFileRedirection to avoid touching sys.stdout/stderr in tests."""

    def __init__(self, _path: str | os.PathLike) -> None:
        pass


@pytest.fixture
def keep_sys_path():
    before = list(sys.path)
    yield
    sys.path[:] = before


##################
# StdMultiplexer #
##################


def test_std_multiplexer_write_and_flush_forwarded():
    base = io.StringIO()
    side1 = io.StringIO()
    side2 = io.StringIO()

    mux = main.StdMultiplexer(base, [side1, side2])

    # write returns what main_stream.write returns (number of chars)
    n = mux.write("hello")
    assert n == 5  # noqa: PLR2004

    mux.write("\nworld")
    mux.flush()

    expected = "hello\nworld"
    assert base.getvalue() == expected
    assert side1.getvalue() == expected
    assert side2.getvalue() == expected


def test_std_multiplexer_getattr_delegates_to_main_stream():
    base = io.StringIO()
    side = io.StringIO()
    mux = main.StdMultiplexer(base, [side])

    # StringIO has getvalue(); StdMultiplexer should delegate unknown attrs
    mux.write("x")
    assert mux.getvalue() == "x"
    assert side.getvalue() == "x"


####################
# FILE_REDIRECTION #
####################


def test_std_file_redirection_writes_to_file_and_restores_streams(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # Avoid registering global atexit handlers during the test.
    monkeypatch.setattr(atexit, "register", lambda *_args, **_kwargs: None)

    log_path = tmp_path / "outputs.log"

    # Keep references to the original streams so we can assert restoration.
    orig_out = sys.stdout
    orig_err = sys.stderr

    redir = main.StdFileRedirection(log_path)

    # Write to stdout/stderr while redirected
    print("hello stdout")
    sys.stderr.write("hello stderr\n")
    sys.stdout.flush()
    sys.stderr.flush()

    # Close should restore sys.stdout/sys.stderr and close file
    redir.close()

    assert sys.stdout is orig_out
    assert sys.stderr is orig_err

    content = log_path.read_text(encoding="utf-8")
    assert "hello stdout\n" in content
    assert "hello stderr\n" in content

    captured = capsys.readouterr()

    assert captured.out == "hello stdout\n"
    assert captured.err == "hello stderr\n"


##############
# CONVERT_AS #
##############


@pytest.mark.parametrize(
    ("default", "arg", "expected"),
    [
        (1, "2", 2),
        (1.0, "2.0", 2.0),
        (1.0, "2.5", 2.5),
        (True, "false", False),
        (True, "0", False),
        (False, "true", True),
        (False, "1", True),
        (["1", "2"], "3,4", ["3", "4"]),  # default list of str -> list of str
        ([1, "2"], "3,4", [3, "4"]),  # Same length -> Type is match by element
        ([1, 2], "3,4,5", [3, 4, 5]),  # len differs -> use first element type
        ([], "1,2,3", [1, 2, 3]),  # empty list -> convert_if_possible
        (None, "5", 5),  # None -> convert_if_possible
    ],
)
def test_convert_as(default, arg, expected):
    assert main.convert_as(default, arg) == expected


def test_convert_as_bool_invalid():
    with pytest.raises(ValueError, match="Unable to convert to boolean"):
        main.convert_as(True, "maybe")


################
# BUILD_CONFIG #
################


def test_build_config_overrides_values(tmp_path: pathlib.Path):
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(
        """
__run__:
  __main__: my_code.runner:run
  __name__: test
  __output_dir__: /tmp/out

a: 1
b:
  c: 2
lst: [1, 2]
d: 5.0
""".lstrip(),
        encoding="utf-8",
    )

    # Override existing keys only
    out = main.build_config(
        str(cfg_file),
        ["--a", "10", "--b.c", "20", "--lst", "3,4"],
    )
    assert out["a"] == 10  # noqa: PLR2004
    assert isinstance(out["b"], dict)
    assert out["b"]["c"] == 20  # noqa: PLR2004
    assert out["lst"] == [3, 4]
    assert out["d"] == 5.0  # noqa: PLR2004


def test_build_config_rejects_odd_number_of_args(tmp_path: pathlib.Path):
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(
        """
__run__:
  __main__: my_code.runner:run
  __name__: test
  __output_dir__: /tmp/out

a: 1
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Args should be even"):
        main.build_config(str(cfg_file), ["--a"])


def test_build_config_rejects_bad_key_format(tmp_path: pathlib.Path):
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(
        """
__run__:
  __main__: my_code.runner:run
  __name__: test
  __output_dir__: /tmp/out
a: 1
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Expected key format"):
        main.build_config(str(cfg_file), ["a", "2"])


def test_build_config_rejects_unknown_key(tmp_path: pathlib.Path):
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(
        """
__run__:
  __main__: my_code.runner:run
  __name__: test
  __output_dir__: /tmp/out
a: 1
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(KeyError, match="Unexpected key when merging args"):
        main.build_config(str(cfg_file), ["--nope", "2"])


##################
# DUPLICATE_CODE #
##################


def test_duplicate_code_copies_only_py_files(tmp_path: pathlib.Path):
    # Minimal pkg + additional files for a complete test
    pkg = make_package(tmp_path / "project")
    pkg_path = tmp_path / "project" / "src"

    (pkg_path / "a.py").write_text("x=1\n", encoding="utf-8")
    (pkg_path / "data.bin").write_bytes(b"\x00\x01")
    (pkg_path / "nested").mkdir()
    (pkg_path / "nested" / "__init__.py").write_text("", encoding="utf-8")
    (pkg_path / "nested" / "b.py").write_text("y=2\n", encoding="utf-8")
    (pkg_path / "nested" / "notes.txt").write_text("no\n", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    main.duplicate_code(tmp_path / "project", out_dir, pkg)

    copied_pkg = out_dir / "src"
    assert (copied_pkg / "__init__.py").exists()
    assert (copied_pkg / "runner.py").exists()
    assert (copied_pkg / "a.py").read_text().strip() == "x=1"
    assert (copied_pkg / "nested" / "b.py").read_text().strip() == "y=2"

    # non .py files should not be copied
    assert not (copied_pkg / "data.bin").exists()
    assert not (copied_pkg / "nested" / "notes.txt").exists()


def test_code_copy_refuses_existing_destination(tmp_path: pathlib.Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "my_code").mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    # Pre-create destination package name to trigger the guard
    (dest / "my_code").mkdir()

    with pytest.raises(RuntimeError, match="existing location"):
        main.duplicate_code(src, dest, "my_code.runner")


def test_duplicate_code_warns_on_unhandled_path(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    pkg = make_package(tmp_path / "project")
    pkg_path = tmp_path / "project" / "src"
    (pkg_path / "tmp").touch()

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Patch is_file and is_dir to trigger the warning for a specific file
    orig_is_file = pathlib.Path.is_file
    orig_is_dir = pathlib.Path.is_dir

    def patched_is_file(self: pathlib.Path) -> bool:
        if self == pkg_path / "tmp":
            return False
        return orig_is_file(self)

    def patched_is_dir(self: pathlib.Path) -> bool:
        if self == pkg_path / "tmp":
            return False
        return orig_is_dir(self)

    monkeypatch.setattr(pathlib.Path, "is_file", patched_is_file)
    monkeypatch.setattr(pathlib.Path, "is_dir", patched_is_dir)

    with pytest.warns(UserWarning, match=r"Unhandled path in code duplication"):
        main.duplicate_code(tmp_path / "project", out_dir, pkg)

    assert (out_dir / "src").exists()
    assert (out_dir / "src" / "runner.py").exists()
    assert not (out_dir / "src" / "tmp").exists()


########
# MAIN #
########


def test_main_debug_mode_runs_without_copying(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, keep_sys_path):
    pkg = make_package(tmp_path / "project")
    output_dir = tmp_path / "outputs"
    cfg = minimal_cfg(pkg, output_dir=output_dir, code_dir=tmp_path / "project")

    # Avoid std redirection side-effects
    monkeypatch.setattr(main, "StdFileRedirection", NoStdRedirect)

    # Ensure we don't copy / freeze in debug
    called: dict[str, int] = {"save_requirements": 0, "duplicate_code": 0}

    def _save(_out: pathlib.Path) -> None:
        called["save_requirements"] += 1

    def _dup(_code: pathlib.Path, _out: pathlib.Path, _mod: str) -> None:
        called["duplicate_code"] += 1

    monkeypatch.setattr(main, "save_requirements", _save)
    monkeypatch.setattr(main, "duplicate_code", _dup)

    old_cwd = pathlib.Path.cwd()
    try:
        main.main(cfg, debug=True)
    finally:
        os.chdir(old_cwd)

    assert called["save_requirements"] == 0
    assert called["duplicate_code"] == 0

    exp_dir = output_dir.absolute() / "DEBUG" / "exp_name" / "exp.0"
    assert exp_dir.exists()
    assert (exp_dir / "config.yml").exists()
    assert (exp_dir / "raw_config.yml").exists()

    # main function wrote ran.txt in the experiment directory
    assert (exp_dir / "ran.txt").read_text(encoding="utf-8") == f"exp_name\n{cfg['x']}\n"


def test_main_non_debug_copies_and_writes_requirements(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, keep_sys_path
):
    pkg = make_package(tmp_path / "project")
    output_dir = tmp_path / "outputs"
    cfg = minimal_cfg(pkg, output_dir=output_dir, code_dir=tmp_path / "project")

    monkeypatch.setattr(main, "StdFileRedirection", NoStdRedirect)

    called: dict[str, int] = {"save_requirements": 0, "duplicate_code": 0}

    def _save(out: pathlib.Path) -> None:
        called["save_requirements"] += 1
        # create a marker file as if pip freeze ran
        (out / "requirements.txt").write_text("expyrun\n", encoding="utf-8")

    _duplicate = main.duplicate_code

    def _dup(code: pathlib.Path, out: pathlib.Path, mod: str) -> None:
        called["duplicate_code"] += 1
        _duplicate(code, out, mod)

    monkeypatch.setattr(main, "save_requirements", _save)
    monkeypatch.setattr(main, "duplicate_code", _dup)

    old_cwd = pathlib.Path.cwd()
    try:
        main.main(cfg, debug=False)
    finally:
        os.chdir(old_cwd)

    assert called["save_requirements"] == 1
    assert called["duplicate_code"] == 1

    exp_dir = output_dir.absolute() / "exp_name" / "exp.0"
    assert exp_dir.exists()
    assert (exp_dir / "requirements.txt").exists()

    # Code should have been copied
    assert (exp_dir / "src" / "__init__.py").exists()
    assert (exp_dir / "src" / "runner.py").exists()

    # main function wrote ran.txt in the experiment directory
    assert (exp_dir / "ran.txt").read_text(encoding="utf-8") == f"exp_name\n{cfg['x']}\n"


def test_main_increments_exp_index_if_exp0_exists(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, keep_sys_path
):
    pkg = make_package(tmp_path / "project")
    output_dir = tmp_path / "outputs"
    cfg = minimal_cfg(pkg, output_dir=output_dir, code_dir=tmp_path / "project")

    monkeypatch.setattr(main, "StdFileRedirection", NoStdRedirect)

    # Create exp.0 ahead of time so main should create exp.1
    pre = output_dir.absolute() / "exp_name" / "exp.0"
    pre.mkdir(parents=True)

    old_cwd = pathlib.Path.cwd()
    try:
        main.main(cfg, debug=False)
    finally:
        os.chdir(old_cwd)

    assert (output_dir.absolute() / "exp_name" / "exp.1").exists()

    # Exists but is empty as with our uv install, pip is not available
    assert (output_dir.absolute() / "exp_name" / "exp.1" / "requirements.txt").exists()


def test_main_sets_expyrun_cwd_env_var(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, keep_sys_path):
    pkg = make_package(tmp_path / "project")
    output_dir = tmp_path / "outputs"
    cfg = minimal_cfg(pkg, output_dir=output_dir, code_dir=tmp_path / "project")

    monkeypatch.setattr(main, "StdFileRedirection", NoStdRedirect)

    old_cwd = pathlib.Path.cwd()
    try:
        main.main(cfg, debug=True)
    finally:
        os.chdir(old_cwd)

    assert os.environ.get("EXPYRUN_CWD") == str(old_cwd)


# # ---------------------------
# # entry_point() CLI parsing
# # ---------------------------


def test_entry_point_debug_hack_moves_debug_from_remainder(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(
        """
__run__:
  __main__: my_code.runner:run
  __name__: test
  __output_dir__: /tmp/out
a: 1
""".lstrip(),
        encoding="utf-8",
    )

    captured: dict[str, Any] = {}

    def fake_build_config(config_path: str, args: list[str]) -> config.Config:
        captured["config_path"] = config_path
        captured["args"] = list(args)
        return {"__run__": {"__main__": "x:y", "__name__": "n", "__output_dir__": "tmp"}}

    def fake_main(cfg, debug: bool) -> None:
        captured["debug"] = debug
        captured["cfg"] = cfg

    monkeypatch.setattr(main, "build_config", fake_build_config)
    monkeypatch.setattr(main, "main", fake_main)

    # Simulate: expyrun cfg.yml --a 2 --debug
    # (where argparse would place --debug into remainder if it comes after config)
    monkeypatch.setattr(sys, "argv", ["expyrun", str(cfg_file), "--a", "2", "--debug"])

    main.entry_point()

    assert captured["config_path"] == str(cfg_file)
    assert captured["debug"] is True
    # --debug should have been removed from remainder
    assert captured["args"] == ["--a", "2"]

    captured = {}
    monkeypatch.setattr(sys, "argv", ["expyrun", str(cfg_file), "--a", "2"])

    main.entry_point()

    assert captured["config_path"] == str(cfg_file)
    assert captured["debug"] is False
    # --debug should have been removed from remainder
    assert captured["args"] == ["--a", "2"]
