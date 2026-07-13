import sys
import ruamel.yaml

_yaml = ruamel.yaml.YAML()
_yaml.default_flow_style = False
_yaml.width = 120


def dump(data: dict, stream=None) -> None:
    if stream is None:
        stream = sys.stdout
    _yaml.dump(data, stream)
