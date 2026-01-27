/**
 * Skill management admin routes
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { createSkillSchema, updateSkillSchema, paginationSchema } from '@maven/shared';
import {
  createSkill,
  getSkillById,
  getSkillContent,
  listSkills,
  updateSkill,
  deleteSkill,
  assignSkillToRoles,
} from '../../services/skills';
import type { Env, Variables } from '../../index';
import { z } from 'zod';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// List skills
app.get('/', zValidator('query', paginationSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { offset, limit } = c.req.valid('query');

  const result = await listSkills(c.env.DB, tenantId, offset, limit);

  return c.json({
    skills: result.skills,
    total: result.total,
    offset,
    limit,
  });
});

// Get single skill with content
app.get('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const skill = await getSkillById(c.env.DB, id);
  if (!skill || skill.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Skill not found' });
  }

  // Get content from R2
  const content = await getSkillContent(c.env.FILES, skill.r2Path);

  return c.json({
    ...skill,
    content,
  });
});

// Create skill
app.post('/', zValidator('json', createSkillSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { name, description, content, roles } = c.req.valid('json');

  const skill = await createSkill(
    c.env.DB,
    c.env.FILES,
    {
      id: crypto.randomUUID(),
      tenantId,
      name,
      description: description || '',
      r2Path: '', // Will be set by createSkill
      roles,
      enabled: true,
    },
    content
  );

  return c.json(skill, 201);
});

// Update skill
app.patch('/:id', zValidator('json', updateSkillSchema), async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');
  const updates = c.req.valid('json');

  const skill = await getSkillById(c.env.DB, id);
  if (!skill || skill.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Skill not found' });
  }

  await updateSkill(c.env.DB, c.env.FILES, id, updates, updates.content);

  const updatedSkill = await getSkillById(c.env.DB, id);
  return c.json(updatedSkill);
});

// Assign skill to roles
app.post(
  '/:id/assign',
  zValidator('json', z.object({ roles: z.array(z.string()) })),
  async (c) => {
    const id = c.req.param('id');
    const tenantId = c.get('tenantId');
    const { roles } = c.req.valid('json');

    const skill = await getSkillById(c.env.DB, id);
    if (!skill || skill.tenantId !== tenantId) {
      throw new HTTPException(404, { message: 'Skill not found' });
    }

    await assignSkillToRoles(c.env.DB, id, roles);

    return c.json({ message: 'Skill roles updated', roles });
  }
);

// Enable/disable skill
app.post('/:id/enable', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const skill = await getSkillById(c.env.DB, id);
  if (!skill || skill.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Skill not found' });
  }

  await updateSkill(c.env.DB, c.env.FILES, id, { enabled: true });
  return c.json({ message: 'Skill enabled' });
});

app.post('/:id/disable', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const skill = await getSkillById(c.env.DB, id);
  if (!skill || skill.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Skill not found' });
  }

  await updateSkill(c.env.DB, c.env.FILES, id, { enabled: false });
  return c.json({ message: 'Skill disabled' });
});

// Delete skill
app.delete('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const skill = await getSkillById(c.env.DB, id);
  if (!skill || skill.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Skill not found' });
  }

  await deleteSkill(c.env.DB, c.env.FILES, id);
  return c.json({ message: 'Skill deleted' });
});

export { app as skillsRoute };
