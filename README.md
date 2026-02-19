# Expyrun

[![License](https://img.shields.io/github/license/raphaelreme/expyrun)](https://github.com/raphaelreme/expyrun/raw/main/LICENSE)
[![PyPi](https://img.shields.io/pypi/v/expyrun)](https://pypi.org/project/expyrun)
[![Python](https://img.shields.io/pypi/pyversions/expyrun)](https://pypi.org/project/expyrun)
[![Downloads](https://img.shields.io/pypi/dm/expyrun)](https://pypi.org/project/expyrun)
[![Codecov](https://codecov.io/github/raphaelreme/expyrun/graph/badge.svg)](https://codecov.io/github/raphaelreme/expyrun)
[![Lint and Test](https://github.com/raphaelreme/expyrun/actions/workflows/tests.yml/badge.svg)](https://github.com/raphaelreme/expyrun/actions/workflows/tests.yml)

**Run fully reproducible experiments from YAML configuration
files.**

Expyrun is a command-line tool that launches your code from a YAML
configuration file and automatically stores everything required to
reproduce the run in a dedicated output directory.

It helps you:
- Centralize experiment configuration
- Track code and dependency versions
- Reproduce experiments exactly
- Organize outputs cleanly

------------------------------------------------------------------------

## ⚠️ Project Status

This library was originally developed to fit my own needs as a
researcher.\
Its design and implementation are therefore somewhat opinionated and
tailored toward research workflows.

Expyrun is currently **in beta**.

Contributions are very welcome!\
Do not hesitate to open an issue if you encounter a bug, have a
suggestion, or would like to discuss improvements.

------------------------------------------------------------------------

## ✨ Features

-   YAML-based configuration
-   Configuration inheritance
-   Environment variable resolution (`${MY_VAR}`)
-   Self-referencing config values (e.g., experiment names based on
    hyperparameters)
-   Automatic experiment directory creation
-   Frozen `requirements.txt` snapshot
-   Source code snapshot
-   Automatic stdout/stderr logging
-   Command-line hyperparameter overrides

> [!WARNING]
> Current limitation: lists of objects are not yet supported in the configuration file.

------------------------------------------------------------------------

## 🚀 Installation

### Install with pip

``` bash
pip install expyrun
```

### Install from source

``` bash
git clone https://github.com/raphaelreme/expyrun.git
cd expyrun
pip install .
```

------------------------------------------------------------------------

## 🏁 Getting Started

Expyrun is a command-line tool. Once installed:

``` bash
expyrun -h  # Display Expyrun help
expyrun path/to/config.yml  # Run the experiments described by the YAML configuration
expyrun path/to/config.yml --debug  # Run in a debug-specific folder and using the original code without duplication
```

### 1️⃣ Create an entry point

Your code must expose a function with the following signature:

``` python
def entry_point(name: str, config: dict) -> None:
    ...
```

-   `name`: the experiment name
-   `config`: the parsed configuration dictionary

Expyrun will import and execute this function.

------------------------------------------------------------------------

### 2️⃣ Minimal configuration file

``` yaml
__run__:
  __main__: package.module:entry_point
  __output_dir__: /path/to/output_dir
  __name__: my_experiment

# Additional configuration passed to your function
# seed: 666
# data: /path/to/data
# device: cuda
```

#### `__run__` section fields

| Key                | Required   | Description |
| ------------------ | ---------- | --------------------------------------------------- |
| `__main__`         | ✅         | Entry point in the form `package.module:function` |
| `__output_dir__`   | ✅         | Base directory where experiments are stored |
| `__name__`         | ✅         | Experiment name (used to build output path) |
| `__code__`         | ❌         | Optional path to the source code |

By default, Expyrun searches for your package in the current working
directory.\
You can override this using `__code__`.

> [!NOTE]
> As of now, Expyrun only duplicates the package of the `__main__` entry point, which is searched inside `__code__` folder.
> Consequently, all of your code should be contained into a single package (which may consist of multiple subpackages)

------------------------------------------------------------------------

## 📦 What Expyrun Generates

For each run, Expyrun creates:

    {output_dir}/{name}/exp.{i}/ # If run without --debug (default)
    {output_dir}/DEBUG/{name}/exp.{i}  # if run with --debug

Inside:

-   `config.yml` --- parsed configuration
-   `raw_config.yml` --- original configuration
-   `frozen_requirements.txt` --- environment snapshot
-   `outputs.log` --- stdout/stderr log
-   A copy of your source code package

From inside your entry function, the working directory is automatically
set to the experiment folder.\
You can safely write outputs (models, logs, metrics, etc.) directly to
the current directory.

> [!NOTE]
> Expyrun does not copy external dependencies such as datasets (usually to heavy).
> You are responsible for keeping data paths valid when reproducing
> experiments.

------------------------------------------------------------------------

## 🧩 Configuration File Format

Expyrun reserves three special sections in YAML files.

### `__default__`

Inherit configuration from other YAML files.

``` yaml
__default__: path/to/base.yml
```

Or:

``` yaml
__default__:
  - base.yml
  - other.yml
```

Paths may be:
- Absolute: `/path/to/file.yml`
- Relative to CWD: `path/to/file.yml`
- Relative to the config file: `./path/to/file.yml`

This allows you to build modular experiment configurations.

------------------------------------------------------------------------

### `__new_key_policy__`

Defines how new keys are handled when inheriting.

Options:
- `"raise"` --- Error
- `"warn"` --- Warning (Default)
- `"pass"` --- Silently accept

A *new key* is one not defined in any parent configs.

> [!NOTE]
> This does not apply to a base configuration (with no parent).

------------------------------------------------------------------------

### `__run__`

Defines how the experiment should be executed.

``` yaml
__run__:
  __main__: package.module:function
  __name__: experiment_name
  __output_dir__: /base/output/path
  __code__: optional/path/to/code
```

------------------------------------------------------------------------


### User-defined configuration

Any parameters that your experiment needs to run. For example:

``` yaml
seed: 666

training:
  lr: 0.0001
  epochs: 50

datasets:
  - Cifar10
  - Cifar100
  - ImageNet
```

## 🧪 Concrete Example

> [!TIP]
> See the example/ directory in the repository for a minimal working example.

### Project structure

```
my_project/
├── data/
├── src/
│   ├── __init__.py
│   ├── utils.py
│   ├── data.py
|   ├── methods.py
│   └── experiments/
│       ├── __init__.py
│       ├── train.py
│       └── eval.py
├── configs/
│   ├── data.yml
│   ├── methods.yml
│   └── experiments/
│       ├── common.yml
│       ├── train.yml
│       └── eval.yml
```

------------------------------------------------------------------------
`data.yml`

``` yaml
data:
  location: $DATA_FOLDER
  train_size: 0.7
```


------------------------------------------------------------------------
`methods.yml`

``` yaml
ResNet:
  layers: 50
  epochs: 200
  lr: 0.001

ViT:
  epochs: 30
  lr: 0.0005
  patch_size: 16
```
------------------------------------------------------------------------
`common.yml`

``` yaml
seed: 666
device: cuda
```
------------------------------------------------------------------------
`train.yml`

``` yaml
__default__:
  - ../data.yml
  - ../methods.yml
  - ./common.yml

__run__:
  __main__: src.experiments.train:main
  __output_dir__: $OUTPUT_DIR
  __name__: training/{seed}  # Name can depend on the seed
```
------------------------------------------------------------------------
`eval.yml`

``` yaml
__new_key_policy__: pass  # Allow new keys

__default__: ./train.yml  # Inherit from train and therefore from common, data and methods

__run__:
  __main__: src.experiments.eval:main
  __name__: evaluation/{seed}

training_exp: 0  # Id of the training exp to reload
training_folder: $OUTPUT_DIR/training/{seed}/exp.{training_exp}/
```

### ▶  Running Experiments

From the root of my_project:

``` bash
# Set up the required env variables (could be inside ~/.bashrc)
export OUTPUT_DIR=/path/to/output
export DATA_FOLDER=/path/to/data

# Then run expyrun
expyrun configs/experiments/train.yml
```

With debug mode:
``` bash
expyrun configs/experiments/train.yml --debug
```

Override parameters from the CLI:
``` bash
expyrun configs/experiments/eval.yml --training_exp 3
```

### 📂 Output Structure Example
After running, you typically get:
```
$OUTPUT_DIR/
├── training/
│   └── 666/
│       └── exp.0/
│           ├── config.yml
│           ├── raw_config.yml
│           ├── frozen_requirements.txt
│           ├── outputs.log
│           ├── src/
│           └── checkpoints/
│               ├── ViT.ckpt
│               └── ResNet.ckpt
└── evaluation/
    └── 666/
        └── exp.0/
            └── ...
```


### 🔁 Reproducing Experiments

### Exact reproduction

``` bash
# Will reproduce this previous experiments into the next available exp.{i} folder
expyrun $OUTPUT_DIR/training/666/exp.0/config.yml
```

### Modify hyperparameters

``` bash
expyrun $OUTPUT_DIR/training/666/exp.0/raw_config.yml --ResNet.lr 0.005 --seed 111
```

-   `config.yml` → parsed, fixed configuration
-   `raw_config.yml` → original config; recommended when modifying
    parameters: If you change a hyperparameter that affects the experiment name (i.e. `seed`), the
    directory will automatically adapt.

------------------------------------------------------------------------

## Parsing Variables

Expyrun resolves environment variables inside YAML, as well as self references:

``` yaml
data_path: $DATA_FOLDER
dataset: ${DATASET}_raw
seed: 555
output_path: $OUTPUT_FOLDER/{seed}
```

------------------------------------------------------------------------

## Environment Variables

Expyrun defines the following variables:

### `EXPYRUN_CWD`

The original working directory from which Expyrun was launched.

This can be useful if your code needs to know where execution started
before Expyrun switches to the experiment directory.

------------------------------------------------------------------------

## 💡 Tips

* Consider using `dataclasses` and `dacite` to convert configuration dictionaries into strongly-typed Python objects.

* Keep datasets versioned or documented externally for full reproducibility.

* Use inheritance (`__default__`) to build clean experiment hierarchies.

------------------------------------------------------------------------

## 📜 License

MIT License
