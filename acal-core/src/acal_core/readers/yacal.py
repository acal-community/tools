import ruamel.yaml


def load(path: str, strict: bool = False) -> dict:
    """Load a YACAL document. The strict parameter is accepted for API
    compatibility with the XACML reader but is currently a no-op.
    """
    yaml = ruamel.yaml.YAML()
    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh)
    return _to_plain(data)


def _to_plain(obj):
    """Recursively convert ruamel.yaml CommentedMap/CommentedSeq to plain dict/list."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj
