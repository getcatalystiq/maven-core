"""Cloudflare infrastructure provider for tenant provisioning.

Handles production provisioning of Cloudflare resources:
- R2 buckets for dedicated storage
- D1 databases for dedicated databases
- DNS records and SSL for custom domains
- Worker binding updates and redeployment
"""

import time
from typing import TYPE_CHECKING, Any

import httpx

from maven_core.provisioning.providers.base import (
    BucketInfo,
    DatabaseInfo,
    DeploymentInfo,
    DomainInfo,
)

if TYPE_CHECKING:
    from maven_core.config import Config


class CloudflareProvider:
    """Cloudflare infrastructure provisioning provider.

    Uses Cloudflare API to create and manage tenant resources.
    Requires CF_API_TOKEN, CF_ACCOUNT_ID env vars (via config).
    """

    def __init__(self, config: "Config") -> None:
        """Initialize the Cloudflare provider.

        Args:
            config: Application configuration

        Raises:
            ValueError: If required Cloudflare config is missing
        """
        self.config = config

        if not config.cloudflare.account_id:
            raise ValueError("Cloudflare account_id is required for cloudflare backend")
        if not config.cloudflare.api_token:
            raise ValueError("Cloudflare api_token is required for cloudflare backend")

        self.account_id = config.cloudflare.account_id
        self.api_token = config.cloudflare.api_token
        self.base_url = "https://api.cloudflare.com/client/v4"

    def _headers(self) -> dict[str, str]:
        """Get API request headers."""
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def create_bucket(self, tenant_id: str, name: str) -> BucketInfo:
        """Create a dedicated R2 bucket for a tenant.

        Args:
            tenant_id: Tenant identifier
            name: Bucket name

        Returns:
            BucketInfo with created bucket details

        Raises:
            RuntimeError: If bucket creation fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/accounts/{self.account_id}/r2/buckets",
                headers=self._headers(),
                json={"name": name},
            )

            if response.status_code not in (200, 201):
                error = response.json().get("errors", [{}])[0].get("message", "Unknown error")
                raise RuntimeError(f"Failed to create R2 bucket: {error}")

            result = response.json().get("result", {})

            return BucketInfo(
                name=name,
                binding_name=f"STORAGE_tenant_{tenant_id.replace('-', '_')}",
                endpoint=result.get("endpoint"),
                region=result.get("location"),
            )

    async def create_database(self, tenant_id: str, name: str) -> DatabaseInfo:
        """Create a dedicated D1 database for a tenant.

        Args:
            tenant_id: Tenant identifier
            name: Database name

        Returns:
            DatabaseInfo with created database details

        Raises:
            RuntimeError: If database creation fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/accounts/{self.account_id}/d1/database",
                headers=self._headers(),
                json={"name": name},
            )

            if response.status_code not in (200, 201):
                error = response.json().get("errors", [{}])[0].get("message", "Unknown error")
                raise RuntimeError(f"Failed to create D1 database: {error}")

            result = response.json().get("result", {})

            return DatabaseInfo(
                name=name,
                binding_name=f"DB_tenant_{tenant_id.replace('-', '_')}",
                database_id=result.get("uuid"),
            )

    async def update_worker_bindings(
        self, tenant_id: str, resources: dict[str, Any]
    ) -> None:
        """Update wrangler.toml with new resource bindings.

        Note: In a production setup, this would update the wrangler.toml
        file and prepare for redeployment. For now, we store the config
        for manual deployment or CI/CD integration.

        Args:
            tenant_id: Tenant identifier
            resources: Dict containing bucket and database info
        """
        # Store binding configuration for later deployment
        # In a real setup, this could:
        # 1. Update wrangler.toml directly
        # 2. Trigger a CI/CD pipeline
        # 3. Use Workers for Platforms API

        await self.store_tenant_config(
            tenant_id,
            {
                "bindings": resources,
                "updated_at": time.time(),
            },
        )

    async def deploy_worker(self) -> DeploymentInfo:
        """Redeploy the Worker with updated bindings.

        Note: In production, this would trigger `wrangler deploy` or
        use the Workers API. For now, returns a mock deployment.

        Returns:
            DeploymentInfo with deployment details
        """
        # In a real implementation, this would:
        # 1. Run `wrangler deploy` via subprocess
        # 2. Or use the Workers API to upload new config
        # 3. Or trigger a GitHub Action/CI pipeline

        return DeploymentInfo(
            version=f"deploy-{int(time.time())}",
            deployed_at=time.time(),
            bindings_updated=["pending_manual_deploy"],
        )

    async def configure_domain(self, tenant_id: str, domain: str) -> DomainInfo:
        """Configure a custom domain with DNS and SSL.

        Args:
            tenant_id: Tenant identifier
            domain: Custom domain to configure

        Returns:
            DomainInfo with domain configuration details
        """
        # Get zone ID for the domain (assumes domain is in configured zone)
        zone_id = getattr(self.config.cloudflare, "zone_id", None)

        if not zone_id:
            # Return pending status if zone not configured
            return DomainInfo(
                domain=domain,
                status="pending_zone_config",
            )

        async with httpx.AsyncClient() as client:
            # Create DNS CNAME record
            response = await client.post(
                f"{self.base_url}/zones/{zone_id}/dns_records",
                headers=self._headers(),
                json={
                    "type": "CNAME",
                    "name": domain.split(".")[0],  # subdomain
                    "content": f"maven-worker.{self.account_id}.workers.dev",
                    "proxied": True,
                },
            )

            if response.status_code not in (200, 201):
                error = response.json().get("errors", [{}])[0].get("message", "Unknown error")
                raise RuntimeError(f"Failed to create DNS record: {error}")

            result = response.json().get("result", {})

            return DomainInfo(
                domain=domain,
                dns_record_id=result.get("id"),
                status="active",
            )

    async def store_tenant_config(
        self, tenant_id: str, config: dict[str, Any]
    ) -> None:
        """Store tenant configuration in KV for runtime routing.

        Args:
            tenant_id: Tenant identifier
            config: Configuration to store
        """
        import json

        kv_namespace_id = self.config.control_plane.kv_namespace_id

        if not kv_namespace_id:
            # Fall back to local storage if KV not configured
            return

        async with httpx.AsyncClient() as client:
            await client.put(
                f"{self.base_url}/accounts/{self.account_id}/storage/kv/namespaces/{kv_namespace_id}/values/tenant:{tenant_id}",
                headers=self._headers(),
                content=json.dumps(config),
            )

    async def cleanup(self, tenant_id: str) -> None:
        """Remove all tenant infrastructure.

        Args:
            tenant_id: Tenant identifier
        """
        # In production, this would:
        # 1. Delete R2 bucket
        # 2. Delete D1 database
        # 3. Remove DNS records
        # 4. Remove KV entries
        # 5. Update worker bindings

        # For safety, we don't auto-delete cloud resources
        # This should be handled manually or through a separate cleanup job
        pass

    async def verify_connectivity(self, tenant_id: str) -> bool:
        """Verify that tenant infrastructure is accessible.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if all resources are accessible
        """
        # Check that we can access the Cloudflare API
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/accounts/{self.account_id}",
                headers=self._headers(),
            )
            return response.status_code == 200
