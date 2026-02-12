"""Run the code with expyrun.

```bash
$ DATA_FOLDER=/root/data expyrun config/example.yml
```
"""

import pathlib
import sys

import yaml


def main(name: str, config: dict) -> None:
    print("Hello from experiment:", name)
    print("-----------------CFG-------------------")
    print(yaml.dump(config))
    print("-----------------CWD-------------------")
    print(pathlib.Path.cwd())
    print("---------------__file__----------------")
    print(__file__)
    print("-----------------PATH------------------")
    print(sys.path)


if __name__ == "__main__":
    main("Local", {})
