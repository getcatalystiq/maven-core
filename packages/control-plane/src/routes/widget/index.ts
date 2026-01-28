/**
 * Widget routes
 *
 * Endpoints for the maven-widget frontend. These routes require JWT auth
 * but not admin role - any authenticated user can access them.
 */

import { Hono } from 'hono';
import { widgetConnectorsRoute } from './connectors';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

app.route('/connectors', widgetConnectorsRoute);

export { app as widgetRoutes };
