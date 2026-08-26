"""Anonymous Resource Registry client with resumable content-addressed downloads."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from PhyAgentOS.config.loader import load_config
from PhyAgentOS.config.paths import get_artifact_cache_root
from PhyAgentOS.config.schema import DEFAULT_RESOURCE_REGISTRY_URL
from PhyAgentOS.skill_runtime.archive import sha256_file


class RegistryError(RuntimeError):
    """Raised when registry metadata or an artifact download is invalid."""


def get_registry_base_url() -> str:
    """Resolve the registry URL, with the explicit PAOS environment override first."""
    configured = os.environ.get("PAOS_RESOURCE_REGISTRY_URL", "").strip()
    if not configured:
        configured = load_config().resource_registry.url.strip()
    if not configured:
        configured = DEFAULT_RESOURCE_REGISTRY_URL
    if not configured.startswith(("http://", "https://")):
        raise RegistryError(
            "Resource Registry URL must use HTTP(S); set PAOS_RESOURCE_REGISTRY_URL "
            "or resourceRegistry.url to override the default"
        )
    return configured.rstrip("/")


@dataclass(frozen=True)
class RegistryArtifact:
    """Download coordinates returned by the Resource Registry."""

    url: str
    sha256: str | None = None
    size: int | None = None
    name: str | None = None
    artifact_id: str | None = None
    mode: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> RegistryArtifact:
        if not isinstance(value, dict):
            raise RegistryError("registry artifact metadata must be an object")
        source = value.get("artifact", value)
        if not isinstance(source, dict):
            raise RegistryError("registry artifact field must be an object")
        url = source.get("download_url", source.get("url"))
        digest = source.get("sha256", source.get("digest"))
        size = source.get("size", source.get("content_length"))
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise RegistryError("registry artifact has an invalid download URL")
        if (digest is None) != (size is None):
            raise RegistryError("registry artifact must provide both sha256 and size")
        if digest is not None:
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in digest)
            ):
                raise RegistryError("registry artifact has an invalid sha256")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise RegistryError("registry artifact has an invalid size")

        def optional_string(*names: str) -> str | None:
            for name in names:
                item = value.get(name, source.get(name))
                if isinstance(item, str) and item:
                    return item
            return None

        mode = optional_string("mode")
        if mode == "verified" and digest is None:
            raise RegistryError("verified registry artifact is missing sha256 and size")
        return cls(
            url=url,
            sha256=digest.lower() if isinstance(digest, str) else None,
            size=size,
            name=optional_string("name"),
            artifact_id=optional_string("artifact_id"),
            mode=mode,
        )


DownloadProgressCallback = Callable[[str, RegistryArtifact, int, int | None], None]


class RegistryClient:
    """Small synchronous client for public, anonymous registry endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or get_registry_base_url()).rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> RegistryClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        try:
            response = self.client.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RegistryError(f"Resource Registry request failed: {path}") from exc

    def search_skills(self, query: str = "") -> list[dict[str, Any]]:
        value = self._get("/v1/skills", params={"q": query} if query else None)
        if isinstance(value, dict):
            value = value.get("items", value.get("skills"))
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise RegistryError("registry skill search response must contain an item list")
        return value

    def skill(self, name: str) -> RegistryArtifact:
        value = self._get(f"/v1/skills/{quote(name, safe='')}")
        artifact = RegistryArtifact.from_dict(value)
        if artifact.sha256 is None or artifact.size is None:
            raise RegistryError("registry Skill is missing required sha256 and size")
        return artifact

    def node(self, artifact_id: str) -> RegistryArtifact:
        value = self._get(f"/v1/forge-nodes/{quote(artifact_id, safe='')}")
        return RegistryArtifact.from_dict(value)


class DownloadCache:
    """Resumable archive cache rooted at ``cache/<sha256>/``."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        progress: DownloadProgressCallback | None = None,
    ) -> None:
        self.root = (root or get_artifact_cache_root()).expanduser()
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.progress = progress

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def download(self, artifact: RegistryArtifact) -> Path:
        if artifact.sha256 is None or artifact.size is None:
            return self._download_direct(artifact)
        cache_dir = self.root / artifact.sha256
        cache_dir.mkdir(parents=True, exist_ok=True)
        final = cache_dir / "archive.tar.gz"
        partial = cache_dir / "archive.tar.gz.part"
        if final.is_file():
            if final.stat().st_size == artifact.size and sha256_file(final) == artifact.sha256:
                self._notify("cached", artifact, artifact.size, artifact.size)
                return final
            final.unlink()

        offset = partial.stat().st_size if partial.is_file() else 0
        if offset > artifact.size:
            partial.unlink()
            offset = 0
        if offset == artifact.size:
            result = self._commit(artifact, partial, final)
            self._notify("complete", artifact, artifact.size, artifact.size)
            return result
        headers = {"Accept": "application/gzip"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        self._notify("start", artifact, offset, artifact.size)
        try:
            with self.client.stream("GET", artifact.url, headers=headers) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    partial.unlink(missing_ok=True)
                    return self._download_fresh(artifact, partial, final)
                if offset:
                    content_range = response.headers.get("Content-Range", "")
                    expected_range = (
                        f"bytes {offset}-{artifact.size - 1}/{artifact.size}"
                    )
                    if content_range != expected_range:
                        raise RegistryError("download resume Content-Range does not match request")
                self._validate_content_length(response, artifact.size - offset)
                mode = "ab" if offset else "wb"
                downloaded = offset
                with partial.open(mode) as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        downloaded += len(chunk)
                        self._notify("advance", artifact, downloaded, artifact.size)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError(
                f"artifact download failed for {artifact.url}: {exc}; "
                "partial download was retained"
            ) from exc
        result = self._commit(artifact, partial, final)
        self._notify("complete", artifact, artifact.size, artifact.size)
        return result

    def _download_direct(self, artifact: RegistryArtifact) -> Path:
        cache_key = hashlib.sha256(artifact.url.encode()).hexdigest()
        cache_dir = self.root / "direct" / cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        final = cache_dir / "artifact.download"
        temporary = cache_dir / "artifact.download.part"
        if final.is_file() and final.stat().st_size > 0:
            self._notify("cached", artifact, final.stat().st_size, final.stat().st_size)
            return final
        self._notify("start", artifact, 0, None)
        try:
            with self.client.stream(
                "GET", artifact.url, headers={"Accept": "application/gzip"}
            ) as response:
                response.raise_for_status()
                total = self._response_content_length(response)
                self._notify("start", artifact, 0, total)
                downloaded = 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        downloaded += len(chunk)
                        self._notify("advance", artifact, downloaded, total)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError(
                f"direct artifact download failed for {artifact.url}: {exc}"
            ) from exc
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RegistryError("direct artifact download is empty")
        os.replace(temporary, final)
        self._notify("complete", artifact, final.stat().st_size, final.stat().st_size)
        return final

    def _download_fresh(
        self, artifact: RegistryArtifact, partial: Path, final: Path
    ) -> Path:
        self._notify("start", artifact, 0, artifact.size)
        try:
            with self.client.stream(
                "GET", artifact.url, headers={"Accept": "application/gzip"}
            ) as response:
                response.raise_for_status()
                self._validate_content_length(response, artifact.size)
                downloaded = 0
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        downloaded += len(chunk)
                        self._notify("advance", artifact, downloaded, artifact.size)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError(
                f"artifact download failed for {artifact.url}: {exc}; "
                "partial download was retained"
            ) from exc
        result = self._commit(artifact, partial, final)
        assert artifact.size is not None
        self._notify("complete", artifact, artifact.size, artifact.size)
        return result

    def _notify(
        self,
        event: str,
        artifact: RegistryArtifact,
        downloaded: int,
        total: int | None,
    ) -> None:
        if self.progress is not None:
            self.progress(event, artifact, downloaded, total)

    @staticmethod
    def _response_content_length(response: httpx.Response) -> int | None:
        raw = response.headers.get("Content-Length")
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value >= 0 else None

    @staticmethod
    def _validate_content_length(response: httpx.Response, expected: int) -> None:
        raw = response.headers.get("Content-Length")
        if raw is None:
            raise RegistryError("artifact response is missing Content-Length")
        try:
            actual = int(raw)
        except ValueError as exc:
            raise RegistryError("artifact response has invalid Content-Length") from exc
        if actual != expected:
            raise RegistryError(
                f"artifact Content-Length mismatch: expected {expected}, received {actual}"
            )

    @staticmethod
    def _commit(artifact: RegistryArtifact, partial: Path, final: Path) -> Path:
        assert artifact.size is not None and artifact.sha256 is not None
        if partial.stat().st_size != artifact.size:
            raise RegistryError("downloaded artifact size does not match registry metadata")
        digest = sha256_file(partial)
        if digest != artifact.sha256:
            partial.unlink(missing_ok=True)
            raise RegistryError("downloaded artifact sha256 does not match registry metadata")
        os.replace(partial, final)
        return final
