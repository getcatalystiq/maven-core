"""Base protocol for infrastructure provisioning providers.

Defines the interface that all provisioning providers must implement.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class BucketInfo:
    """Information about a created storage bucket."""

    name: str
    binding_name: str
    endpoint: str | None = None
    region: str | None = None


@dataclass
class DatabaseInfo:
    """Information about a created database."""

    name: str
    binding_name: str
    database_id: str | None = None


@dataclass
class DomainInfo:
    """Information about a configured custom domain."""

    domain: str
    dns_record_id: str | None = None
    ssl_certificate_id: str | None = None
    status: str = "pending"


@dataclass
class DeploymentInfo:
    """Information about a worker deployment."""

    version: str
    deployed_at: float
    bindings_updated: list[str]


@runtime_checkable
class InfraProvider(Protocol):
    """Protocol for infrastructure provisioning providers.

    Implementations must provide methods for creating and managing
    tenant-specific infrastructure resources.
    """

    async def create_bucket(self, tenant_id: str, name: str) -> BucketInfo:
        """Create a dedicated storage bucket for a tenant.

        Args:
            tenant_id: Tenant identifier
            name: Bucket name

        Returns:
            BucketInfo with created bucket details
        """
        ...

    async def create_database(self, tenant_id: str, name: str) -> DatabaseInfo:
        """Create a dedicated database instance for a tenant.

        Args:
            tenant_id: Tenant identifier
            name: Database name

        Returns:
            DatabaseInfo with created database details
        """
        ...

    async def update_worker_bindings(
        self, tenant_id: str, resources: dict[str, Any]
    ) -> None:
        """Update Worker configuration with new resource bindings.

        Args:
            tenant_id: Tenant identifier
            resources: Dict of resource info (bucket, database, etc.)
        """
        ...

    async def deploy_worker(self) -> DeploymentInfo:
        """Redeploy the Worker with updated bindings.

        Returns:
            DeploymentInfo with deployment details
        """
        ...

    async def configure_domain(self, tenant_id: str, domain: str) -> DomainInfo:
        """Configure a custom domain for a tenant.

        Args:
            tenant_id: Tenant identifier
            domain: Custom domain to configure

        Returns:
            DomainInfo with domain configuration details
        """
        ...

    async def store_tenant_config(
        self, tenant_id: str, config: dict[str, Any]
    ) -> None:
        """Store tenant configuration for runtime resource routing.

        Args:
            tenant_id: Tenant identifier
            config: Configuration to store (binding names, tier, etc.)
        """
        ...

    async def cleanup(self, tenant_id: str) -> None:
        """Remove all tenant infrastructure (for rollback on failure).

        Args:
            tenant_id: Tenant identifier
        """
        ...

    async def verify_connectivity(self, tenant_id: str) -> bool:
        """Verify that tenant infrastructure is accessible.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if all resources are accessible
        """
        ...
