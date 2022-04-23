# Expyrun

Running reproducible experiments from a yaml configuration file.

Expyrun is a command-line script that will launch your code from
a yaml configuration file and register in the output directory everything
needed to reproduce the run.

The configuration file is a yaml film with some specifications:
- List of objects are not supported yet.
- Environement variables are parsed and resolved. (\$MY_VAR or ${MY_VAR})
- The config can reference itself, for instance make the name of the experiment
depends on value of some keys. See the examples.


## Install

### Pip

```bash
$ pip install expyrun
```

### Conda

Not yet available


## Getting started

Expyrun is a command-line tool. You can directly use it once install:

```bash
$ expyrun -h
$ expyrun path/to/my/experiment/configuration.yml
```

You only have to adapt your code to be executable from an main function expecting a name
and a dict configuration for the run. Note that you should probably look at dacite and dataclasses
to create nicely typed configuration in your code. But this is out of the scope of expyrun.

## Create configuration files
### Configuration file format
There are three special sections reserved for expyrun in the yaml files:

- \_\_default__: Inherit keys and values from one or several other configurations
    (can be a string or a list of strings). Each path can be absolute (/path/to/default.yml),
    relative to the current directory (path/to/default.yml) or relative to the current yaml
    config (./path/to/default.yml). If not set, it is considered empty.
    This allows you to build common default configuration between your experiences.

- \_\_new_key_policy__: How to handle new keys in a configuration that inherits from others.
    Accepted values: "raise", "warn", "pass". Default: "warn".
    A new key is a key that is present in the current configuration but absent from any of
    its parents (which is probably weird).

- \_\_run__: The most import section. It defines the metadata for running your experiment.
    It has itself 4 differents sections:
    - \_\_main__: Main function to run (Mandatory). Expected signature: Callable[[str, dict], None].
        This function will be called with the experiment name and the experiment configuration.
        A valid main function string is given as package.subpackage.module:function.
        Expyrun will search the package inside the current working directory.
    - \_\_name__: Name of the experiment. (Mandatory) Used to compute the true output directory,
        it will be given to the main function.
    - \_\_output_dir__: Base path for outputs to be stored (Mandatory). The outputs will be stored
        in {output_dir}/{name}/exp.{i} or {output_dir}/DEBUG/{name}/exp.{i} in debug mode.
        (for the ith experiment of the same name)
    - \_\_code__: Optional path to the code. Expyrun search the code package in the current
        working directory by default. This allows you to change this behavior.

### One example
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

Different experiments can be launch in experiments package. (One file by experiment). And some code is shared between experiments,
for instance the code handling the data.

A simple way to create the configuration files would be to create a new configs directory following roughly the architecture of the code7
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
    lr: 0.001
    batch_size: 10
```

```yml
# second_method.yml

__default__: ./first_method.yml

__run__:
    __main__: my_code.experiments.second_method:main

seed: 777

model:
    name: MyModelBis

training:
    lr: 0.1
    size: [10, 10]
```

Then within a terminal in `my_project` directory, you can launch experiments with

```bash
$ expyrun configs/experiments/first_method.yml [--debug]
# Change hyper parameters from arguments:
$ expyrun configs/experiments/second_method.yml --training.size 15,15
```

Have a look at `example` folder which implements another simple example.

## Build and Deploy

```bash
$ pip install build twine
$ python -m build
$ python -m twine upload dist/*
```
