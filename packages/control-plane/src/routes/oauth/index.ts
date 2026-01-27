/**
 * OAuth routes
 */

import { Hono } from 'hono';
import { jwtAuth } from '../../middleware/auth';
import { authorizeRoute } from './authorize';
import { callbackRoute } from './callback';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// Authorization initiation requires auth
app.use('/*/authorize', jwtAuth);
app.route('/', authorizeRoute);

// Callback is public (user redirected from OAuth provider)
app.route('/', callbackRoute);

export { app as oauthRoutes };
