"""Tests for skill loader."""

import pytest

from maven_core.backends.files.local import LocalFileStore
from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.exceptions import SkillNotFoundError
from maven_core.skills.loader import SkillLoader
from maven_core.skills.parser import Skill


@pytest.fixture
def file_store(tmp_path) -> LocalFileStore:
    """Create a local file store for testing."""
    return LocalFileStore(tmp_path)


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store for testing."""
    return MemoryKVStore()


@pytest.fixture
def loader(file_store, kv_store) -> SkillLoader:
    """Create a skill loader for testing."""
    return SkillLoader(file_store, kv_store, "test-tenant")


class TestSkillLoader:
    """Tests for SkillLoader."""

    @pytest.mark.asyncio
    async def test_save_and_get_skill(self, loader: SkillLoader) -> None:
        """Save a skill and retrieve it."""
        skill = Skill(
            slug="test-skill",
            name="Test Skill",
            description="A test skill",
            content="# Test\n\nContent here.",
            triggers=["test"],
            allowed_roles=["admin"],
        )

        await loader.save_skill(skill)
        retrieved = await loader.get_skill("test-skill")

        assert retrieved.slug == "test-skill"
        assert retrieved.name == "Test Skill"
        assert retrieved.description == "A test skill"
        assert "# Test" in retrieved.content

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self, loader: SkillLoader) -> None:
        """Getting non-existent skill raises error."""
        with pytest.raises(SkillNotFoundError):
            await loader.get_skill("nonexistent")

    @pytest.mark.asyncio
    async def test_list_skills_empty(self, loader: SkillLoader) -> None:
        """List skills when none exist."""
        skills = await loader.list_skills()
        assert skills == []

    @pytest.mark.asyncio
    async def test_list_skills(self, loader: SkillLoader) -> None:
        """List all skills."""
        skill1 = Skill(
            slug="skill-1",
            name="Skill One",
            description="First skill",
            content="Content 1",
        )
        skill2 = Skill(
            slug="skill-2",
            name="Skill Two",
            description="Second skill",
            content="Content 2",
            triggers=["trigger2"],
        )

        await loader.save_skill(skill1)
        await loader.save_skill(skill2)

        skills = await loader.list_skills()
        assert len(skills) == 2

        slugs = {s["slug"] for s in skills}
        assert slugs == {"skill-1", "skill-2"}

    @pytest.mark.asyncio
    async def test_list_skills_with_role_filter(self, loader: SkillLoader) -> None:
        """List skills filtered by role."""
        public_skill = Skill(
            slug="public",
            name="Public Skill",
            description="Available to all",
            content="Content",
            allowed_roles=[],  # Empty = available to all
        )
        admin_skill = Skill(
            slug="admin-only",
            name="Admin Only",
            description="Only for admins",
            content="Content",
            allowed_roles=["admin"],
        )
        dev_skill = Skill(
            slug="dev-only",
            name="Developer Only",
            description="Only for developers",
            content="Content",
            allowed_roles=["developer"],
        )

        await loader.save_skill(public_skill)
        await loader.save_skill(admin_skill)
        await loader.save_skill(dev_skill)

        # No filter - all skills
        all_skills = await loader.list_skills()
        assert len(all_skills) == 3

        # Admin sees all (admin override)
        admin_skills = await loader.list_skills(user_roles=["admin"])
        assert len(admin_skills) == 3

        # Developer sees public + dev-only
        dev_skills = await loader.list_skills(user_roles=["developer"])
        slugs = {s["slug"] for s in dev_skills}
        assert slugs == {"public", "dev-only"}

        # User with no special role sees only public
        user_skills = await loader.list_skills(user_roles=["user"])
        slugs = {s["slug"] for s in user_skills}
        assert slugs == {"public"}

    @pytest.mark.asyncio
    async def test_filter_for_user(self, loader: SkillLoader) -> None:
        """Get skill slugs accessible to a user."""
        skill1 = Skill(
            slug="all-access",
            name="All Access",
            description="",
            content="",
            allowed_roles=[],
        )
        skill2 = Skill(
            slug="restricted",
            name="Restricted",
            description="",
            content="",
            allowed_roles=["special"],
        )

        await loader.save_skill(skill1)
        await loader.save_skill(skill2)

        # Regular user
        slugs = await loader.filter_for_user(["user"])
        assert slugs == ["all-access"]

        # Special user
        slugs = await loader.filter_for_user(["special"])
        assert set(slugs) == {"all-access", "restricted"}

    @pytest.mark.asyncio
    async def test_delete_skill(self, loader: SkillLoader) -> None:
        """Delete a skill."""
        skill = Skill(
            slug="to-delete",
            name="To Delete",
            description="",
            content="",
        )

        await loader.save_skill(skill)

        # Verify it exists
        retrieved = await loader.get_skill("to-delete")
        assert retrieved.slug == "to-delete"

        # Delete it
        await loader.delete_skill("to-delete")

        # Verify it's gone
        with pytest.raises(SkillNotFoundError):
            await loader.get_skill("to-delete")

    @pytest.mark.asyncio
    async def test_rebuild_index(self, loader: SkillLoader) -> None:
        """Rebuild the skill index."""
        skill = Skill(
            slug="indexed",
            name="Indexed Skill",
            description="For index test",
            content="Content",
            triggers=["index-test"],
        )

        await loader.save_skill(skill)

        # Force rebuild
        index = await loader.rebuild_index()

        assert "indexed" in index.skills
        assert index.skills["indexed"]["name"] == "Indexed Skill"
        assert index.skills["indexed"]["triggers"] == ["index-test"]

    @pytest.mark.asyncio
    async def test_index_caching(self, loader: SkillLoader) -> None:
        """Index is cached and reused."""
        skill = Skill(
            slug="cached",
            name="Cached",
            description="",
            content="",
        )

        await loader.save_skill(skill)

        # First call builds index
        await loader.list_skills()

        # Check local cache is populated
        assert loader._local_cache is not None
        first_built_at = loader._local_cache.built_at

        # Second call uses cache
        await loader.list_skills()
        assert loader._local_cache.built_at == first_built_at
