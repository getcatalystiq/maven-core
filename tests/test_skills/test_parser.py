"""Tests for skill parser."""

import pytest

from maven_core.skills.parser import Skill, parse_skill, skill_to_markdown


class TestParseSkill:
    """Tests for parse_skill function."""

    def test_parse_skill_with_frontmatter(self) -> None:
        """Parse skill with YAML frontmatter."""
        content = """---
name: Test Skill
description: A test skill
triggers:
  - test
  - example
allowed_roles:
  - admin
  - developer
custom_field: custom_value
---

# Test Skill

This is the skill content.

## Usage

Use it like this.
"""
        skill = parse_skill("test-skill", content)

        assert skill.slug == "test-skill"
        assert skill.name == "Test Skill"
        assert skill.description == "A test skill"
        assert skill.triggers == ["test", "example"]
        assert skill.allowed_roles == ["admin", "developer"]
        assert skill.metadata == {"custom_field": "custom_value"}
        assert "# Test Skill" in skill.content
        assert "## Usage" in skill.content

    def test_parse_skill_minimal_frontmatter(self) -> None:
        """Parse skill with minimal frontmatter."""
        content = """---
name: Simple Skill
---

Content here.
"""
        skill = parse_skill("simple", content)

        assert skill.slug == "simple"
        assert skill.name == "Simple Skill"
        assert skill.description == ""
        assert skill.triggers == []
        assert skill.allowed_roles == []
        assert skill.content.strip() == "Content here."

    def test_parse_skill_no_frontmatter(self) -> None:
        """Parse skill without frontmatter."""
        content = """# Just Content

No YAML frontmatter here.
"""
        skill = parse_skill("no-yaml", content)

        assert skill.slug == "no-yaml"
        assert skill.name == "no-yaml"  # Falls back to slug
        assert skill.description == ""
        # Content is stripped
        assert skill.content == content.strip()

    def test_parse_skill_empty_frontmatter(self) -> None:
        """Parse skill with empty frontmatter."""
        content = """---
---

Content after empty frontmatter.
"""
        skill = parse_skill("empty-fm", content)

        assert skill.slug == "empty-fm"
        assert skill.name == "empty-fm"
        assert skill.content.strip() == "Content after empty frontmatter."

    def test_parse_skill_preserves_content_formatting(self) -> None:
        """Ensure content formatting is preserved."""
        content = """---
name: Formatted
---

```python
def hello():
    print("world")
```

- List item 1
- List item 2
"""
        skill = parse_skill("formatted", content)

        assert "```python" in skill.content
        assert 'print("world")' in skill.content
        assert "- List item 1" in skill.content


class TestSkillToMarkdown:
    """Tests for skill_to_markdown function."""

    def test_skill_to_markdown_full(self) -> None:
        """Convert full skill to markdown."""
        skill = Skill(
            slug="test",
            name="Test Skill",
            description="A description",
            content="# Content\n\nBody here.",
            triggers=["trigger1", "trigger2"],
            allowed_roles=["admin"],
            metadata={"key": "value"},
        )

        md = skill_to_markdown(skill)

        assert "---" in md
        assert "name: Test Skill" in md
        assert "description: A description" in md
        assert "trigger1" in md
        assert "allowed_roles:" in md
        assert "admin" in md
        assert "key: value" in md
        assert "# Content" in md
        assert "Body here." in md

    def test_skill_to_markdown_minimal(self) -> None:
        """Convert minimal skill to markdown."""
        skill = Skill(
            slug="minimal",
            name="Minimal",
            description="",
            content="Just content.",
        )

        md = skill_to_markdown(skill)

        assert "name: Minimal" in md
        assert "Just content." in md

    def test_roundtrip(self) -> None:
        """Parse and regenerate should preserve data."""
        original = """---
name: Roundtrip Test
description: Testing roundtrip
triggers:
  - test
allowed_roles:
  - user
---

# Content

Some content here.
"""
        skill = parse_skill("roundtrip", original)
        regenerated = skill_to_markdown(skill)
        reparsed = parse_skill("roundtrip", regenerated)

        assert reparsed.name == skill.name
        assert reparsed.description == skill.description
        assert reparsed.triggers == skill.triggers
        assert reparsed.allowed_roles == skill.allowed_roles
