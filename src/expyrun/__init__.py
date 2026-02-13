"""Run reproducible experiments from a yaml configuration file.

Expyrun.
=======

Expyrun is a lightweight experiment runner designed to make research workflows
reproducible and structured.

It allows you to:
- Define experiments in YAML configuration files
- Inherit and compose configurations
- Override parameters from the command line
- Resolve environment variables and self-references
- Automatically create structured output directories
- Snapshot the configuration, dependencies, and source code
- Reproduce experiments exactly

Typical workflow
----------------
1. Write a YAML config file containing a special ``__run__`` section.
2. Implement an entry function with signature:

       def main(name: str, config: dict) -> None:

3. Launch your experiment:

       expyrun path/to/config.yml [--debug] [--my.key value]

Expyrun will:
- Build the configuration (including CLI overrides)
- Create a unique experiment directory
- Save the parsed and raw configurations
- Freeze requirements
- Copy the relevant source code (except in debug mode)
- Redirect stdout/stderr to ``outputs.log``
- Execute your entry function inside the experiment directory

This project was originally developed to fit the author's research needs.
It is currently in beta. Contributions and feedback are very welcome.

See the README for full documentation and examples.
"""

import importlib.metadata

__version__ = importlib.metadata.version("expyrun")
