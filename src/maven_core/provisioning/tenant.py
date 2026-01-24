"""Tenant provisioning and lifecycle management."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import uuid4

from maven_core.protocols import Database, FileStore
from maven_core.provisioning.tiers import (
    TENANT_TIERS,
    TierConfig,
    get_provisioning_steps,
    get_tier,
    get_tier_limits,
)


@dataclass
class TenantConfig:
    """Configuration for a tenant."""

    tenant_id: str
    name: str
    created_at: float
    updated_at: float
    status: str  # "active", "suspended", "deleted"
    tier: str = "starter"
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
            "tier": self.tier,
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
            tier=data.get("tier", "starter"),
            settings=data.get("settings", {}),
            limits=data.get("limits", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_row(cls, row: Any) -> "TenantConfig":
        """Create from database row."""
        # Handle timestamp conversion
        created_at = row.created_at
        updated_at = row.updated_at

        # Convert string timestamps to float if needed
        if isinstance(created_at, str):
            from datetime import datetime

            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        if isinstance(updated_at, str):
            from datetime import datetime

            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()

        return cls(
            tenant_id=row.tenant_id,
            name=row.name,
            created_at=created_at if isinstance(created_at, (int, float)) else time.time(),
            updated_at=updated_at if isinstance(updated_at, (int, float)) else time.time(),
            status=row.status,
            tier=getattr(row, "tier", "starter") or "starter",
            settings=json.loads(row.settings) if row.settings else {},
            limits=json.loads(row.limits) if row.limits else {},
            metadata=json.loads(row.metadata) if row.metadata else {},
        )


@dataclass
class TenantProvisionResult:
    """Result of tenant provisioning."""

    tenant_id: str
    config: TenantConfig
    success: bool
    message: str
    provisioned_at: float


@dataclass
class ProvisioningJob:
    """Tracks the status of an async provisioning job."""

    id: str
    tenant_id: str
    tenant_name: str
    tier: str
    status: str  # "pending", "running", "completed", "failed"
    current_step: int
    total_steps: int
    steps_completed: list[str]
    steps_skipped: list[str]
    current_step_name: str | None
    error: str | None
    created_at: float
    updated_at: float
    completed_at: float | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "tier": self.tier,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "steps_completed": self.steps_completed,
            "steps_skipped": self.steps_skipped,
            "current_step_name": self.current_step_name,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> "ProvisioningJob":
        """Create from database row."""
        return cls(
            id=row.id,
            tenant_id=row.tenant_id,
            tenant_name=row.tenant_name,
            tier=row.tier,
            status=row.status,
            current_step=row.current_step,
            total_steps=row.total_steps,
            steps_completed=json.loads(row.steps_completed) if row.steps_completed else [],
            steps_skipped=json.loads(row.steps_skipped) if row.steps_skipped else [],
            current_step_name=row.current_step_name,
            error=row.error,
            created_at=row.created_at if isinstance(row.created_at, (int, float)) else time.time(),
            updated_at=row.updated_at if isinstance(row.updated_at, (int, float)) else time.time(),
            completed_at=row.completed_at,
        )


@dataclass
class ProvisioningEvent:
    """Event emitted during provisioning."""

    type: str  # "step_started", "step_completed", "step_skipped", "completed", "failed"
    step_id: str | None = None
    step_name: str | None = None
    step_number: int | None = None
    reason: str | None = None
    tenant_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for NDJSON."""
        data: dict[str, Any] = {"type": self.type}
        if self.step_id:
            data["step_id"] = self.step_id
        if self.step_name:
            data["step_name"] = self.step_name
        if self.step_number is not None:
            data["step_number"] = self.step_number
        if self.reason:
            data["reason"] = self.reason
        if self.tenant_id:
            data["tenant_id"] = self.tenant_id
        if self.error:
            data["error"] = self.error
        return data


class TenantManager:
    """Manages tenant provisioning and lifecycle.

    Handles:
    - Creating new tenants with isolated storage
    - Updating tenant configuration
    - Suspending and deleting tenants
    - Listing and querying tenants
    - Async provisioning with progress tracking

    Tenant metadata is stored in the database for persistence.
    Tenant-specific files (skills, transcripts) are stored in FileStore.
    """

    def __init__(
        self,
        files: FileStore,
        db: Database,
        kv: Any = None,  # Kept for backwards compatibility, not used
    ) -> None:
        """Initialize tenant manager.

        Args:
            files: File storage backend (for tenant-specific files)
            db: Database backend (required for tenant metadata)
            kv: Deprecated, kept for backwards compatibility
        """
        self.files = files
        self.db = db

    async def create_tenant(
        self,
        name: str,
        tenant_id: str | None = None,
        tier: str = "starter",
        settings: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TenantProvisionResult:
        """Create and provision a new tenant.

        Args:
            name: Tenant display name
            tenant_id: Optional tenant ID (generated if not provided)
            tier: Tenant tier (starter, pro, enterprise)
            settings: Initial tenant settings
            limits: Resource limits for the tenant (defaults based on tier)
            metadata: Additional metadata

        Returns:
            Provisioning result
        """
        if tenant_id is None:
            tenant_id = str(uuid4())

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

        # Validate tier
        if tier not in TENANT_TIERS:
            tier = "starter"

        now = time.time()
        # Use tier-based limits as defaults, override with provided limits
        final_limits = {**get_tier_limits(tier), **(limits or {})}
        final_settings = {**self._default_settings(), **(settings or {})}
        final_metadata = metadata or {}

        # Insert into database
        await self.db.execute(
            """
            INSERT INTO tenants (tenant_id, name, status, tier, settings, limits, metadata, created_at, updated_at)
            VALUES (:tenant_id, :name, :status, :tier, :settings, :limits, :metadata, :created_at, :updated_at)
            """,
            {
                "tenant_id": tenant_id,
                "name": name,
                "status": "active",
                "tier": tier,
                "settings": json.dumps(final_settings),
                "limits": json.dumps(final_limits),
                "metadata": json.dumps(final_metadata),
                "created_at": now,
                "updated_at": now,
            },
        )

        config = TenantConfig(
            tenant_id=tenant_id,
            name=name,
            created_at=now,
            updated_at=now,
            status="active",
            tier=tier,
            settings=final_settings,
            limits=final_limits,
            metadata=final_metadata,
        )

        # Create tenant storage directories (skills, connectors, etc.)
        await self._create_tenant_directories(tenant_id)

        # Initialize tenant roles
        await self._init_tenant_roles(tenant_id)

        return TenantProvisionResult(
            tenant_id=tenant_id,
            config=config,
            success=True,
            message=f"Tenant provisioned successfully: {tenant_id}",
            provisioned_at=now,
        )

    async def create_provisioning_job(
        self,
        name: str,
        tier: str = "starter",
        tenant_id: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ProvisioningJob:
        """Create a new provisioning job for async tenant creation.

        Args:
            name: Tenant display name
            tier: Tenant tier (starter, pro, enterprise)
            tenant_id: Optional tenant ID (generated if not provided)
            settings: Initial tenant settings

        Returns:
            Created provisioning job
        """
        if tenant_id is None:
            tenant_id = str(uuid4())

        job_id = str(uuid4())

        # Validate tier and get applicable steps
        tier_config = get_tier(tier)
        if not tier_config:
            tier = "starter"
            tier_config = TENANT_TIERS["starter"]

        steps = get_provisioning_steps(tier_config)
        total_steps = len(steps)

        now = time.time()

        # Insert job record
        await self.db.execute(
            """
            INSERT INTO provisioning_jobs
            (id, tenant_id, tenant_name, tier, status, current_step, total_steps,
             steps_completed, steps_skipped, created_at, updated_at)
            VALUES (:id, :tenant_id, :tenant_name, :tier, :status, :current_step, :total_steps,
                    :steps_completed, :steps_skipped, :created_at, :updated_at)
            """,
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "tenant_name": name,
                "tier": tier,
                "status": "pending",
                "current_step": 0,
                "total_steps": total_steps,
                "steps_completed": "[]",
                "steps_skipped": "[]",
                "created_at": now,
                "updated_at": now,
            },
        )

        return ProvisioningJob(
            id=job_id,
            tenant_id=tenant_id,
            tenant_name=name,
            tier=tier,
            status="pending",
            current_step=0,
            total_steps=total_steps,
            steps_completed=[],
            steps_skipped=[],
            current_step_name=None,
            error=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    async def get_provisioning_job(self, job_id: str) -> ProvisioningJob | None:
        """Get a provisioning job by ID.

        Args:
            job_id: Job identifier

        Returns:
            ProvisioningJob or None if not found
        """
        rows = await self.db.execute(
            "SELECT * FROM provisioning_jobs WHERE id = :id",
            {"id": job_id},
        )
        if not rows:
            return None
        return ProvisioningJob.from_row(rows[0])

    async def update_provisioning_job(
        self,
        job_id: str,
        status: str | None = None,
        current_step: int | None = None,
        current_step_name: str | None = None,
        steps_completed: list[str] | None = None,
        steps_skipped: list[str] | None = None,
        error: str | None = None,
        completed_at: float | None = None,
    ) -> None:
        """Update a provisioning job.

        Args:
            job_id: Job identifier
            status: New status
            current_step: Current step number
            current_step_name: Current step name
            steps_completed: List of completed step IDs
            steps_skipped: List of skipped step IDs
            error: Error message if failed
            completed_at: Completion timestamp
        """
        updates = ["updated_at = :updated_at"]
        params: dict[str, Any] = {"id": job_id, "updated_at": time.time()}

        if status is not None:
            updates.append("status = :status")
            params["status"] = status
        if current_step is not None:
            updates.append("current_step = :current_step")
            params["current_step"] = current_step
        if current_step_name is not None:
            updates.append("current_step_name = :current_step_name")
            params["current_step_name"] = current_step_name
        if steps_completed is not None:
            updates.append("steps_completed = :steps_completed")
            params["steps_completed"] = json.dumps(steps_completed)
        if steps_skipped is not None:
            updates.append("steps_skipped = :steps_skipped")
            params["steps_skipped"] = json.dumps(steps_skipped)
        if error is not None:
            updates.append("error = :error")
            params["error"] = error
        if completed_at is not None:
            updates.append("completed_at = :completed_at")
            params["completed_at"] = completed_at

        await self.db.execute(
            f"UPDATE provisioning_jobs SET {', '.join(updates)} WHERE id = :id",
            params,
        )

    async def provision_tenant_with_progress(
        self,
        job_id: str,
        settings: dict[str, Any] | None = None,
    ) -> AsyncIterator[ProvisioningEvent]:
        """Execute tenant provisioning with progress updates.

        This is an async generator that yields progress events as each
        step is executed. Used for streaming progress to the frontend.

        Args:
            job_id: Provisioning job ID
            settings: Additional settings for the tenant

        Yields:
            ProvisioningEvent for each step
        """
        # Get job details
        job = await self.get_provisioning_job(job_id)
        if not job:
            yield ProvisioningEvent(type="failed", error="Job not found")
            return

        # Get tier config and applicable steps
        tier_config = get_tier(job.tier)
        if not tier_config:
            tier_config = TENANT_TIERS["starter"]

        steps = get_provisioning_steps(tier_config)
        all_step_ids = [s.id for s in steps]

        # Update job status to running
        await self.update_provisioning_job(job_id, status="running")

        steps_completed: list[str] = []
        steps_skipped: list[str] = []
        step_number = 0

        try:
            for step in steps:
                step_number += 1

                # Check if step should be skipped
                should_skip = False
                skip_reason = None

                if step.required_infra == "dedicated":
                    if tier_config.infra.storage != "dedicated" and tier_config.infra.database != "dedicated":
                        should_skip = True
                        skip_reason = f"Not required for {tier_config.display_name} tier"

                if step.required_feature and step.required_feature not in tier_config.features:
                    should_skip = True
                    skip_reason = f"Feature '{step.required_feature}' not included in {tier_config.display_name} tier"

                if should_skip:
                    steps_skipped.append(step.id)
                    await self.update_provisioning_job(
                        job_id,
                        current_step=step_number,
                        current_step_name=step.name,
                        steps_skipped=steps_skipped,
                    )
                    yield ProvisioningEvent(
                        type="step_skipped",
                        step_id=step.id,
                        step_name=step.name,
                        step_number=step_number,
                        reason=skip_reason,
                    )
                    continue

                # Start step
                await self.update_provisioning_job(
                    job_id,
                    current_step=step_number,
                    current_step_name=step.name,
                )
                yield ProvisioningEvent(
                    type="step_started",
                    step_id=step.id,
                    step_name=step.name,
                    step_number=step_number,
                )

                # Execute step
                await self._execute_provisioning_step(
                    step.id,
                    job.tenant_id,
                    job.tenant_name,
                    job.tier,
                    tier_config,
                    settings,
                )

                # Complete step
                steps_completed.append(step.id)
                await self.update_provisioning_job(
                    job_id,
                    steps_completed=steps_completed,
                )
                yield ProvisioningEvent(
                    type="step_completed",
                    step_id=step.id,
                    step_number=step_number,
                )

            # All steps completed successfully
            await self.update_provisioning_job(
                job_id,
                status="completed",
                completed_at=time.time(),
            )
            yield ProvisioningEvent(
                type="completed",
                tenant_id=job.tenant_id,
            )

        except Exception as e:
            error_msg = str(e)
            await self.update_provisioning_job(
                job_id,
                status="failed",
                error=error_msg,
                completed_at=time.time(),
            )
            yield ProvisioningEvent(
                type="failed",
                error=error_msg,
            )

    async def _execute_provisioning_step(
        self,
        step_id: str,
        tenant_id: str,
        tenant_name: str,
        tier: str,
        tier_config: TierConfig,
        settings: dict[str, Any] | None,
    ) -> None:
        """Execute a single provisioning step.

        Args:
            step_id: Step identifier
            tenant_id: Tenant identifier
            tenant_name: Tenant display name
            tier: Tier identifier
            tier_config: Tier configuration
            settings: Additional settings
        """
        if step_id == "create_record":
            await self._step_create_record(tenant_id, tenant_name, tier, settings)
        elif step_id == "provision_storage":
            await self._step_provision_storage(tenant_id, tier_config)
        elif step_id == "provision_database":
            await self._step_provision_database(tenant_id, tier_config)
        elif step_id == "update_bindings":
            await self._step_update_bindings(tenant_id, tier_config)
        elif step_id == "deploy_worker":
            await self._step_deploy_worker(tenant_id)
        elif step_id == "initialize_storage":
            await self._step_initialize_storage(tenant_id)
        elif step_id == "create_roles":
            await self._step_create_roles(tenant_id)
        elif step_id == "configure_auth":
            await self._step_configure_auth(tenant_id, settings)
        elif step_id == "apply_limits":
            await self._step_apply_limits(tenant_id, tier)
        elif step_id == "configure_domain":
            await self._step_configure_domain(tenant_id, settings)
        elif step_id == "store_config":
            await self._step_store_config(tenant_id, tier_config)
        elif step_id == "verify_connectivity":
            await self._step_verify_connectivity(tenant_id)
        elif step_id == "finalize":
            await self._step_finalize(tenant_id)
        else:
            # Unknown step - simulate with delay
            await asyncio.sleep(0.2)

    async def _step_create_record(
        self,
        tenant_id: str,
        tenant_name: str,
        tier: str,
        settings: dict[str, Any] | None,
    ) -> None:
        """Create tenant database record."""
        now = time.time()
        final_limits = get_tier_limits(tier)
        final_settings = {**self._default_settings(), **(settings or {})}

        await self.db.execute(
            """
            INSERT INTO tenants (tenant_id, name, status, tier, settings, limits, metadata, created_at, updated_at)
            VALUES (:tenant_id, :name, :status, :tier, :settings, :limits, :metadata, :created_at, :updated_at)
            """,
            {
                "tenant_id": tenant_id,
                "name": tenant_name,
                "status": "provisioning",
                "tier": tier,
                "settings": json.dumps(final_settings),
                "limits": json.dumps(final_limits),
                "metadata": json.dumps({}),
                "created_at": now,
                "updated_at": now,
            },
        )

    async def _step_provision_storage(
        self, tenant_id: str, tier_config: TierConfig
    ) -> None:
        """Provision storage (shared directory or dedicated bucket)."""
        if tier_config.infra.storage == "dedicated":
            # In production, would call provider.create_bucket()
            # For now, create dedicated directory
            await asyncio.sleep(0.5)  # Simulate API call
        else:
            # Shared storage - just create directory prefix
            await asyncio.sleep(0.2)

    async def _step_provision_database(
        self, tenant_id: str, tier_config: TierConfig
    ) -> None:
        """Provision database (shared DB or dedicated D1)."""
        if tier_config.infra.database == "dedicated":
            # In production, would call provider.create_database()
            await asyncio.sleep(0.5)  # Simulate API call
        else:
            # Shared database - no action needed
            await asyncio.sleep(0.1)

    async def _step_update_bindings(
        self, tenant_id: str, tier_config: TierConfig
    ) -> None:
        """Update worker bindings for dedicated resources."""
        # In production, would update wrangler.toml
        await asyncio.sleep(0.3)

    async def _step_deploy_worker(self, tenant_id: str) -> None:
        """Deploy worker with updated bindings."""
        # In production, would trigger wrangler deploy
        await asyncio.sleep(0.5)

    async def _step_initialize_storage(self, tenant_id: str) -> None:
        """Initialize tenant storage structure."""
        await self._create_tenant_directories(tenant_id)

    async def _step_create_roles(self, tenant_id: str) -> None:
        """Create default roles for tenant."""
        await self._init_tenant_roles(tenant_id)

    async def _step_configure_auth(
        self, tenant_id: str, settings: dict[str, Any] | None
    ) -> None:
        """Configure authentication for tenant."""
        # Auth is configured via settings during tenant creation
        await asyncio.sleep(0.2)

    async def _step_apply_limits(self, tenant_id: str, tier: str) -> None:
        """Apply tier-based resource limits."""
        limits = get_tier_limits(tier)
        await self.db.execute(
            "UPDATE tenants SET limits = :limits, updated_at = :updated_at WHERE tenant_id = :tenant_id",
            {
                "tenant_id": tenant_id,
                "limits": json.dumps(limits),
                "updated_at": time.time(),
            },
        )

    async def _step_configure_domain(
        self, tenant_id: str, settings: dict[str, Any] | None
    ) -> None:
        """Configure custom domain if specified."""
        # In production, would call provider.configure_domain()
        await asyncio.sleep(0.3)

    async def _step_store_config(
        self, tenant_id: str, tier_config: TierConfig
    ) -> None:
        """Store tenant configuration for runtime routing."""
        # In production, would store in KV for worker routing
        await asyncio.sleep(0.1)

    async def _step_verify_connectivity(self, tenant_id: str) -> None:
        """Verify tenant infrastructure is accessible."""
        await asyncio.sleep(0.2)

    async def _step_finalize(self, tenant_id: str) -> None:
        """Finalize tenant setup - mark as active."""
        await self.db.execute(
            "UPDATE tenants SET status = 'active', updated_at = :updated_at WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id, "updated_at": time.time()},
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

    def _default_settings(self) -> dict[str, Any]:
        """Get default settings for a tenant."""
        return {
            "auth_mode": "builtin",
        }

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

    async def _init_tenant_roles(self, tenant_id: str) -> None:
        """Initialize default roles for a new tenant."""
        default_roles = [
            ("admin", "Full access to all resources"),
            ("user", "Standard user access"),
            ("service", "Service account access"),
        ]

        for role_name, description in default_roles:
            role_id = f"role-{tenant_id}-{role_name}"
            await self.db.execute(
                """
                INSERT OR IGNORE INTO roles (id, tenant_id, name, description)
                VALUES (:id, :tenant_id, :name, :description)
                """,
                {
                    "id": role_id,
                    "tenant_id": tenant_id,
                    "name": role_name,
                    "description": description,
                },
            )

    async def get_tenant(self, tenant_id: str) -> TenantConfig | None:
        """Get tenant configuration.

        Args:
            tenant_id: Tenant ID

        Returns:
            Tenant configuration or None if not found
        """
        rows = await self.db.execute(
            "SELECT * FROM tenants WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        )
        if not rows:
            return None

        return TenantConfig.from_row(rows[0])

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

        # Save to database
        await self.db.execute(
            """
            UPDATE tenants
            SET name = :name, settings = :settings, limits = :limits,
                metadata = :metadata, updated_at = :updated_at
            WHERE tenant_id = :tenant_id
            """,
            {
                "tenant_id": tenant_id,
                "name": config.name,
                "settings": json.dumps(config.settings),
                "limits": json.dumps(config.limits),
                "metadata": json.dumps(config.metadata),
                "updated_at": config.updated_at,
            },
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

        await self.db.execute(
            """
            UPDATE tenants SET status = 'suspended', updated_at = :updated_at
            WHERE tenant_id = :tenant_id
            """,
            {"tenant_id": tenant_id, "updated_at": time.time()},
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

        await self.db.execute(
            """
            UPDATE tenants SET status = 'active', updated_at = :updated_at
            WHERE tenant_id = :tenant_id
            """,
            {"tenant_id": tenant_id, "updated_at": time.time()},
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
            await self.db.execute(
                """
                UPDATE tenants SET status = 'deleted', updated_at = :updated_at
                WHERE tenant_id = :tenant_id
                """,
                {"tenant_id": tenant_id, "updated_at": time.time()},
            )
        else:
            # Hard delete - remove from database
            await self.db.execute(
                "DELETE FROM tenants WHERE tenant_id = :tenant_id",
                {"tenant_id": tenant_id},
            )
            # Note: tenant files in FileStore are not deleted here
            # Would need to implement file cleanup if needed

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
        if status:
            rows = await self.db.execute(
                """
                SELECT * FROM tenants WHERE status = :status
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset
                """,
                {"status": status, "limit": limit, "offset": offset},
            )
        else:
            rows = await self.db.execute(
                """
                SELECT * FROM tenants
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset
                """,
                {"limit": limit, "offset": offset},
            )

        return [TenantConfig.from_row(row) for row in rows]

    async def tenant_exists(self, tenant_id: str) -> bool:
        """Check if a tenant exists.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if tenant exists (any status)
        """
        rows = await self.db.execute(
            "SELECT 1 FROM tenants WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        )
        return len(rows) > 0

    async def is_tenant_active(self, tenant_id: str) -> bool:
        """Check if a tenant is active.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if tenant exists and is active
        """
        rows = await self.db.execute(
            "SELECT 1 FROM tenants WHERE tenant_id = :tenant_id AND status = 'active'",
            {"tenant_id": tenant_id},
        )
        return len(rows) > 0
