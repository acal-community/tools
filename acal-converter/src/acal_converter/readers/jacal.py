import json


def load(path: str, strict: bool = False) -> dict:
    """Load a JACAL document. The strict parameter is accepted for API
    compatibility with the XACML reader but is currently a no-op.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
