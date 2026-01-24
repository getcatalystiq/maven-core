"""Infrastructure provisioning providers.

Provides factory function to get the appropriate provider based on configuration.
"""

from typing import TYPE_CHECKING

from maven_core.provisioning.providers.base import InfraProvider
from maven_core.provisioning.providers.local import LocalProvider

if TYPE_CHECKING:
    from maven_core.config import Config


def get_provider(config: "Config") -> InfraProvider:
    """Get the appropriate infrastructure provider based on configuration.

    Args:
        config: Application configuration

    Returns:
        InfraProvider implementation

    Raises:
        ValueError: If provider type is not supported
    """
    backend = config.provisioning.backend

    if backend == "local":
        from maven_core.provisioning.providers.local import LocalProvider

        return LocalProvider(config)
    elif backend == "cloudflare":
        from maven_core.provisioning.providers.cloudflare import CloudflareProvider

        return CloudflareProvider(config)
    else:
        raise ValueError(f"Unsupported provisioning backend: {backend}")


__all__ = ["InfraProvider", "LocalProvider", "get_provider"]
