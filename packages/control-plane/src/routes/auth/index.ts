/**
 * Auth routes
 */

import { Hono } from 'hono';
import { loginRoute } from './login';
import { registerRoute } from './register';
import { refreshRoute } from './refresh';
import { authRateLimitMiddleware } from '../../middleware/ratelimit';
import type { Env } from '../../index';

const app = new Hono<{ Bindings: Env }>();

// Apply rate limiting to all auth endpoints
app.use('*', authRateLimitMiddleware);

app.route('/login', loginRoute);
app.route('/register', registerRoute);
app.route('/refresh', refreshRoute);

export { app as authRoutes };
export { jwksHandler } from './jwks';
