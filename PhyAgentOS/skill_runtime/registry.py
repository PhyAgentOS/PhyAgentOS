"""Anonymous Resource Registry client with resumable content-addressed downloads."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

from PhyAgentOS.config.loader import load_config
from PhyAgentOS.config.paths import get_artifact_cache_root
from PhyAgentOS.skill_runtime.archive import sha256_file


class RegistryError(RuntimeError):
    """Raised when registry metadata or an artifact download is invalid."""


def get_registry_base_url() -> str:
    """Resolve the registry URL, with the explicit PAOS environment override first."""
    configured = os.environ.get("PAOS_RESOURCE_REGISTRY_URL", "").strip()
    if not configured:
        configured = load_config().resource_registry.url.strip()
    if not configured.startswith(("http://", "https://")):
        raise RegistryError(
            "Resource Registry URL is not configured; set PAOS_RESOURCE_REGISTRY_URL "
            "or resourceRegistry.url"
        )
    return configured.rstrip("/")


@dataclass(frozen=True)
class RegistryArtifact:
    """Download coordinates returned by the Resource Registry."""

    url: str
    sha256: str | None = None
    size: int | None = None
    name: str | None = None
    version: str | None = None
    artifact_set_id: str | None = None
    mode: str | None = None
    runtime_digest: str | None = None
    node_digest: str | None = None

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

        runtime_digest = optional_string("runtime_digest", "artifact_set_digest")
        if runtime_digest is not None and (
            len(runtime_digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in runtime_digest)
        ):
            raise RegistryError("registry artifact has an invalid runtime digest")
        node_digest = optional_string("node_digest")
        if node_digest is not None and (
            len(node_digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in node_digest)
        ):
            raise RegistryError("registry artifact has an invalid node digest")
        return cls(
            url=url,
            sha256=digest.lower(),
            size=size,
            name=optional_string("name"),
            version=optional_string("version"),
            artifact_set_id=optional_string("artifact_set_id", "artifactSetId"),
            mode=optional_string("mode"),
            runtime_digest=runtime_digest.lower() if runtime_digest else None,
            node_digest=node_digest.lower() if node_digest else None,
        )


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

    def skill(self, name: str, version: str | None = None) -> RegistryArtifact:
        suffix = f"/{quote(version, safe='')}" if version else ""
        value = self._get(f"/v1/skills/{quote(name, safe='')}{suffix}")
        return RegistryArtifact.from_dict(value)

    def runtime(self, artifact_set_id: str) -> RegistryArtifact:
        value = self._get(f"/v1/forge-runtimes/{quote(artifact_set_id, safe='')}")
        return RegistryArtifact.from_dict(value)

    def node(self, artifact_id: str) -> RegistryArtifact:
        value = self._get(f"/v1/forge-nodes/{quote(artifact_id, safe='')}")
        return RegistryArtifact.from_dict(value)


class StaticPackageIndex:
    """Minimal Skill/Node locator backed by one schema-v3 YAML document."""

    def __init__(
        self,
        source: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.source = source
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.packages = self._load()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> StaticPackageIndex:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _load(self) -> list[dict[str, Any]]:
        try:
            if self.source.startswith(("http://", "https://")):
                response = self.client.get(self.source, headers={"Accept": "application/yaml"})
                response.raise_for_status()
                value = yaml.safe_load(response.text)
            else:
                value = yaml.safe_load(Path(self.source).expanduser().read_text(encoding="utf-8"))
        except (OSError, httpx.HTTPError, yaml.YAMLError) as exc:
            raise RegistryError(f"cannot load static package index: {self.source}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 3:
            raise RegistryError("static package index must use schema_version 3")
        packages = value.get("packages")
        if not isinstance(packages, list) or not all(isinstance(item, dict) for item in packages):
            raise RegistryError("static package index packages must be a list")
        return packages

    def search_skills(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.casefold()
        return [
            {
                "name": item.get("package_key", ""),
                "version": item.get("version", ""),
                "description": "static package index",
            }
            for item in self.packages
            if item.get("kind") == "skill_bundle"
            and (not needle or needle in str(item.get("package_key", "")).casefold())
            and item.get("direct_download_url")
        ]

    def _entry(
        self,
        *,
        kind: str,
        package_key: str | None = None,
        version: str | None = None,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        matches = [
            item
            for item in self.packages
            if item.get("kind") == kind
            and (package_key is None or item.get("package_key") == package_key)
            and (version is None or str(item.get("version")) == version)
            and (artifact_id is None or item.get("artifact_id") == artifact_id)
        ]
        if not matches:
            identity = artifact_id or package_key or kind
            raise RegistryError(f"package is not present in static index: {identity}")
        if version is None:
            matches.sort(key=lambda item: str(item.get("version", "")), reverse=True)
        return matches[0]

    @staticmethod
    def _artifact(item: dict[str, Any]) -> RegistryArtifact:
        url = item.get("direct_download_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise RegistryError("static package does not have a direct_download_url")
        return RegistryArtifact(
            url=url,
            name=str(item.get("package_key", "")) or None,
            version=str(item.get("version", "")) or None,
            mode="direct",
            node_digest=(
                str(item["node_digest"]).lower()
                if isinstance(item.get("node_digest"), str)
                else None
            ),
        )

    def skill(self, name: str, version: str | None = None) -> RegistryArtifact:
        return self._artifact(
            self._entry(kind="skill_bundle", package_key=name, version=version)
        )

    def node(self, artifact_id: str) -> RegistryArtifact:
        return self._artifact(self.node_metadata(artifact_id))

    def node_metadata(self, artifact_id: str) -> dict[str, Any]:
        return self._entry(kind="node_bundle", artifact_id=artifact_id)


class DownloadCache:
    """Resumable archive cache rooted at ``cache/<sha256>/``."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.root = (root or get_artifact_cache_root()).expanduser()
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

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
                return final
            final.unlink()

        offset = partial.stat().st_size if partial.is_file() else 0
        if offset > artifact.size:
            partial.unlink()
            offset = 0
        if offset == artifact.size:
            return self._commit(artifact, partial, final)
        headers = {"Accept": "application/gzip"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
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
                with partial.open(mode) as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError("artifact download failed; partial download was retained") from exc
        return self._commit(artifact, partial, final)

    def _download_direct(self, artifact: RegistryArtifact) -> Path:
        cache_key = hashlib.sha256(artifact.url.encode()).hexdigest()
        cache_dir = self.root / "direct" / cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        final = cache_dir / "archive.tar.gz"
        temporary = cache_dir / "archive.tar.gz.part"
        if final.is_file() and final.stat().st_size > 0:
            return final
        try:
            with self.client.stream(
                "GET", artifact.url, headers={"Accept": "application/gzip"}
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError("direct artifact download failed") from exc
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RegistryError("direct artifact download is empty")
        os.replace(temporary, final)
        return final

    def _download_fresh(
        self, artifact: RegistryArtifact, partial: Path, final: Path
    ) -> Path:
        try:
            with self.client.stream(
                "GET", artifact.url, headers={"Accept": "application/gzip"}
            ) as response:
                response.raise_for_status()
                self._validate_content_length(response, artifact.size)
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except httpx.HTTPError as exc:
            raise RegistryError("artifact download failed; partial download was retained") from exc
        return self._commit(artifact, partial, final)

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
