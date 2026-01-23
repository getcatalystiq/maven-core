"""Skill loading with caching and role filtering."""

import json
import time
from dataclasses import dataclass
from pathlib import Path

from maven_core.exceptions import SkillNotFoundError
from maven_core.protocols import FileStore, KVStore
from maven_core.skills.parser import Skill, parse_skill


@dataclass
class SkillIndex:
    """Cached skill metadata for fast filtering."""

    skills: dict[str, dict]  # slug -> metadata
    built_at: float


class SkillLoader:
    """Loads and caches skills with role-based filtering.

    Skills are stored in FileStore and indexed in KV for fast lookup.
    """

    def __init__(
        self,
        files: FileStore,
        kv: KVStore,
        tenant_id: str,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """Initialize skill loader.

        Args:
            files: File storage backend (skills stored here)
            kv: KV storage backend (index cached here)
            tenant_id: Current tenant ID
            cache_ttl_seconds: How long to cache the skill index
        """
        self.files = files
        self.kv = kv
        self.tenant_id = tenant_id
        self.cache_ttl = cache_ttl_seconds
        self._local_cache: SkillIndex | None = None

    def _skills_prefix(self) -> str:
        """Get the storage prefix for skills."""
        return f"skills/{self.tenant_id}/"

    def _index_key(self) -> str:
        """Get the KV key for the skill index."""
        return f"skill_index:{self.tenant_id}"

    async def _get_index(self) -> SkillIndex:
        """Get the skill index, using cache if available."""
        now = time.time()

        # Check local cache
        if self._local_cache and (now - self._local_cache.built_at) < self.cache_ttl:
            return self._local_cache

        # Check KV cache
        cached = await self.kv.get(self._index_key())
        if cached:
            try:
                data = json.loads(cached.decode())
                if (now - data.get("built_at", 0)) < self.cache_ttl:
                    self._local_cache = SkillIndex(
                        skills=data.get("skills", {}),
                        built_at=data.get("built_at", now),
                    )
                    return self._local_cache
            except (json.JSONDecodeError, KeyError):
                pass

        # Rebuild index
        return await self.rebuild_index()

    async def rebuild_index(self) -> SkillIndex:
        """Rebuild the skill index from storage."""
        skills: dict[str, dict] = {}
        prefix = self._skills_prefix()

        async for meta in self.files.list(prefix):
            if not meta.key.endswith(".md"):
                continue

            # Extract slug from key
            slug = meta.key[len(prefix):-3]  # Remove prefix and .md
            if "/" in slug:
                continue  # Skip nested files

            # Load skill to get metadata
            result = await self.files.get(meta.key)
            if result:
                content, _ = result
                skill = parse_skill(slug, content.decode())
                skills[slug] = {
                    "name": skill.name,
                    "description": skill.description,
                    "triggers": skill.triggers,
                    "allowed_roles": skill.allowed_roles,
                }

        now = time.time()
        index = SkillIndex(skills=skills, built_at=now)

        # Cache in KV
        cache_data = json.dumps({
            "skills": skills,
            "built_at": now,
        }).encode()
        await self.kv.set(self._index_key(), cache_data, ttl=self.cache_ttl)

        self._local_cache = index
        return index

    async def list_skills(self, user_roles: list[str] | None = None) -> list[dict]:
        """List all skills, optionally filtered by user roles.

        Args:
            user_roles: User's roles for filtering (None = no filtering)

        Returns:
            List of skill metadata dicts
        """
        index = await self._get_index()
        result = []

        for slug, meta in index.skills.items():
            # Check role access
            allowed_roles = meta.get("allowed_roles", [])
            if user_roles is not None and allowed_roles:
                # Admin always has access
                if "admin" not in user_roles:
                    if not set(user_roles) & set(allowed_roles):
                        continue

            result.append({
                "slug": slug,
                "name": meta.get("name", slug),
                "description": meta.get("description", ""),
                "triggers": meta.get("triggers", []),
            })

        return result

    async def get_skill(self, slug: str) -> Skill:
        """Get a skill by slug.

        Args:
            slug: Skill identifier

        Returns:
            Parsed Skill object

        Raises:
            SkillNotFoundError: If skill doesn't exist
        """
        key = f"{self._skills_prefix()}{slug}.md"
        result = await self.files.get(key)

        if not result:
            raise SkillNotFoundError(f"Skill not found: {slug}")

        content, _ = result
        return parse_skill(slug, content.decode())

    async def save_skill(self, skill: Skill) -> None:
        """Save a skill.

        Args:
            skill: Skill to save
        """
        from maven_core.skills.parser import skill_to_markdown

        key = f"{self._skills_prefix()}{skill.slug}.md"
        content = skill_to_markdown(skill)
        await self.files.put(key, content.encode(), content_type="text/markdown")

        # Invalidate cache
        self._local_cache = None
        await self.kv.delete(self._index_key())

    async def delete_skill(self, slug: str) -> None:
        """Delete a skill.

        Args:
            slug: Skill identifier
        """
        key = f"{self._skills_prefix()}{slug}.md"
        await self.files.delete(key)

        # Invalidate cache
        self._local_cache = None
        await self.kv.delete(self._index_key())

    async def filter_for_user(self, user_roles: list[str]) -> list[str]:
        """Get skill slugs accessible to a user.

        Args:
            user_roles: User's roles

        Returns:
            List of accessible skill slugs
        """
        skills = await self.list_skills(user_roles)
        return [s["slug"] for s in skills]
