"""Tenant provisioning and lifecycle management."""

import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from maven_core.protocols import FileStore, KVStore, Database


@dataclass
class TenantConfig:
    """Configuration for a tenant."""

    tenant_id: str
    name: str
    created_at: float
    updated_at: float
    status: str  # "active", "suspended", "deleted"
    settings: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "settings": self.settings,
            "limits": self.limits,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantConfig":
        """Create from dictionary."""
        return cls(
            tenant_id=data["tenant_id"],
            name=data["name"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            status=data["status"],
            settings=data.get("settings", {}),
            limits=data.get("limits", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TenantProvisionResult:
    """Result of tenant provisioning."""

    tenant_id: str
    config: TenantConfig
    success: bool
    message: str
    provisioned_at: float


class TenantManager:
    """Manages tenant provisioning and lifecycle.

    Handles:
    - Creating new tenants with isolated storage
    - Updating tenant configuration
    - Suspending and deleting tenants
    - Listing and querying tenants
    """

    def __init__(
        self,
        files: FileStore,
        kv: KVStore,
        db: Database | None = None,
    ) -> None:
        """Initialize tenant manager.

        Args:
            files: File storage backend (for tenant configs and data)
            kv: KV storage backend (for fast lookups)
            db: Optional database backend (for RBAC and user data)
        """
        self.files = files
        self.kv = kv
        self.db = db

    def _config_key(self, tenant_id: str) -> str:
        """Get file key for tenant config."""
        return f"tenants/{tenant_id}/config.json"

    def _index_key(self, tenant_id: str) -> str:
        """Get KV key for tenant index entry."""
        return f"tenant:{tenant_id}"

    def _tenant_list_key(self) -> str:
        """Get KV key for tenant list."""
        return "tenants:list"

    async def create_tenant(
        self,
        name: str,
        tenant_id: str | None = None,
        settings: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TenantProvisionResult:
        """Create and provision a new tenant.

        Args:
            name: Tenant display name
            tenant_id: Optional tenant ID (generated if not provided)
            settings: Initial tenant settings
            limits: Resource limits for the tenant
            metadata: Additional metadata

        Returns:
            Provisioning result
        """
        if tenant_id is None:
            tenant_id = f"tenant-{uuid4().hex[:12]}"

        # Check if tenant already exists
        existing = await self.get_tenant(tenant_id)
        if existing:
            return TenantProvisionResult(
                tenant_id=tenant_id,
                config=existing,
                success=False,
                message=f"Tenant already exists: {tenant_id}",
                provisioned_at=time.time(),
            )

        now = time.time()
        config = TenantConfig(
            tenant_id=tenant_id,
            name=name,
            created_at=now,
            updated_at=now,
            status="active",
            settings=settings or {},
            limits=limits or self._default_limits(),
            metadata=metadata or {},
        )

        # Save tenant config
        await self.files.put(
            self._config_key(tenant_id),
            json.dumps(config.to_dict(), indent=2).encode(),
            content_type="application/json",
        )

        # Add to KV index for fast lookup
        await self.kv.set(
            self._index_key(tenant_id),
            json.dumps({"tenant_id": tenant_id, "name": name, "status": "active"}).encode(),
        )

        # Add to tenant list
        await self._add_to_tenant_list(tenant_id)

        # Create tenant storage directories (skills, connectors, etc.)
        await self._create_tenant_directories(tenant_id)

        # Initialize database schema if DB is available
        if self.db:
            await self._init_tenant_database(tenant_id)

        return TenantProvisionResult(
            tenant_id=tenant_id,
            config=config,
            success=True,
            message=f"Tenant provisioned successfully: {tenant_id}",
            provisioned_at=now,
        )

    def _default_limits(self) -> dict[str, Any]:
        """Get default resource limits for a tenant."""
        return {
            "max_sessions": 1000,
            "max_skills": 100,
            "max_connectors": 50,
            "max_users": 100,
            "storage_mb": 1024,
            "sandbox_timeout_seconds": 30,
            "sandbox_memory_mb": 256,
        }

    async def _add_to_tenant_list(self, tenant_id: str) -> None:
        """Add tenant to the global tenant list."""
        key = self._tenant_list_key()
        existing = await self.kv.get(key)

        if existing:
            tenants = json.loads(existing.decode())
        else:
            tenants = []

        if tenant_id not in tenants:
            tenants.append(tenant_id)
            await self.kv.set(key, json.dumps(tenants).encode())

    async def _remove_from_tenant_list(self, tenant_id: str) -> None:
        """Remove tenant from the global tenant list."""
        key = self._tenant_list_key()
        existing = await self.kv.get(key)

        if existing:
            tenants = json.loads(existing.decode())
            if tenant_id in tenants:
                tenants.remove(tenant_id)
                await self.kv.set(key, json.dumps(tenants).encode())

    async def _create_tenant_directories(self, tenant_id: str) -> None:
        """Create storage directories for tenant data."""
        # Create placeholder files to establish directory structure
        directories = [
            f"tenants/{tenant_id}/skills/.gitkeep",
            f"tenants/{tenant_id}/connectors/.gitkeep",
            f"tenants/{tenant_id}/transcripts/.gitkeep",
        ]

        for path in directories:
            await self.files.put(path, b"", content_type="text/plain")

    async def _init_tenant_database(self, tenant_id: str) -> None:
        """Initialize database schema for tenant if using RBAC."""
        if not self.db:
            return

        # The RBAC schema is tenant-scoped by the tenant_id column
        # No additional initialization needed if schema is already created

    async def get_tenant(self, tenant_id: str) -> TenantConfig | None:
        """Get tenant configuration.

        Args:
            tenant_id: Tenant ID

        Returns:
            Tenant configuration or None if not found
        """
        result = await self.files.get(self._config_key(tenant_id))
        if not result:
            return None

        content, _ = result
        return TenantConfig.from_dict(json.loads(content.decode()))

    async def update_tenant(
        self,
        tenant_id: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TenantConfig | None:
        """Update tenant configuration.

        Args:
            tenant_id: Tenant ID
            name: New name (if provided)
            settings: Settings to merge (if provided)
            limits: Limits to merge (if provided)
            metadata: Metadata to merge (if provided)

        Returns:
            Updated configuration or None if tenant not found
        """
        config = await self.get_tenant(tenant_id)
        if not config:
            return None

        # Update fields
        if name:
            config.name = name
        if settings:
            config.settings.update(settings)
        if limits:
            config.limits.update(limits)
        if metadata:
            config.metadata.update(metadata)

        config.updated_at = time.time()

        # Save updated config
        await self.files.put(
            self._config_key(tenant_id),
            json.dumps(config.to_dict(), indent=2).encode(),
            content_type="application/json",
        )

        # Update KV index
        await self.kv.set(
            self._index_key(tenant_id),
            json.dumps({
                "tenant_id": tenant_id,
                "name": config.name,
                "status": config.status,
            }).encode(),
        )

        return config

    async def suspend_tenant(self, tenant_id: str) -> bool:
        """Suspend a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if suspended, False if not found
        """
        config = await self.get_tenant(tenant_id)
        if not config:
            return False

        config.status = "suspended"
        config.updated_at = time.time()

        await self.files.put(
            self._config_key(tenant_id),
            json.dumps(config.to_dict(), indent=2).encode(),
            content_type="application/json",
        )

        await self.kv.set(
            self._index_key(tenant_id),
            json.dumps({
                "tenant_id": tenant_id,
                "name": config.name,
                "status": "suspended",
            }).encode(),
        )

        return True

    async def activate_tenant(self, tenant_id: str) -> bool:
        """Activate a suspended tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if activated, False if not found
        """
        config = await self.get_tenant(tenant_id)
        if not config:
            return False

        config.status = "active"
        config.updated_at = time.time()

        await self.files.put(
            self._config_key(tenant_id),
            json.dumps(config.to_dict(), indent=2).encode(),
            content_type="application/json",
        )

        await self.kv.set(
            self._index_key(tenant_id),
            json.dumps({
                "tenant_id": tenant_id,
                "name": config.name,
                "status": "active",
            }).encode(),
        )

        return True

    async def delete_tenant(self, tenant_id: str, soft_delete: bool = True) -> bool:
        """Delete a tenant.

        Args:
            tenant_id: Tenant ID
            soft_delete: If True, mark as deleted but keep data

        Returns:
            True if deleted, False if not found
        """
        config = await self.get_tenant(tenant_id)
        if not config:
            return False

        if soft_delete:
            # Mark as deleted
            config.status = "deleted"
            config.updated_at = time.time()

            await self.files.put(
                self._config_key(tenant_id),
                json.dumps(config.to_dict(), indent=2).encode(),
                content_type="application/json",
            )

            await self.kv.set(
                self._index_key(tenant_id),
                json.dumps({
                    "tenant_id": tenant_id,
                    "name": config.name,
                    "status": "deleted",
                }).encode(),
            )
        else:
            # Hard delete - remove all data
            # Delete config
            await self.files.delete(self._config_key(tenant_id))
            await self.kv.delete(self._index_key(tenant_id))

            # Delete tenant directories (would need to list and delete all files)
            # For now, just remove from list
            await self._remove_from_tenant_list(tenant_id)

        return True

    async def list_tenants(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TenantConfig]:
        """List all tenants.

        Args:
            status: Filter by status (optional)
            limit: Maximum tenants to return
            offset: Number to skip

        Returns:
            List of tenant configurations
        """
        # Get tenant list from KV
        list_data = await self.kv.get(self._tenant_list_key())
        if not list_data:
            return []

        tenant_ids = json.loads(list_data.decode())

        # Apply pagination
        tenant_ids = tenant_ids[offset : offset + limit]

        # Load configs
        result = []
        for tenant_id in tenant_ids:
            config = await self.get_tenant(tenant_id)
            if config:
                if status is None or config.status == status:
                    result.append(config)

        return result

    async def tenant_exists(self, tenant_id: str) -> bool:
        """Check if a tenant exists.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if tenant exists (any status)
        """
        data = await self.kv.get(self._index_key(tenant_id))
        return data is not None

    async def is_tenant_active(self, tenant_id: str) -> bool:
        """Check if a tenant is active.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if tenant exists and is active
        """
        data = await self.kv.get(self._index_key(tenant_id))
        if not data:
            return False

        try:
            info = json.loads(data.decode())
            return info.get("status") == "active"
        except (json.JSONDecodeError, KeyError):
            return False
