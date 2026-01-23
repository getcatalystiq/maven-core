"""Tests for RBAC manager."""

import pytest

from maven_core.backends.database.sqlite import SQLiteDatabase
from maven_core.exceptions import NotFoundError, PermissionDeniedError
from maven_core.rbac.manager import PermissionManager


@pytest.fixture
async def db():
    """Create an in-memory SQLite database."""
    database = SQLiteDatabase(path=":memory:")
    yield database
    await database.close()


@pytest.fixture
async def rbac(db):
    """Create a permission manager with initialized schema."""
    manager = PermissionManager(db, tenant_id="test-tenant")
    await manager.initialize_schema()

    # Create default roles for testing
    await manager.create_role("admin", "Administrator role")
    await manager.create_role("user", "Regular user role")
    await manager.create_role("editor", "Editor role")

    return manager


class TestPermissionManager:
    """Tests for PermissionManager."""

    @pytest.mark.asyncio
    async def test_create_role(self, rbac):
        """Test creating a new role."""
        role = await rbac.create_role("viewer", "View-only access")

        assert role.name == "viewer"
        assert role.description == "View-only access"

    @pytest.mark.asyncio
    async def test_get_role(self, rbac):
        """Test getting an existing role."""
        role = await rbac.get_role("admin")

        assert role.name == "admin"
        assert role.description == "Administrator role"

    @pytest.mark.asyncio
    async def test_get_nonexistent_role(self, rbac):
        """Test getting a role that doesn't exist."""
        with pytest.raises(NotFoundError):
            await rbac.get_role("nonexistent")

    @pytest.mark.asyncio
    async def test_list_roles(self, rbac):
        """Test listing all roles."""
        roles = await rbac.list_roles()

        role_names = [r.name for r in roles]
        assert "admin" in role_names
        assert "user" in role_names

    @pytest.mark.asyncio
    async def test_assign_and_get_user_roles(self, rbac):
        """Test assigning roles to a user."""
        await rbac.assign_role("user-123", "admin")
        await rbac.assign_role("user-123", "editor")

        roles = await rbac.get_user_roles("user-123")

        assert "admin" in roles
        assert "editor" in roles

    @pytest.mark.asyncio
    async def test_revoke_role(self, rbac):
        """Test revoking a role from a user."""
        await rbac.assign_role("user-123", "admin")
        await rbac.assign_role("user-123", "user")

        await rbac.revoke_role("user-123", "admin")
        roles = await rbac.get_user_roles("user-123")

        assert "admin" not in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_grant_skill_access(self, rbac):
        """Test granting skill access to a role."""
        await rbac.grant_skill_access("my-skill", "editor")

        roles = await rbac.get_skill_roles("my-skill")
        assert "editor" in roles

    @pytest.mark.asyncio
    async def test_revoke_skill_access(self, rbac):
        """Test revoking skill access from a role."""
        await rbac.grant_skill_access("my-skill", "editor")
        await rbac.grant_skill_access("my-skill", "admin")

        await rbac.revoke_skill_access("my-skill", "editor")
        roles = await rbac.get_skill_roles("my-skill")

        assert "editor" not in roles
        assert "admin" in roles

    @pytest.mark.asyncio
    async def test_can_access_skill_no_restrictions(self, rbac):
        """Test that unrestricted skills are accessible by anyone."""
        # Skill has no role restrictions
        can_access = await rbac.can_access_skill(["user"], "unrestricted-skill")
        assert can_access is True

    @pytest.mark.asyncio
    async def test_can_access_skill_with_matching_role(self, rbac):
        """Test skill access with matching role."""
        await rbac.grant_skill_access("restricted-skill", "editor")

        can_access = await rbac.can_access_skill(["editor"], "restricted-skill")
        assert can_access is True

    @pytest.mark.asyncio
    async def test_cannot_access_skill_without_role(self, rbac):
        """Test skill access denied without required role."""
        await rbac.grant_skill_access("restricted-skill", "editor")

        can_access = await rbac.can_access_skill(["user"], "restricted-skill")
        assert can_access is False

    @pytest.mark.asyncio
    async def test_admin_always_has_access(self, rbac):
        """Test that admin role always has skill access."""
        await rbac.grant_skill_access("restricted-skill", "editor")

        can_access = await rbac.can_access_skill(["admin"], "restricted-skill")
        assert can_access is True

    @pytest.mark.asyncio
    async def test_require_role_success(self, rbac):
        """Test require_role with matching role."""
        # Should not raise
        await rbac.require_role(["admin", "user"], "admin")

    @pytest.mark.asyncio
    async def test_require_role_failure(self, rbac):
        """Test require_role without matching role."""
        with pytest.raises(PermissionDeniedError):
            await rbac.require_role(["user"], "admin")

    @pytest.mark.asyncio
    async def test_require_skill_access_success(self, rbac):
        """Test require_skill_access with access."""
        # Unrestricted skill - should not raise
        await rbac.require_skill_access(["user"], "unrestricted-skill")

    @pytest.mark.asyncio
    async def test_require_skill_access_failure(self, rbac):
        """Test require_skill_access without access."""
        await rbac.grant_skill_access("restricted-skill", "editor")

        with pytest.raises(PermissionDeniedError):
            await rbac.require_skill_access(["user"], "restricted-skill")
