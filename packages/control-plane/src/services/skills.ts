/**
 * Skills service - manages skill metadata in D1 and content in R2
 */

import type { Skill, SkillContent } from '@maven/shared';

// Skill operations
export async function createSkill(
  db: D1Database,
  files: R2Bucket,
  skill: Omit<Skill, 'createdAt' | 'updatedAt'>,
  content: string
): Promise<Skill> {
  const now = new Date().toISOString();
  const r2Path = `skills/${skill.tenantId}/${skill.name}/`;

  // Store metadata in D1
  await db
    .prepare(
      `INSERT INTO skills (id, tenant_id, name, description, r2_path, roles, enabled, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      skill.id,
      skill.tenantId,
      skill.name,
      skill.description,
      r2Path,
      skill.roles ? JSON.stringify(skill.roles) : null,
      skill.enabled ? 1 : 0,
      now,
      now
    )
    .run();

  // Store SKILL.md in R2
  await files.put(`${r2Path}SKILL.md`, content, {
    customMetadata: { skillId: skill.id },
  });

  return { ...skill, r2Path, createdAt: now, updatedAt: now };
}

export async function getSkillById(db: D1Database, id: string): Promise<Skill | null> {
  const row = await db
    .prepare('SELECT * FROM skills WHERE id = ?')
    .bind(id)
    .first<SkillRow>();

  return row ? rowToSkill(row) : null;
}

export async function getSkillContent(files: R2Bucket, r2Path: string): Promise<string | null> {
  const obj = await files.get(`${r2Path}SKILL.md`);
  if (!obj) return null;
  return obj.text();
}

export async function listSkills(
  db: D1Database,
  tenantId: string,
  offset = 0,
  limit = 20
): Promise<{ skills: Skill[]; total: number }> {
  const [skillsResult, countResult] = await Promise.all([
    db
      .prepare(
        'SELECT * FROM skills WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?'
      )
      .bind(tenantId, limit, offset)
      .all<SkillRow>(),
    db
      .prepare('SELECT COUNT(*) as count FROM skills WHERE tenant_id = ?')
      .bind(tenantId)
      .first<{ count: number }>(),
  ]);

  return {
    skills: skillsResult.results.map(rowToSkill),
    total: countResult?.count || 0,
  };
}

export async function listSkillsForUser(
  db: D1Database,
  tenantId: string,
  userId: string,
  userRoles: string[]
): Promise<Skill[]> {
  // Get all enabled skills for tenant
  const result = await db
    .prepare('SELECT * FROM skills WHERE tenant_id = ? AND enabled = 1')
    .bind(tenantId)
    .all<SkillRow>();

  const skills = result.results.map(rowToSkill);

  // Filter by role access
  return skills.filter((skill) => {
    if (!skill.roles || skill.roles.length === 0) {
      return true; // No role restriction
    }
    return skill.roles.some((role) => userRoles.includes(role));
  });
}

export async function updateSkill(
  db: D1Database,
  files: R2Bucket,
  id: string,
  updates: Partial<Pick<Skill, 'description' | 'roles' | 'enabled'>>,
  content?: string
): Promise<void> {
  const skill = await getSkillById(db, id);
  if (!skill) {
    throw new Error('Skill not found');
  }

  const setClauses: string[] = ['updated_at = ?'];
  const values: (string | number)[] = [new Date().toISOString()];

  if (updates.description !== undefined) {
    setClauses.push('description = ?');
    values.push(updates.description);
  }
  if (updates.roles !== undefined) {
    setClauses.push('roles = ?');
    values.push(JSON.stringify(updates.roles));
  }
  if (updates.enabled !== undefined) {
    setClauses.push('enabled = ?');
    values.push(updates.enabled ? 1 : 0);
  }

  values.push(id);

  await db
    .prepare(`UPDATE skills SET ${setClauses.join(', ')} WHERE id = ?`)
    .bind(...values)
    .run();

  // Update content in R2 if provided
  if (content) {
    await files.put(`${skill.r2Path}SKILL.md`, content, {
      customMetadata: { skillId: id },
    });
  }
}

export async function deleteSkill(
  db: D1Database,
  files: R2Bucket,
  id: string
): Promise<void> {
  const skill = await getSkillById(db, id);
  if (!skill) {
    throw new Error('Skill not found');
  }

  // Delete from D1 and list R2 objects in parallel
  const [, initialObjects] = await Promise.all([
    db.prepare('DELETE FROM skills WHERE id = ?').bind(id).run(),
    files.list({ prefix: skill.r2Path }),
  ]);

  // Delete all R2 objects in parallel
  if (initialObjects.objects.length > 0) {
    await Promise.all(initialObjects.objects.map((obj) => files.delete(obj.key)));
  }

  // Handle pagination if there are more objects
  let objects = initialObjects;
  while (objects.truncated) {
    const moreObjects = await files.list({ prefix: skill.r2Path, cursor: objects.cursor });
    if (moreObjects.objects.length > 0) {
      await Promise.all(moreObjects.objects.map((obj) => files.delete(obj.key)));
    }
    objects = moreObjects;
  }
}

// Skill assignments
export async function assignSkillToRoles(
  db: D1Database,
  skillId: string,
  roles: string[]
): Promise<void> {
  await db
    .prepare('UPDATE skills SET roles = ?, updated_at = ? WHERE id = ?')
    .bind(JSON.stringify(roles), new Date().toISOString(), skillId)
    .run();
}

// Row types and converters
interface SkillRow {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  r2_path: string;
  roles: string | null;
  enabled: number;
  created_at: string;
  updated_at: string;
}

function rowToSkill(row: SkillRow): Skill {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    name: row.name,
    description: row.description || '',
    r2Path: row.r2_path,
    roles: row.roles ? JSON.parse(row.roles) : undefined,
    enabled: row.enabled === 1,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}
