"""Authentication manager supporting multiple auth modes."""

from dataclasses import dataclass
from typing import Any

from maven_core.auth.jwt_utils import (
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from maven_core.auth.oidc import OIDCTokenPayload, OIDCValidator
from maven_core.auth.password import hash_password, needs_rehash, verify_password
from maven_core.config import AuthConfig
from maven_core.exceptions import (
    AuthError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
)
from maven_core.protocols import Database


@dataclass
class User:
    """Authenticated user."""

    id: str
    tenant_id: str
    email: str | None
    roles: list[str]
    auth_method: str  # "password" or "oidc"


@dataclass
class AuthTokens:
    """Authentication tokens."""

    access_token: str
    refresh_token: str | None
    expires_in: int


class AuthManager:
    """Manages authentication for maven-core.

    Supports two authentication modes:
    - builtin: Password-based authentication with JWT tokens
    - oidc: External OIDC identity provider (Clerk, Auth0, etc.)
    """

    def __init__(
        self,
        config: AuthConfig,
        database: Database,
        tenant_id: str,
    ) -> None:
        """Initialize authentication manager.

        Args:
            config: Authentication configuration
            database: Database backend for user storage
            tenant_id: Current tenant ID
        """
        self.config = config
        self.database = database
        self.tenant_id = tenant_id
        self._oidc_validator: OIDCValidator | None = None

        # Initialize OIDC validator if configured
        if config.mode == "oidc" and config.oidc:
            self._oidc_validator = OIDCValidator(
                issuer=config.oidc.issuer,
                audience=config.oidc.audience,
                jwks_uri=config.oidc.jwks_uri,
            )

    async def register(
        self,
        email: str,
        password: str,
        roles: list[str] | None = None,
    ) -> User:
        """Register a new user with password authentication.

        Args:
            email: User's email address
            password: User's password
            roles: Optional roles to assign (defaults to default_role)

        Returns:
            The created user

        Raises:
            AuthError: If registration fails
        """
        if self.config.mode != "builtin":
            raise AuthError("Password registration not available in OIDC mode")

        from maven_core.utils.validation import validate_email, validate_password

        email = validate_email(email)
        validate_password(
            password,
            min_length=self.config.builtin.password.min_length if self.config.builtin else 12,
            require_special=self.config.builtin.password.require_special if self.config.builtin else True,
        )

        password_hash = hash_password(password)
        user_id = f"user-{email.split('@')[0]}-{hash(email) % 10000:04d}"

        # Check if user exists
        existing = await self.database.execute(
            "SELECT id FROM users WHERE tenant_id = :tenant_id AND email = :email",
            {"tenant_id": self.tenant_id, "email": email},
        )
        if existing:
            raise AuthError("User already exists")

        # Create user
        await self.database.execute(
            """
            INSERT INTO users (id, tenant_id, email, password_hash, email_verified)
            VALUES (:id, :tenant_id, :email, :password_hash, :email_verified)
            """,
            {
                "id": user_id,
                "tenant_id": self.tenant_id,
                "email": email,
                "password_hash": password_hash,
                "email_verified": False,
            },
        )

        # Assign roles
        user_roles = roles or ["user"]
        for role in user_roles:
            role_rows = await self.database.execute(
                "SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = :name",
                {"tenant_id": self.tenant_id, "name": role},
            )
            if role_rows:
                await self.database.execute(
                    """
                    INSERT INTO user_roles (id, tenant_id, user_id, role_id)
                    VALUES (:id, :tenant_id, :user_id, :role_id)
                    """,
                    {
                        "id": f"ur-{user_id}-{role}",
                        "tenant_id": self.tenant_id,
                        "user_id": user_id,
                        "role_id": role_rows[0].id,
                    },
                )

        return User(
            id=user_id,
            tenant_id=self.tenant_id,
            email=email,
            roles=user_roles,
            auth_method="password",
        )

    async def login(self, email: str, password: str) -> AuthTokens:
        """Login with email and password.

        Args:
            email: User's email
            password: User's password

        Returns:
            Authentication tokens

        Raises:
            InvalidCredentialsError: If credentials are invalid
        """
        if self.config.mode != "builtin":
            raise AuthError("Password login not available in OIDC mode")

        if not self.config.builtin or not self.config.builtin.jwt:
            raise AuthError("JWT configuration required for password auth")

        from maven_core.utils.validation import validate_email

        email = validate_email(email)

        # Get user
        rows = await self.database.execute(
            """
            SELECT id, password_hash FROM users
            WHERE tenant_id = :tenant_id AND email = :email
            """,
            {"tenant_id": self.tenant_id, "email": email},
        )
        if not rows:
            raise InvalidCredentialsError("Invalid email or password")

        user = rows[0]

        # Verify password
        verify_password(password, user.password_hash)

        # Check if rehash needed
        if needs_rehash(user.password_hash):
            new_hash = hash_password(password)
            await self.database.execute(
                """
                UPDATE users SET password_hash = :hash, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id AND tenant_id = :tenant_id
                """,
                {"hash": new_hash, "id": user.id, "tenant_id": self.tenant_id},
            )

        # Get user roles
        role_rows = await self.database.execute(
            """
            SELECT r.name FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.tenant_id = :tenant_id AND ur.user_id = :user_id
            """,
            {"tenant_id": self.tenant_id, "user_id": user.id},
        )
        roles = [r.name for r in role_rows]

        # Create tokens
        jwt_config = self.config.builtin.jwt
        access_token = create_access_token(
            user_id=user.id,
            tenant_id=self.tenant_id,
            secret=jwt_config.secret,
            expiry_minutes=jwt_config.expiry_minutes,
            email=email,
            roles=roles,
        )
        refresh_token = create_refresh_token(
            user_id=user.id,
            tenant_id=self.tenant_id,
            secret=jwt_config.secret,
            expiry_days=jwt_config.refresh_expiry_days,
        )

        return AuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=jwt_config.expiry_minutes * 60,
        )

    async def refresh(self, refresh_token: str) -> AuthTokens:
        """Refresh an access token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New authentication tokens

        Raises:
            TokenExpiredError: If refresh token has expired
            TokenInvalidError: If refresh token is invalid
        """
        if self.config.mode != "builtin":
            raise AuthError("Token refresh not available in OIDC mode")

        if not self.config.builtin or not self.config.builtin.jwt:
            raise AuthError("JWT configuration required")

        jwt_config = self.config.builtin.jwt
        payload = decode_token(refresh_token, jwt_config.secret)

        if payload.token_type != "refresh":
            raise TokenInvalidError("Not a refresh token")

        if payload.tenant_id != self.tenant_id:
            raise TokenInvalidError("Invalid tenant")

        # Get current roles
        role_rows = await self.database.execute(
            """
            SELECT r.name FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.tenant_id = :tenant_id AND ur.user_id = :user_id
            """,
            {"tenant_id": self.tenant_id, "user_id": payload.user_id},
        )
        roles = [r.name for r in role_rows]

        # Create new access token
        access_token = create_access_token(
            user_id=payload.user_id,
            tenant_id=self.tenant_id,
            secret=jwt_config.secret,
            expiry_minutes=jwt_config.expiry_minutes,
            email=payload.email,
            roles=roles,
        )

        return AuthTokens(
            access_token=access_token,
            refresh_token=None,  # Don't issue new refresh token
            expires_in=jwt_config.expiry_minutes * 60,
        )

    async def validate_token(self, token: str) -> User:
        """Validate an access token and return the user.

        Args:
            token: Access token (JWT for builtin, OIDC token for oidc mode)

        Returns:
            Authenticated user

        Raises:
            TokenExpiredError: If token has expired
            TokenInvalidError: If token is invalid
        """
        if self.config.mode == "oidc":
            return await self._validate_oidc_token(token)
        else:
            return await self._validate_builtin_token(token)

    async def _validate_builtin_token(self, token: str) -> User:
        """Validate a built-in JWT token."""
        if not self.config.builtin or not self.config.builtin.jwt:
            raise AuthError("JWT configuration required")

        payload = decode_token(token, self.config.builtin.jwt.secret)

        if payload.token_type != "access":
            raise TokenInvalidError("Not an access token")

        if payload.tenant_id != self.tenant_id:
            raise TokenInvalidError("Invalid tenant")

        return User(
            id=payload.user_id,
            tenant_id=payload.tenant_id,
            email=payload.email,
            roles=payload.roles,
            auth_method="password",
        )

    async def _validate_oidc_token(self, token: str) -> User:
        """Validate an OIDC token."""
        if not self._oidc_validator:
            raise AuthError("OIDC not configured")

        payload = await self._oidc_validator.validate_token(token)

        # Get or create user from OIDC claims
        user_id = f"oidc-{payload.user_id}"

        # Check if user exists, create if not
        rows = await self.database.execute(
            "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :id",
            {"tenant_id": self.tenant_id, "id": user_id},
        )
        if not rows:
            # Create user from OIDC claims
            await self.database.execute(
                """
                INSERT INTO users (id, tenant_id, email, email_verified)
                VALUES (:id, :tenant_id, :email, :email_verified)
                """,
                {
                    "id": user_id,
                    "tenant_id": self.tenant_id,
                    "email": payload.email,
                    "email_verified": payload.email_verified,
                },
            )
            # Assign default role
            role_rows = await self.database.execute(
                "SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = 'user'",
                {"tenant_id": self.tenant_id},
            )
            if role_rows:
                await self.database.execute(
                    """
                    INSERT INTO user_roles (id, tenant_id, user_id, role_id)
                    VALUES (:id, :tenant_id, :user_id, :role_id)
                    """,
                    {
                        "id": f"ur-{user_id}-user",
                        "tenant_id": self.tenant_id,
                        "user_id": user_id,
                        "role_id": role_rows[0].id,
                    },
                )

        # Get user roles
        role_rows = await self.database.execute(
            """
            SELECT r.name FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.tenant_id = :tenant_id AND ur.user_id = :user_id
            """,
            {"tenant_id": self.tenant_id, "user_id": user_id},
        )
        roles = [r.name for r in role_rows]

        return User(
            id=user_id,
            tenant_id=self.tenant_id,
            email=payload.email,
            roles=roles or ["user"],
            auth_method="oidc",
        )
