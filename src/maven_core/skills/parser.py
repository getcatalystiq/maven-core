"""SKILL.md parsing with YAML frontmatter."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill:
    """Parsed skill definition."""

    slug: str
    name: str
    description: str
    content: str
    triggers: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# Regex to match YAML frontmatter (--- at start and end)
# Allows for empty frontmatter (just ---\n---\n)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n", re.DOTALL)


def parse_skill(slug: str, content: str) -> Skill:
    """Parse a SKILL.md file content.

    Args:
        slug: Skill identifier (filename without extension)
        content: Raw file content

    Returns:
        Parsed Skill object
    """
    import yaml

    # Extract frontmatter
    match = FRONTMATTER_RE.match(content)
    if match:
        frontmatter_text = match.group(1)
        body = content[match.end():]
        try:
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError:
            frontmatter = {}
    else:
        frontmatter = {}
        body = content

    # Extract fields from frontmatter
    name = frontmatter.get("name", slug)
    description = frontmatter.get("description", "")
    triggers = frontmatter.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]

    # Extract access control (support both top-level and nested under 'access')
    access = frontmatter.get("access", {})
    allowed_roles = frontmatter.get("allowed_roles", access.get("allowed_roles", []))
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]

    # Store remaining metadata
    known_keys = {"name", "description", "triggers", "access", "allowed_roles"}
    metadata = {k: v for k, v in frontmatter.items() if k not in known_keys}

    return Skill(
        slug=slug,
        name=name,
        description=description,
        content=body.strip(),
        triggers=triggers,
        allowed_roles=allowed_roles,
        metadata=metadata,
    )


def skill_to_markdown(skill: Skill) -> str:
    """Convert a Skill back to SKILL.md format.

    Args:
        skill: Skill object

    Returns:
        SKILL.md formatted string
    """
    import yaml

    frontmatter: dict[str, Any] = {
        "name": skill.name,
        "description": skill.description,
    }

    if skill.triggers:
        frontmatter["triggers"] = skill.triggers

    if skill.allowed_roles:
        frontmatter["access"] = {"allowed_roles": skill.allowed_roles}

    if skill.metadata:
        frontmatter.update(skill.metadata)

    yaml_content = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    return f"---\n{yaml_content}---\n\n{skill.content}"
