/**
 * User management admin routes
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import {
  createUserSchema,
  updateUserSchema,
  paginationSchema,
  hashPassword,
} from '@maven/shared';
import {
  createUser,
  getUserById,
  getUserByEmail,
  listUsers,
  updateUser,
  deleteUser,
} from '../../services/database';
import { deleteAllUserTokens } from '../../services/connectors';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// List users
app.get('/', zValidator('query', paginationSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { offset, limit } = c.req.valid('query');

  const result = await listUsers(c.env.DB, tenantId, offset, limit);

  // Remove password hashes from response
  const users = result.users.map(({ passwordHash, ...user }) => user);

  return c.json({
    users,
    total: result.total,
    offset,
    limit,
  });
});

// Get single user
app.get('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const user = await getUserById(c.env.DB, id);

  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  const { passwordHash, ...userWithoutPassword } = user;
  return c.json(userWithoutPassword);
});

// Create user
app.post('/', zValidator('json', createUserSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { email, password, roles } = c.req.valid('json');

  // Check if user already exists
  const existingUser = await getUserByEmail(c.env.DB, email, tenantId);
  if (existingUser) {
    throw new HTTPException(409, { message: 'User already exists' });
  }

  // Hash password
  const passwordHash = await hashPassword(password);

  // Create user
  const user = await createUser(c.env.DB, {
    id: crypto.randomUUID(),
    email,
    tenantId,
    roles,
    passwordHash,
    enabled: true,
  });

  const { passwordHash: _, ...userWithoutPassword } = user;
  return c.json(userWithoutPassword, 201);
});

// Update user
app.patch('/:id', zValidator('json', updateUserSchema), async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');
  const updates = c.req.valid('json');

  const user = await getUserById(c.env.DB, id);
  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  // Hash new password if provided
  let passwordHash: string | undefined;
  if (updates.password) {
    passwordHash = await hashPassword(updates.password);
  }

  await updateUser(c.env.DB, id, {
    email: updates.email,
    roles: updates.roles,
    passwordHash,
    enabled: updates.enabled,
  });

  const updatedUser = await getUserById(c.env.DB, id);
  const { passwordHash: _, ...userWithoutPassword } = updatedUser!;
  return c.json(userWithoutPassword);
});

// Delete user
app.delete('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');
  const currentUserId = c.get('userId');

  // Prevent self-deletion
  if (id === currentUserId) {
    throw new HTTPException(400, { message: 'Cannot delete yourself' });
  }

  const user = await getUserById(c.env.DB, id);
  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  // Clean up user data and connector tokens
  await Promise.all([
    deleteUser(c.env.DB, id),
    deleteAllUserTokens(c.env.KV, tenantId, id),
  ]);

  return c.json({ message: 'User deleted' });
});

export { app as usersRoute };
