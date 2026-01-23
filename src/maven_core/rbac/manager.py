"""RBAC (Role-Based Access Control) manager."""

from dataclasses import dataclass
from pathlib import Path

from maven_core.exceptions import NotFoundError, PermissionDeniedError
from maven_core.protocols import Database


@dataclass
class Role:
    """A role definition."""

    id: str
    name: str
    description: str | None


class PermissionManager:
    """Manages role-based access control.

    Uses deny-first logic: access is denied unless explicitly granted.
    """

    def __init__(self, database: Database, tenant_id: str) -> None:
        """Initialize permission manager.

        Args:
            database: Database backend
            tenant_id: Current tenant ID
        """
        self.database = database
        self.tenant_id = tenant_id

    async def initialize_schema(self) -> None:
        """Initialize the RBAC schema in the database."""
        schema_path = Path(__file__).parent / "schema.sql"
        schema = schema_path.read_text()

        # Execute each statement separately
        for statement in schema.split(";"):
            statement = statement.strip()
            if statement:
                await self.database.execute(statement)

    async def create_role(self, name: str, description: str | None = None) -> Role:
        """Create a new role.

        Args:
            name: Role name (lowercase, alphanumeric with hyphens)
            description: Optional description

        Returns:
            The created role
        """
        role_id = f"role-{self.tenant_id}-{name}"

        await self.database.execute(
            """
            INSERT INTO roles (id, tenant_id, name, description)
            VALUES (:id, :tenant_id, :name, :description)
            """,
            {
                "id": role_id,
                "tenant_id": self.tenant_id,
                "name": name,
                "description": description,
            },
        )

        return Role(id=role_id, name=name, description=description)

    async def get_role(self, name: str) -> Role:
        """Get a role by name.

        Args:
            name: Role name

        Returns:
            The role

        Raises:
            NotFoundError: If role doesn't exist
        """
        rows = await self.database.execute(
            """
            SELECT id, name, description FROM roles
            WHERE tenant_id = :tenant_id AND name = :name
            """,
            {"tenant_id": self.tenant_id, "name": name},
        )
        if not rows:
            raise NotFoundError(f"Role not found: {name}")

        row = rows[0]
        return Role(id=row.id, name=row.name, description=row.description)

    async def list_roles(self) -> list[Role]:
        """List all roles for the tenant.

        Returns:
            List of roles
        """
        rows = await self.database.execute(
            "SELECT id, name, description FROM roles WHERE tenant_id = :tenant_id",
            {"tenant_id": self.tenant_id},
        )
        return [Role(id=r.id, name=r.name, description=r.description) for r in rows]

    async def assign_role(self, user_id: str, role_name: str) -> None:
        """Assign a role to a user.

        Args:
            user_id: User ID
            role_name: Role name to assign
        """
        role = await self.get_role(role_name)

        # Check if already assigned
        existing = await self.database.execute(
            """
            SELECT id FROM user_roles
            WHERE tenant_id = :tenant_id AND user_id = :user_id AND role_id = :role_id
            """,
            {"tenant_id": self.tenant_id, "user_id": user_id, "role_id": role.id},
        )
        if existing:
            return  # Already assigned

        await self.database.execute(
            """
            INSERT INTO user_roles (id, tenant_id, user_id, role_id)
            VALUES (:id, :tenant_id, :user_id, :role_id)
            """,
            {
                "id": f"ur-{user_id}-{role_name}",
                "tenant_id": self.tenant_id,
                "user_id": user_id,
                "role_id": role.id,
            },
        )

    async def revoke_role(self, user_id: str, role_name: str) -> None:
        """Revoke a role from a user.

        Args:
            user_id: User ID
            role_name: Role name to revoke
        """
        role = await self.get_role(role_name)

        await self.database.execute(
            """
            DELETE FROM user_roles
            WHERE tenant_id = :tenant_id AND user_id = :user_id AND role_id = :role_id
            """,
            {"tenant_id": self.tenant_id, "user_id": user_id, "role_id": role.id},
        )

    async def get_user_roles(self, user_id: str) -> list[str]:
        """Get all roles for a user.

        Args:
            user_id: User ID

        Returns:
            List of role names
        """
        rows = await self.database.execute(
            """
            SELECT r.name FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.tenant_id = :tenant_id AND ur.user_id = :user_id
            """,
            {"tenant_id": self.tenant_id, "user_id": user_id},
        )
        return [r.name for r in rows]

    async def grant_skill_access(self, skill_slug: str, role_name: str) -> None:
        """Grant a role access to a skill.

        Args:
            skill_slug: Skill identifier
            role_name: Role name
        """
        role = await self.get_role(role_name)

        # Check if already granted
        existing = await self.database.execute(
            """
            SELECT id FROM skill_roles
            WHERE tenant_id = :tenant_id AND skill_slug = :skill_slug AND role_id = :role_id
            """,
            {"tenant_id": self.tenant_id, "skill_slug": skill_slug, "role_id": role.id},
        )
        if existing:
            return

        await self.database.execute(
            """
            INSERT INTO skill_roles (id, tenant_id, skill_slug, role_id)
            VALUES (:id, :tenant_id, :skill_slug, :role_id)
            """,
            {
                "id": f"sr-{skill_slug}-{role_name}",
                "tenant_id": self.tenant_id,
                "skill_slug": skill_slug,
                "role_id": role.id,
            },
        )

    async def revoke_skill_access(self, skill_slug: str, role_name: str) -> None:
        """Revoke a role's access to a skill.

        Args:
            skill_slug: Skill identifier
            role_name: Role name
        """
        role = await self.get_role(role_name)

        await self.database.execute(
            """
            DELETE FROM skill_roles
            WHERE tenant_id = :tenant_id AND skill_slug = :skill_slug AND role_id = :role_id
            """,
            {"tenant_id": self.tenant_id, "skill_slug": skill_slug, "role_id": role.id},
        )

    async def get_skill_roles(self, skill_slug: str) -> list[str]:
        """Get all roles that have access to a skill.

        Args:
            skill_slug: Skill identifier

        Returns:
            List of role names (empty list means all roles have access)
        """
        rows = await self.database.execute(
            """
            SELECT r.name FROM skill_roles sr
            JOIN roles r ON sr.role_id = r.id
            WHERE sr.tenant_id = :tenant_id AND sr.skill_slug = :skill_slug
            """,
            {"tenant_id": self.tenant_id, "skill_slug": skill_slug},
        )
        return [r.name for r in rows]

    async def can_access_skill(self, user_roles: list[str], skill_slug: str) -> bool:
        """Check if a user with given roles can access a skill.

        Deny-first logic:
        - If no roles are configured for the skill, everyone has access
        - If roles are configured, user must have at least one of them
        - Admin role always has access

        Args:
            user_roles: User's role names
            skill_slug: Skill identifier

        Returns:
            True if access is granted
        """
        # Admin always has access
        if "admin" in user_roles:
            return True

        # Get skill's allowed roles
        allowed_roles = await self.get_skill_roles(skill_slug)

        # No restrictions = everyone has access
        if not allowed_roles:
            return True

        # Check if user has any allowed role
        return bool(set(user_roles) & set(allowed_roles))

    async def require_role(self, user_roles: list[str], required_role: str) -> None:
        """Require a user to have a specific role.

        Args:
            user_roles: User's role names
            required_role: Required role name

        Raises:
            PermissionDeniedError: If user doesn't have the role
        """
        if required_role not in user_roles:
            raise PermissionDeniedError(f"Role '{required_role}' required")

    async def require_skill_access(
        self, user_roles: list[str], skill_slug: str
    ) -> None:
        """Require access to a skill.

        Args:
            user_roles: User's role names
            skill_slug: Skill identifier

        Raises:
            PermissionDeniedError: If user cannot access the skill
        """
        if not await self.can_access_skill(user_roles, skill_slug):
            raise PermissionDeniedError(f"Access denied to skill: {skill_slug}")
