/**
 * Admin routes
 */

import { Hono } from 'hono';
import { usersRoute } from './users';
import { tenantsRoute } from './tenants';
import { provisionRoute } from './provision';
import { skillsRoute } from './skills';
import { connectorsRoute } from './connectors';
import { logsRoute } from './logs';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

app.route('/users', usersRoute);
app.route('/tenants/provision', provisionRoute);  // Must be before /tenants to match first
app.route('/tenants', tenantsRoute);
app.route('/skills', skillsRoute);
app.route('/connectors', connectorsRoute);
app.route('/logs', logsRoute);

export { app as adminRoutes };
