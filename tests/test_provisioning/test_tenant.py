"""Tests for tenant provisioning."""

import pytest
import time

from maven_core.backends.files.local import LocalFileStore
from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.provisioning.tenant import (
    TenantConfig,
    TenantManager,
    TenantProvisionResult,
)


@pytest.fixture
def file_store(tmp_path) -> LocalFileStore:
    """Create a local file store."""
    return LocalFileStore(tmp_path)


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store."""
    return MemoryKVStore()


@pytest.fixture
def tenant_manager(file_store, kv_store) -> TenantManager:
    """Create a tenant manager."""
    return TenantManager(file_store, kv_store)


class TestTenantConfig:
    """Tests for TenantConfig dataclass."""

    def test_to_dict(self) -> None:
        """Convert config to dictionary."""
        config = TenantConfig(
            tenant_id="tenant-123",
            name="Test Tenant",
            created_at=1234567890.0,
            updated_at=1234567900.0,
            status="active",
            settings={"key": "value"},
            limits={"max_users": 100},
            metadata={"env": "test"},
        )

        d = config.to_dict()

        assert d["tenant_id"] == "tenant-123"
        assert d["name"] == "Test Tenant"
        assert d["status"] == "active"
        assert d["settings"]["key"] == "value"

    def test_from_dict(self) -> None:
        """Create config from dictionary."""
        d = {
            "tenant_id": "tenant-456",
            "name": "Another Tenant",
            "created_at": 1234567890.0,
            "updated_at": 1234567890.0,
            "status": "suspended",
            "settings": {},
            "limits": {},
            "metadata": {},
        }

        config = TenantConfig.from_dict(d)

        assert config.tenant_id == "tenant-456"
        assert config.status == "suspended"


class TestTenantProvisioning:
    """Tests for tenant provisioning."""

    @pytest.mark.asyncio
    async def test_create_tenant(self, tenant_manager: TenantManager) -> None:
        """Create a new tenant."""
        result = await tenant_manager.create_tenant(
            name="My Company",
            settings={"theme": "dark"},
        )

        assert result.success is True
        assert result.tenant_id.startswith("tenant-")
        assert result.config.name == "My Company"
        assert result.config.status == "active"
        assert result.config.settings["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_create_tenant_with_id(self, tenant_manager: TenantManager) -> None:
        """Create tenant with specific ID."""
        result = await tenant_manager.create_tenant(
            name="Specific ID Tenant",
            tenant_id="my-tenant",
        )

        assert result.success is True
        assert result.tenant_id == "my-tenant"

    @pytest.mark.asyncio
    async def test_create_tenant_duplicate(self, tenant_manager: TenantManager) -> None:
        """Cannot create tenant with duplicate ID."""
        await tenant_manager.create_tenant(name="First", tenant_id="duplicate")

        result = await tenant_manager.create_tenant(
            name="Second",
            tenant_id="duplicate",
        )

        assert result.success is False
        assert "already exists" in result.message

    @pytest.mark.asyncio
    async def test_create_tenant_default_limits(
        self, tenant_manager: TenantManager
    ) -> None:
        """Tenant gets default limits if not specified."""
        result = await tenant_manager.create_tenant(name="Default Limits")

        assert result.config.limits.get("max_sessions") is not None
        assert result.config.limits.get("max_users") is not None

    @pytest.mark.asyncio
    async def test_create_tenant_custom_limits(
        self, tenant_manager: TenantManager
    ) -> None:
        """Custom limits override defaults."""
        result = await tenant_manager.create_tenant(
            name="Custom Limits",
            limits={"max_users": 500},
        )

        assert result.config.limits["max_users"] == 500


class TestTenantRetrieval:
    """Tests for tenant retrieval."""

    @pytest.mark.asyncio
    async def test_get_tenant(self, tenant_manager: TenantManager) -> None:
        """Get tenant by ID."""
        await tenant_manager.create_tenant(name="Get Test", tenant_id="get-test")

        config = await tenant_manager.get_tenant("get-test")

        assert config is not None
        assert config.tenant_id == "get-test"
        assert config.name == "Get Test"

    @pytest.mark.asyncio
    async def test_get_tenant_not_found(self, tenant_manager: TenantManager) -> None:
        """Get non-existent tenant returns None."""
        config = await tenant_manager.get_tenant("nonexistent")
        assert config is None

    @pytest.mark.asyncio
    async def test_tenant_exists(self, tenant_manager: TenantManager) -> None:
        """Check if tenant exists."""
        await tenant_manager.create_tenant(name="Exists Test", tenant_id="exists")

        assert await tenant_manager.tenant_exists("exists") is True
        assert await tenant_manager.tenant_exists("not-exists") is False

    @pytest.mark.asyncio
    async def test_is_tenant_active(self, tenant_manager: TenantManager) -> None:
        """Check if tenant is active."""
        await tenant_manager.create_tenant(name="Active Test", tenant_id="active")

        assert await tenant_manager.is_tenant_active("active") is True
        assert await tenant_manager.is_tenant_active("not-exists") is False


class TestTenantUpdate:
    """Tests for tenant updates."""

    @pytest.mark.asyncio
    async def test_update_tenant_name(self, tenant_manager: TenantManager) -> None:
        """Update tenant name."""
        await tenant_manager.create_tenant(name="Original", tenant_id="update-name")

        updated = await tenant_manager.update_tenant(
            "update-name", name="Updated Name"
        )

        assert updated is not None
        assert updated.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_tenant_settings(self, tenant_manager: TenantManager) -> None:
        """Update tenant settings."""
        await tenant_manager.create_tenant(
            name="Settings Test",
            tenant_id="update-settings",
            settings={"key1": "value1"},
        )

        updated = await tenant_manager.update_tenant(
            "update-settings", settings={"key2": "value2"}
        )

        assert updated is not None
        # Original settings preserved, new ones added
        assert updated.settings["key1"] == "value1"
        assert updated.settings["key2"] == "value2"

    @pytest.mark.asyncio
    async def test_update_tenant_not_found(
        self, tenant_manager: TenantManager
    ) -> None:
        """Update non-existent tenant returns None."""
        result = await tenant_manager.update_tenant("nonexistent", name="New Name")
        assert result is None


class TestTenantLifecycle:
    """Tests for tenant lifecycle management."""

    @pytest.mark.asyncio
    async def test_suspend_tenant(self, tenant_manager: TenantManager) -> None:
        """Suspend a tenant."""
        await tenant_manager.create_tenant(name="To Suspend", tenant_id="suspend")

        result = await tenant_manager.suspend_tenant("suspend")

        assert result is True

        config = await tenant_manager.get_tenant("suspend")
        assert config.status == "suspended"
        assert await tenant_manager.is_tenant_active("suspend") is False

    @pytest.mark.asyncio
    async def test_activate_tenant(self, tenant_manager: TenantManager) -> None:
        """Activate a suspended tenant."""
        await tenant_manager.create_tenant(name="To Activate", tenant_id="activate")
        await tenant_manager.suspend_tenant("activate")

        result = await tenant_manager.activate_tenant("activate")

        assert result is True

        config = await tenant_manager.get_tenant("activate")
        assert config.status == "active"
        assert await tenant_manager.is_tenant_active("activate") is True

    @pytest.mark.asyncio
    async def test_soft_delete_tenant(self, tenant_manager: TenantManager) -> None:
        """Soft delete a tenant (mark as deleted)."""
        await tenant_manager.create_tenant(name="To Delete", tenant_id="soft-delete")

        result = await tenant_manager.delete_tenant("soft-delete", soft_delete=True)

        assert result is True

        config = await tenant_manager.get_tenant("soft-delete")
        assert config is not None
        assert config.status == "deleted"

    @pytest.mark.asyncio
    async def test_hard_delete_tenant(self, tenant_manager: TenantManager) -> None:
        """Hard delete a tenant (remove data)."""
        await tenant_manager.create_tenant(name="To Delete", tenant_id="hard-delete")

        result = await tenant_manager.delete_tenant("hard-delete", soft_delete=False)

        assert result is True

        config = await tenant_manager.get_tenant("hard-delete")
        assert config is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_tenant(
        self, tenant_manager: TenantManager
    ) -> None:
        """Delete non-existent tenant returns False."""
        result = await tenant_manager.delete_tenant("nonexistent")
        assert result is False


class TestTenantListing:
    """Tests for tenant listing."""

    @pytest.mark.asyncio
    async def test_list_tenants_empty(self, tenant_manager: TenantManager) -> None:
        """List tenants when none exist."""
        tenants = await tenant_manager.list_tenants()
        assert tenants == []

    @pytest.mark.asyncio
    async def test_list_tenants(self, tenant_manager: TenantManager) -> None:
        """List all tenants."""
        await tenant_manager.create_tenant(name="Tenant 1", tenant_id="tenant-1")
        await tenant_manager.create_tenant(name="Tenant 2", tenant_id="tenant-2")
        await tenant_manager.create_tenant(name="Tenant 3", tenant_id="tenant-3")

        tenants = await tenant_manager.list_tenants()

        assert len(tenants) == 3
        ids = {t.tenant_id for t in tenants}
        assert ids == {"tenant-1", "tenant-2", "tenant-3"}

    @pytest.mark.asyncio
    async def test_list_tenants_filter_status(
        self, tenant_manager: TenantManager
    ) -> None:
        """List tenants filtered by status."""
        await tenant_manager.create_tenant(name="Active", tenant_id="active")
        await tenant_manager.create_tenant(name="Suspended", tenant_id="suspended")
        await tenant_manager.suspend_tenant("suspended")

        active_tenants = await tenant_manager.list_tenants(status="active")
        assert len(active_tenants) == 1
        assert active_tenants[0].tenant_id == "active"

        suspended_tenants = await tenant_manager.list_tenants(status="suspended")
        assert len(suspended_tenants) == 1
        assert suspended_tenants[0].tenant_id == "suspended"

    @pytest.mark.asyncio
    async def test_list_tenants_pagination(
        self, tenant_manager: TenantManager
    ) -> None:
        """List tenants with pagination."""
        for i in range(5):
            await tenant_manager.create_tenant(
                name=f"Tenant {i}", tenant_id=f"tenant-{i}"
            )

        # Get first 2
        page1 = await tenant_manager.list_tenants(limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2
        page2 = await tenant_manager.list_tenants(limit=2, offset=2)
        assert len(page2) == 2

        # Get last 1
        page3 = await tenant_manager.list_tenants(limit=2, offset=4)
        assert len(page3) == 1
