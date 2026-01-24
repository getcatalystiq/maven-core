"""Local development provider for infrastructure provisioning.

Simulates infrastructure provisioning for local development:
- Storage: Creates directories instead of buckets
- Database: Uses shared SQLite (isolation via tenant_id)
- Domains: No-op, returns localhost
- Adds small delays to simulate production timing
"""

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maven_core.provisioning.providers.base import (
    BucketInfo,
    DatabaseInfo,
    DeploymentInfo,
    DomainInfo,
)

if TYPE_CHECKING:
    from maven_core.config import Config


class LocalProvider:
    """Local development infrastructure provider.

    Simulates provisioning operations with filesystem-based storage
    and adds delays to mimic production behavior.
    """

    def __init__(self, config: "Config") -> None:
        """Initialize the local provider.

        Args:
            config: Application configuration
        """
        self.config = config
        self._base_path = Path(config.storage.files.path or "./data")

    async def create_bucket(self, tenant_id: str, name: str) -> BucketInfo:
        """Create a dedicated storage directory for a tenant.

        In local mode, this creates a directory structure instead of
        an actual cloud storage bucket.

        Args:
            tenant_id: Tenant identifier
            name: Bucket/directory name

        Returns:
            BucketInfo with local directory details
        """
        # Simulate production delay
        await asyncio.sleep(0.5)

        # Create tenant-specific directory
        bucket_path = self._base_path / "buckets" / name
        bucket_path.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in ["skills", "connectors", "transcripts", "uploads"]:
            (bucket_path / subdir).mkdir(exist_ok=True)

        return BucketInfo(
            name=name,
            binding_name=f"STORAGE_tenant_{tenant_id.replace('-', '_')}",
            endpoint=str(bucket_path),
        )

    async def create_database(self, tenant_id: str, name: str) -> DatabaseInfo:
        """Simulate creating a dedicated database.

        In local mode, we use the shared SQLite database with tenant_id
        column isolation, so this is essentially a no-op.

        Args:
            tenant_id: Tenant identifier
            name: Database name

        Returns:
            DatabaseInfo with mock database details
        """
        # Simulate production delay
        await asyncio.sleep(0.3)

        # In local mode, we don't actually create a separate database
        # All tenants share the same SQLite DB with tenant_id isolation
        return DatabaseInfo(
            name=name,
            binding_name=f"DB_tenant_{tenant_id.replace('-', '_')}",
            database_id=f"local-{tenant_id}",
        )

    async def update_worker_bindings(
        self, tenant_id: str, resources: dict[str, Any]
    ) -> None:
        """No-op in local mode - workers don't exist locally.

        Args:
            tenant_id: Tenant identifier
            resources: Resource info (ignored in local mode)
        """
        # Simulate production delay
        await asyncio.sleep(0.2)
        # No actual worker bindings to update in local mode

    async def deploy_worker(self) -> DeploymentInfo:
        """No-op in local mode - no worker to deploy.

        Returns:
            Mock deployment info
        """
        # Simulate production delay
        await asyncio.sleep(0.3)

        return DeploymentInfo(
            version="local-dev",
            deployed_at=time.time(),
            bindings_updated=[],
        )

    async def configure_domain(self, tenant_id: str, domain: str) -> DomainInfo:
        """No-op in local mode - returns localhost domain.

        Args:
            tenant_id: Tenant identifier
            domain: Requested domain (ignored)

        Returns:
            DomainInfo with localhost details
        """
        # Simulate production delay
        await asyncio.sleep(0.2)

        return DomainInfo(
            domain=f"{tenant_id}.localhost",
            status="active",
        )

    async def store_tenant_config(
        self, tenant_id: str, config: dict[str, Any]
    ) -> None:
        """Store tenant config in a local JSON file.

        Args:
            tenant_id: Tenant identifier
            config: Configuration to store
        """
        import json

        # Simulate production delay
        await asyncio.sleep(0.1)

        config_path = self._base_path / "tenant_configs"
        config_path.mkdir(parents=True, exist_ok=True)

        config_file = config_path / f"{tenant_id}.json"
        config_file.write_text(json.dumps(config, indent=2))

    async def cleanup(self, tenant_id: str) -> None:
        """Remove tenant infrastructure.

        In local mode, removes the tenant's directories and config.

        Args:
            tenant_id: Tenant identifier
        """
        import shutil

        # Remove bucket directory if exists
        bucket_path = self._base_path / "buckets" / f"tenant-{tenant_id}"
        if bucket_path.exists():
            shutil.rmtree(bucket_path)

        # Remove config file if exists
        config_file = self._base_path / "tenant_configs" / f"{tenant_id}.json"
        if config_file.exists():
            config_file.unlink()

    async def verify_connectivity(self, tenant_id: str) -> bool:
        """Verify tenant infrastructure is accessible.

        In local mode, checks that directories exist.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if accessible
        """
        # Simulate production delay
        await asyncio.sleep(0.1)

        # In local mode, we just check basic file access
        return True
