"""Tenant tier definitions and provisioning step configuration.

Defines the available tenant tiers (Starter, Pro, Enterprise) with their
resource limits, features, and infrastructure requirements.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TierLimits:
    """Resource limits for a tier."""

    max_users: int
    storage_mb: int
    max_sessions: int


@dataclass
class TierInfra:
    """Infrastructure configuration for a tier."""

    storage: str  # "shared" or "dedicated"
    database: str  # "shared" or "dedicated"
    custom_domain: bool = False


@dataclass
class TierConfig:
    """Complete configuration for a tenant tier."""

    id: str
    display_name: str
    limits: TierLimits
    features: list[str]
    infra: TierInfra

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "limits": {
                "max_users": self.limits.max_users,
                "storage_mb": self.limits.storage_mb,
                "max_sessions": self.limits.max_sessions,
            },
            "features": self.features,
            "infra": {
                "storage": self.infra.storage,
                "database": self.infra.database,
                "custom_domain": self.infra.custom_domain,
            },
        }


# Tier definitions
TENANT_TIERS: dict[str, TierConfig] = {
    "starter": TierConfig(
        id="starter",
        display_name="Starter",
        limits=TierLimits(
            max_users=10,
            storage_mb=1024,
            max_sessions=100,
        ),
        features=["basic_analytics"],
        infra=TierInfra(
            storage="shared",
            database="shared",
        ),
    ),
    "pro": TierConfig(
        id="pro",
        display_name="Pro",
        limits=TierLimits(
            max_users=100,
            storage_mb=10240,
            max_sessions=1000,
        ),
        features=["basic_analytics", "advanced_analytics", "api_access"],
        infra=TierInfra(
            storage="dedicated",
            database="dedicated",
        ),
    ),
    "enterprise": TierConfig(
        id="enterprise",
        display_name="Enterprise",
        limits=TierLimits(
            max_users=-1,  # Unlimited
            storage_mb=102400,
            max_sessions=-1,  # Unlimited
        ),
        features=[
            "basic_analytics",
            "advanced_analytics",
            "api_access",
            "sso",
            "custom_domain",
            "sla",
        ],
        infra=TierInfra(
            storage="dedicated",
            database="dedicated",
            custom_domain=True,
        ),
    ),
}


@dataclass
class ProvisioningStep:
    """Definition of a provisioning step."""

    id: str
    name: str
    description: str
    required_infra: str | None = None  # "dedicated" to only run for dedicated mode
    required_feature: str | None = None  # Feature flag to check


# All possible provisioning steps
PROVISIONING_STEPS: list[ProvisioningStep] = [
    ProvisioningStep(
        id="create_record",
        name="Create Tenant Record",
        description="Creating tenant database record",
    ),
    ProvisioningStep(
        id="provision_storage",
        name="Provision Storage",
        description="Setting up tenant storage",
    ),
    ProvisioningStep(
        id="provision_database",
        name="Provision Database",
        description="Setting up tenant database",
        required_infra="dedicated",
    ),
    ProvisioningStep(
        id="update_bindings",
        name="Update Worker Bindings",
        description="Configuring worker bindings",
        required_infra="dedicated",
    ),
    ProvisioningStep(
        id="deploy_worker",
        name="Deploy Worker",
        description="Deploying updated worker",
        required_infra="dedicated",
    ),
    ProvisioningStep(
        id="initialize_storage",
        name="Initialize Storage",
        description="Creating storage structure",
    ),
    ProvisioningStep(
        id="create_roles",
        name="Create Default Roles",
        description="Setting up default roles",
    ),
    ProvisioningStep(
        id="configure_auth",
        name="Configure Authentication",
        description="Setting up authentication",
    ),
    ProvisioningStep(
        id="apply_limits",
        name="Apply Tier Limits",
        description="Configuring resource limits",
    ),
    ProvisioningStep(
        id="configure_domain",
        name="Configure Custom Domain",
        description="Setting up custom domain",
        required_feature="custom_domain",
    ),
    ProvisioningStep(
        id="store_config",
        name="Store Configuration",
        description="Saving tenant configuration",
    ),
    ProvisioningStep(
        id="verify_connectivity",
        name="Verify Connectivity",
        description="Testing tenant access",
    ),
    ProvisioningStep(
        id="finalize",
        name="Finalize Setup",
        description="Completing tenant setup",
    ),
]


def get_tier(tier_id: str) -> TierConfig | None:
    """Get tier configuration by ID.

    Args:
        tier_id: Tier identifier (starter, pro, enterprise)

    Returns:
        TierConfig or None if not found
    """
    return TENANT_TIERS.get(tier_id)


def list_tiers() -> list[TierConfig]:
    """Get all available tiers.

    Returns:
        List of all tier configurations
    """
    return list(TENANT_TIERS.values())


def get_provisioning_steps(tier: TierConfig) -> list[ProvisioningStep]:
    """Get the provisioning steps applicable to a tier.

    Filters steps based on tier's infrastructure mode and features.

    Args:
        tier: Tier configuration

    Returns:
        List of applicable provisioning steps
    """
    applicable_steps = []

    for step in PROVISIONING_STEPS:
        # Check infrastructure requirement
        if step.required_infra == "dedicated":
            # Step requires dedicated infra - check if tier has it
            if tier.infra.storage != "dedicated" and tier.infra.database != "dedicated":
                continue

        # Check feature requirement
        if step.required_feature:
            if step.required_feature not in tier.features:
                continue

        applicable_steps.append(step)

    return applicable_steps


def get_tier_limits(tier_id: str) -> dict[str, Any]:
    """Get the resource limits for a tier.

    Used when creating a tenant to set appropriate limits.

    Args:
        tier_id: Tier identifier

    Returns:
        Dict of limits suitable for tenant creation
    """
    tier = get_tier(tier_id)
    if not tier:
        tier = TENANT_TIERS["starter"]  # Default to starter

    return {
        "max_users": tier.limits.max_users,
        "storage_mb": tier.limits.storage_mb,
        "max_sessions": tier.limits.max_sessions,
        # Include standard limits from existing system
        "max_skills": 100,
        "max_connectors": 50,
        "sandbox_timeout_seconds": 30,
        "sandbox_memory_mb": 256,
    }
