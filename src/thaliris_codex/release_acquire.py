"""Acquire an externally selected release; no unsigned 'latest' discovery."""
from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlsplit

from . import release_identity as identity


def download(url: str, *, limit: int = 128 * 1024 * 1024) -> bytes:
    if urlsplit(url).scheme != "https" or urlsplit(url).username or urlsplit(url).password:
        raise ValueError("release download requires credential-free HTTPS")
    with urlopen(url, timeout=60) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("release download redirected outside HTTPS")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("release download exceeds size limit")
    return raw


def acquire(manifest_source: str, expected_sha256: str, destination: Path) -> tuple[dict, dict[str, Path]]:
    """Each invocation owns a new leaf; never replace downloaded/candidate bytes."""
    raw = (download(manifest_source, limit=1024 * 1024) if manifest_source.startswith("https://")
           else Path(manifest_source).read_bytes())
    binding = identity.binding(raw, expected_sha256)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "release.json").write_bytes(raw)
    wheels = {}
    for name, artifact in binding["manifest"]["artifacts"].items():
        data = download(artifact["url"])
        if identity.sha256(data) != artifact["sha256"]:
            raise ValueError(f"release {name} artifact SHA-256 mismatch")
        path = destination / artifact["filename"]
        with path.open("xb") as stream:
            stream.write(data)
        wheels[name] = path
    return binding, wheels
