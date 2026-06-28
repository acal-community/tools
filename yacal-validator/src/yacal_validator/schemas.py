"""Schema loading: filesystem path or GitHub URL, with local caching.

Cache lives at ~/.cache/yacal-validator/schemas/{source_hash}/.
Refresh with --refresh-schemas.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx

_CACHE_ROOT = Path.home() / ".cache" / "yacal-validator" / "schemas"

SCHEMA_FILES: dict[str, str] = {
    "core_structure": "acal-core-yaml-v1.0-structure.schema.yaml",
    "core_constraints": "acal-core-yaml-v1.0-constraints.yaml",
    "xpath_structure": "acal-xpath-yaml-v1.0-structure.schema.yaml",
    "jsonpath_structure": "acal-jsonpath-yaml-v1.0-structure.schema.yaml",
}


class SchemaStore:
    def __init__(self, source: str, branch: str = "main", refresh: bool = False) -> None:
        self.source = source.rstrip("/")
        self.branch = branch
        self._is_url = _is_http(source)
        cache_key = hashlib.sha256(f"{source}@{branch}".encode()).hexdigest()[:16]
        self._cache = _CACHE_ROOT / cache_key
        self._refresh = refresh

    @property
    def cache_dir(self) -> Path:
        return self._cache

    def resolve(self, filename: str) -> Path:
        """Return a local path to *filename*, fetching or copying if needed."""
        dest = self._cache / filename
        if dest.exists() and not self._refresh:
            return dest
        if self._is_url:
            url = _raw_url(self.source, self.branch, filename)
            _download(url, dest)
        else:
            src = Path(self.source) / filename
            if not src.exists():
                raise FileNotFoundError(f"Schema not found: {src}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return dest

    def try_resolve(self, filename: str) -> Path | None:
        """Like resolve(), but returns None instead of raising."""
        try:
            return self.resolve(filename)
        except (FileNotFoundError, httpx.HTTPError, httpx.HTTPStatusError):
            return None

    def prefetch_all(self) -> None:
        """Download all known schema files; silently skip missing optional ones."""
        for fname in SCHEMA_FILES.values():
            self.try_resolve(fname)


def _is_http(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def _raw_url(repo_url: str, branch: str, filename: str) -> str:
    """Convert a GitHub repo URL to a raw content URL for *filename*."""
    parsed = urlparse(repo_url)
    parts = parsed.path.strip("/").split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse GitHub URL: {repo_url!r}")
    owner, repo = parts
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filename}"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        r = client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
