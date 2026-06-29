import json
import sys


def dump(data: dict, stream=None) -> None:
    if stream is None:
        stream = sys.stdout
    stream.write(json.dumps(data, indent=2))
    stream.write("\n")
