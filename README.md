# Expyrun

[![Lint and Test](https://github.com/raphaelreme/expyrun/actions/workflows/tests.yml/badge.svg)](https://github.com/raphaelreme/expyrun/actions/workflows/tests.yml)

Running reproducible experiments from a yaml configuration file.

Expyrun is a command-line script that will launch your code from
a yaml configuration file and register in the output directory everything
needed to reproduce the run.

The configuration file is a yaml film with some specifications:
- List of objects are not supported yet.
- Environment variables are parsed and resolved. (\$MY_VAR or ${MY_VAR})
- The config can reference itself, for instance, make the name of the experiment
depending on the value of some keys. See the examples.


## Install

### Pip

```bash
$ pip install expyrun
```

### Conda

Not available yet


## Getting started

Expyrun is a command-line tool. You can directly use it once installed:

```bash
$ expyrun -h
$ expyrun path/to/my/experiment/configuration.yml
```

In order to work, you have to build an entry point in your code which is a function
that takes as inputs a string (name of the experiment) and a dictionary (configuration
of the experiment). This function will be imported and run by Expyrun.

The minimal configuration file is:
```yml
__run__:
    __main__: package.module:entry_point  # How to find your entry point
    __output_dir__: /path/to/output_dir  # Where to store experiments
    __name__: my_experiment  # Name of the experiment

# Additional configuration will be given to your code
# For instance:
# seed: 666
#
# data: /path/to/data
#
# device: cuda
#
# model:
#   name: resnet
#   size: 18
```

It can be stored anywhere. When running Expyrun, the package of your entry point should
be in the current working directory. Or you can specify a \_\_code__ key in \_\_run__
section, to indicate where the code should be found.

Notes:
- Expyrun will create an experiment folder in which it will put the configuration (and raw configuration,
see the example), frozen requirements, and a copy of the source code. Almost everything you need to run
your experiment again. It will also redirect your stdout and stderr to outputs.log file.
- From your function perspective, the current working directory is this experiment directory,
therefore results (model weights, data preprocessing, etc) can be saved directly in it.
- Expyrun does not try to copy all your dependencies (for instance data read by your code), as this
would be too heavy. You are responsible to keep the data the code reads at the same location. Or
you should overwrite the location of the data when reproducing.
- You should probably look at dacite and dataclasses to create nicely typed configuration in your code.
But this is out of the scope of Expyrun.

## Configuration file format
There are three special sections reserved for Expyrun in the yaml files:

- \_\_default__: Inherit keys and values from one or several other configurations
    (can be a string or a list of strings). Each path can be absolute (/path/to/default.yml),
    relative to the current directory (path/to/default.yml), or relative to the current yaml
    config (./path/to/default.yml). If not set, it is considered empty.
    This allows you to build a common default configuration between your experiences.

- \_\_new_key_policy__: How to handle new keys in a configuration that inherits from others.
    Accepted values: "raise", "warn", "pass". Default: "warn".
    A new key is a key that is present in the current configuration but absent from any of
    its parents (which is probably weird).

- \_\_run__: The most important section. It defines the metadata for running your experiment.
    It has 4 different keys:
    - \_\_main__: Main function to run (Mandatory). Expected signature: Callable[[str, dict], None].
        This function will be called with the experiment name and the experiment configuration.
        A valid main function string is given as package.subpackage.module:function.
        Expyrun will search the package inside the current working directory.
    - \_\_name__: Name of the experiment. (Mandatory) Used to compute the true output directory,
        it will be given to the main function.
    - \_\_output_dir__: Base path for outputs to be stored (Mandatory). The outputs will be stored
        in {output_dir}/{name}/exp.{i} or {output_dir}/DEBUG/{name}/exp.{i} in debug mode.
        (for the ith experiment of the same name)
    - \_\_code__: Optional path to the code. Expyrun searches the code package in the current
        working directory by default. This allows you to change this behavior.

## Concrete example
Let's assume the following architecture

- my_project/
    - data/
    - my_code/
        - \_\_init__.py
        - utils.py
        - data.py
        - experiments/
            - \_\_init__.py
            - first_method.py
            - second_method.py
    - .git/
    - .gitignore
    - README.md

Different experiments can be launched in the `experiments` package. (One file by experiment). And some code is shared between experiments,
for instance, the code handling the data.

A simple way to create the configuration files would be to create a new configs directory following roughly the architecture of the code
- my_project/
    - configs/
        - data.yml
        - experiments/
            - first_method.yml
            - second_method.yml


```yml
# data.yml

data:
    location: $DATA_FOLDER
    train_size: 0.7
```

```yml
# first_method.yml

__default__: ../data.yml

__run__:
    __main__: my_code.experiments.first_method:main
    __output_dir__: $OUTPUT_DIR
    __name__: first_method/{model.name}-{training.lr}

seed: 666

model:
    name: MyModel

training:
    seed: "{seed}"  # Have to add "" when starting with { char
    lr: 0.001
    batch_size: 10
```

```yml
# second_method.yml

__default__: ./first_method.yml

__run__:
    __main__: my_code.experiments.second_method:main
    __name__: second_method/{model.name}-{training.size}

seed: 777

model:
    name: MyModelBis

training:
    lr: 0.1
    size: [10, 10]
```

Then within a terminal in the `my_project` directory, you can launch experiments with

```bash
$ expyrun configs/experiments/first_method.yml [--debug]
# Change hyper parameters from arguments:
$ expyrun configs/experiments/second_method.yml --training.size 15,15
```

Have a look at the `example` folder which implements another simple example.

After running these two experiments $OUTPUT_DIR is filled this way:
- $OUTPUT_DIR/
    - first_method/
        - MyModel-0.0001/
            - exp.0/
                - config.yml
                - frozen_requirements.txt
                - my_code/
                - outputs.log
                - raw_config.yml
    - second_method/
        - MyModelBis-[10,10]/
            - exp.0/
                - config.yml
                - frozen_requirements.txt
                - my_code/
                - outputs.log
                - raw_config.yml

To execute them again precisely, you should build a new environment
from the frozen_requirements. Then execute Expyrun with the config.yml file.

To start from an experiment and change some hyperparameters,
then use the raw_config.yml file and use args in command-line to overwrite
what you want. (raw_config is the unparsed config. Therefore if you change
some hyperparameters, other values, for instance the name, will be adapted too.)

```bash
# Reproduce and change existing experiments
$ expyrun $OUTPUT_DIR/first_method/MyModel-0.0001/exp.0/config.yml
$ expyrun $OUTPUT_DIR/first_method/MyModel-0.0001/exp.0/raw_config.yml --training.lr 0.001  # Name will be format with the new value of lr
```

After running these two lines here is the output tree:
- $OUTPUT_DIR/
    - first_method/
        - MyModel-0.0001/
            - exp.0/
            - exp.1/
        - MyModel-0.001/
            - exp.0/
    - second_method/
        - MyModelBis-[10,10]/
            - exp.0/


## Environment variables used by Expyrun

- `EXPYRUN_CWD`: Working directory when expyrun has been launched. Expyrun will set this variable before changing to the real working directory.
    Can be useful to know exactly where we came from.


## Build and Deploy

```bash
$ python -m build
$ python -m twine upload dist/*
```
