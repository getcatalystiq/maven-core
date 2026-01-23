"""Plugin discovery via Python entry points."""

from importlib.metadata import entry_points
from typing import Any, TypeVar

from maven_core.protocols import Database, FileStore, KVStore, SandboxBackend

T = TypeVar("T")

BACKEND_GROUPS = {
    "files": "maven_core.backends.files",
    "kv": "maven_core.backends.kv",
    "database": "maven_core.backends.database",
    "sandbox": "maven_core.backends.sandbox",
}


def discover_backends(group: str) -> dict[str, Any]:
    """Discover all registered backends for a given group.

    Args:
        group: The backend group name (files, kv, database, sandbox)

    Returns:
        Dictionary mapping backend names to their classes
    """
    full_group = BACKEND_GROUPS.get(group, group)
    eps = entry_points(group=full_group)
    return {ep.name: ep.load() for ep in eps}


def get_backend(group: str, name: str) -> Any:
    """Get a specific backend class by group and name.

    Args:
        group: The backend group name (files, kv, database, sandbox)
        name: The backend name (e.g., "local", "cloudflare_r2")

    Returns:
        The backend class

    Raises:
        ValueError: If the backend is not found
    """
    backends = discover_backends(group)
    if name not in backends:
        available = ", ".join(sorted(backends.keys())) or "(none)"
        raise ValueError(
            f"Backend '{name}' not found in group '{group}'. Available: {available}"
        )
    return backends[name]


def create_file_store(backend: str, **kwargs: Any) -> FileStore:
    """Create a FileStore instance.

    Args:
        backend: The backend name (e.g., "local", "cloudflare_r2")
        **kwargs: Backend-specific configuration

    Returns:
        A FileStore implementation
    """
    cls = get_backend("files", backend)
    return cls(**kwargs)


def create_kv_store(backend: str, **kwargs: Any) -> KVStore:
    """Create a KVStore instance.

    Args:
        backend: The backend name (e.g., "memory", "cloudflare_kv")
        **kwargs: Backend-specific configuration

    Returns:
        A KVStore implementation
    """
    cls = get_backend("kv", backend)
    return cls(**kwargs)


def create_database(backend: str, **kwargs: Any) -> Database:
    """Create a Database instance.

    Args:
        backend: The backend name (e.g., "sqlite", "cloudflare_d1")
        **kwargs: Backend-specific configuration

    Returns:
        A Database implementation
    """
    cls = get_backend("database", backend)
    return cls(**kwargs)


def create_sandbox_backend(backend: str, **kwargs: Any) -> SandboxBackend:
    """Create a SandboxBackend instance.

    Args:
        backend: The backend name (e.g., "local", "cloudflare")
        **kwargs: Backend-specific configuration

    Returns:
        A SandboxBackend implementation
    """
    cls = get_backend("sandbox", backend)
    return cls(**kwargs)
