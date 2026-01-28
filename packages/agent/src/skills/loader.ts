/**
 * Skills loader - parses SKILL.md files from filesystem
 *
 * Supports cache invalidation for hot-reload when skills are
 * dynamically injected by the Sandbox SDK.
 */

import { readdir, readFile } from 'fs/promises';
import { join } from 'path';
import matter from 'gray-matter';

export interface SkillContent {
  name: string;
  description: string;
  prompt: string;
  roles?: string[];
  tools?: string[];
  agents?: string[];
}

// Cache for loaded skills
let skillsCache: SkillContent[] | null = null;
let skillsCacheTime = 0;
const CACHE_TTL = 60000; // 1 minute TTL for cache

/**
 * Load all skills from the skills directory
 *
 * @param skillsPath - Custom path to skills directory (optional)
 * @param forceReload - Force reload even if cache is valid (optional)
 */
export async function loadSkills(
  skillsPath?: string,
  forceReload = false
): Promise<SkillContent[]> {
  const now = Date.now();

  // Return cached skills if still valid and not forcing reload
  if (!forceReload && skillsCache && now - skillsCacheTime < CACHE_TTL) {
    return skillsCache;
  }

  const path = skillsPath || process.env.SKILLS_PATH || '/app/skills';

  try {
    const skillDirs = await readdir(path);
    const skills: SkillContent[] = [];

    for (const dir of skillDirs) {
      const skillMdPath = join(path, dir, 'SKILL.md');
      try {
        const content = await readFile(skillMdPath, 'utf-8');
        const skill = parseSkillMd(dir, content);
        if (skill) {
          skills.push(skill);
        }
      } catch {
        // Skip if SKILL.md doesn't exist
      }
    }

    // Update cache
    skillsCache = skills;
    skillsCacheTime = now;

    return skills;
  } catch {
    // Skills directory doesn't exist
    return [];
  }
}

/**
 * Invalidate the skills cache
 *
 * Call this when skills have been updated (e.g., after dynamic injection)
 * to force the next loadSkills() call to reload from disk.
 */
export function invalidateSkillsCache(): void {
  skillsCache = null;
  skillsCacheTime = 0;
}

/**
 * Get cache status for debugging/monitoring
 */
export function getSkillsCacheStatus(): {
  cached: boolean;
  age: number;
  ttl: number;
  count: number;
} {
  const now = Date.now();
  return {
    cached: skillsCache !== null,
    age: skillsCache ? now - skillsCacheTime : 0,
    ttl: CACHE_TTL,
    count: skillsCache?.length ?? 0,
  };
}

/**
 * Parse SKILL.md content with YAML frontmatter
 */
function parseSkillMd(name: string, content: string): SkillContent | null {
  try {
    const { data, content: prompt } = matter(content);

    return {
      name,
      description: data.description || '',
      prompt: prompt.trim(),
      roles: data.roles,
      tools: data.tools,
      agents: data.agents,
    };
  } catch {
    return null;
  }
}

/**
 * Filter skills by user roles
 */
export function filterSkillsByRoles(skills: SkillContent[], userRoles: string[]): SkillContent[] {
  return skills.filter((skill) => {
    if (!skill.roles || skill.roles.length === 0) {
      return true; // No role restriction
    }
    return skill.roles.some((role) => userRoles.includes(role));
  });
}

/**
 * Build system prompt from skills
 */
export function buildSystemPromptFromSkills(skills: SkillContent[]): string {
  if (skills.length === 0) {
    return '';
  }

  const skillDescriptions = skills
    .map((s) => `- **${s.name}**: ${s.description}`)
    .join('\n');

  return `You have access to the following skills:\n${skillDescriptions}`;
}
