/**
 * Admin Log Viewer API
 *
 * Provides endpoints to query and read agent container logs stored in R2.
 *
 * Logs are stored as NDJSON files at:
 * logs/{tenantId}/{date}/{timestamp}.ndjson
 */

import { Hono } from 'hono';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

interface LogFile {
  key: string;
  date: string;
  timestamp: number;
  size: number;
  entryCount?: number;
}

interface LogEntry {
  ts: string;
  level: 'info' | 'warn' | 'error';
  msg: string;
  tenant?: string;
  session?: string;
  context?: Record<string, unknown>;
}

/**
 * List available log files for a tenant
 *
 * GET /admin/logs?tenantId=xxx&since=2024-01-01&until=2024-01-31&limit=100
 */
app.get('/', async (c) => {
  const tenantId = c.req.query('tenantId');
  const since = c.req.query('since'); // ISO date string (YYYY-MM-DD)
  const until = c.req.query('until'); // ISO date string (YYYY-MM-DD)
  const limit = parseInt(c.req.query('limit') || '100', 10);

  // Check if user is super admin or has access to the tenant
  const isSuperAdmin = c.get('isSuperAdmin');
  const userTenantId = c.get('tenantId');

  if (!tenantId) {
    return c.json({ error: 'tenantId query parameter is required' }, 400);
  }

  // Only super admins can view logs for any tenant
  // Regular admins can only view their own tenant's logs
  if (!isSuperAdmin && tenantId !== userTenantId) {
    return c.json({ error: 'Unauthorized to view logs for this tenant' }, 403);
  }

  try {
    const prefix = `logs/${tenantId}/`;
    const listed = await c.env.FILES.list({
      prefix,
      limit: Math.min(limit, 1000),
    });

    // Parse and filter log files
    const logFiles: LogFile[] = [];
    const sinceDate = since ? new Date(since) : null;
    const untilDate = until ? new Date(until) : null;

    for (const obj of listed.objects) {
      // Parse path: logs/{tenantId}/{date}/{timestamp}.ndjson
      const parts = obj.key.split('/');
      if (parts.length < 4) continue;

      const dateStr = parts[2];
      const logDate = new Date(dateStr);

      // Apply date filters
      if (sinceDate && logDate < sinceDate) continue;
      if (untilDate && logDate > untilDate) continue;

      const timestampPart = parts[3].replace('.ndjson', '');
      const timestamp = parseInt(timestampPart, 10);

      logFiles.push({
        key: obj.key,
        date: dateStr,
        timestamp,
        size: obj.size,
        entryCount: obj.customMetadata?.entryCount
          ? parseInt(obj.customMetadata.entryCount, 10)
          : undefined,
      });
    }

    // Sort by timestamp descending (most recent first)
    logFiles.sort((a, b) => b.timestamp - a.timestamp);

    return c.json({
      tenantId,
      files: logFiles.slice(0, limit),
      total: logFiles.length,
      truncated: listed.truncated,
    });
  } catch (error) {
    console.error('Failed to list logs:', error);
    return c.json({ error: 'Failed to list logs' }, 500);
  }
});

/**
 * Read a specific log file
 *
 * GET /admin/logs/:tenantId/:date/:filename
 */
app.get('/:tenantId/:date/:filename', async (c) => {
  const { tenantId, date, filename } = c.req.param();

  // Check authorization
  const isSuperAdmin = c.get('isSuperAdmin');
  const userTenantId = c.get('tenantId');

  if (!isSuperAdmin && tenantId !== userTenantId) {
    return c.json({ error: 'Unauthorized to view logs for this tenant' }, 403);
  }

  const key = `logs/${tenantId}/${date}/${filename}`;

  try {
    const obj = await c.env.FILES.get(key);

    if (!obj) {
      return c.json({ error: 'Log file not found' }, 404);
    }

    const content = await obj.text();

    // Parse NDJSON
    const entries: LogEntry[] = content
      .split('\n')
      .filter((line) => line.trim())
      .map((line) => {
        try {
          return JSON.parse(line) as LogEntry;
        } catch {
          return null;
        }
      })
      .filter((e): e is LogEntry => e !== null);

    return c.json({
      key,
      date,
      entries,
      count: entries.length,
    });
  } catch (error) {
    console.error('Failed to read log file:', error);
    return c.json({ error: 'Failed to read log file' }, 500);
  }
});

/**
 * Search logs for a tenant
 *
 * GET /admin/logs/search?tenantId=xxx&query=error&level=error&since=2024-01-01&limit=100
 */
app.get('/search', async (c) => {
  const tenantId = c.req.query('tenantId');
  const query = c.req.query('query') || '';
  const level = c.req.query('level') as 'info' | 'warn' | 'error' | undefined;
  const sessionId = c.req.query('sessionId');
  const since = c.req.query('since');
  const limit = parseInt(c.req.query('limit') || '100', 10);

  // Check authorization
  const isSuperAdmin = c.get('isSuperAdmin');
  const userTenantId = c.get('tenantId');

  if (!tenantId) {
    return c.json({ error: 'tenantId query parameter is required' }, 400);
  }

  if (!isSuperAdmin && tenantId !== userTenantId) {
    return c.json({ error: 'Unauthorized to view logs for this tenant' }, 403);
  }

  try {
    const prefix = `logs/${tenantId}/`;
    const listed = await c.env.FILES.list({
      prefix,
      limit: 100, // Max files to scan
    });

    const sinceDate = since ? new Date(since) : null;
    const matchingEntries: (LogEntry & { file: string })[] = [];

    // Scan files (most recent first based on listing order)
    for (const obj of listed.objects) {
      if (matchingEntries.length >= limit) break;

      // Parse date from path
      const parts = obj.key.split('/');
      if (parts.length < 4) continue;

      const dateStr = parts[2];
      const logDate = new Date(dateStr);
      if (sinceDate && logDate < sinceDate) continue;

      // Read file
      const content = await c.env.FILES.get(obj.key);
      if (!content) continue;

      const text = await content.text();
      const entries = text
        .split('\n')
        .filter((line) => line.trim())
        .map((line) => {
          try {
            return JSON.parse(line) as LogEntry;
          } catch {
            return null;
          }
        })
        .filter((e): e is LogEntry => e !== null);

      // Filter entries
      for (const entry of entries) {
        if (matchingEntries.length >= limit) break;

        // Apply filters
        if (level && entry.level !== level) continue;
        if (sessionId && entry.session !== sessionId) continue;
        if (query && !entry.msg.toLowerCase().includes(query.toLowerCase())) continue;

        matchingEntries.push({ ...entry, file: obj.key });
      }
    }

    // Sort by timestamp descending
    matchingEntries.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());

    return c.json({
      tenantId,
      query,
      filters: { level, sessionId, since },
      entries: matchingEntries,
      count: matchingEntries.length,
    });
  } catch (error) {
    console.error('Failed to search logs:', error);
    return c.json({ error: 'Failed to search logs' }, 500);
  }
});

/**
 * Delete logs for a tenant (cleanup)
 *
 * DELETE /admin/logs?tenantId=xxx&before=2024-01-01
 */
app.delete('/', async (c) => {
  const tenantId = c.req.query('tenantId');
  const before = c.req.query('before'); // ISO date string

  // Only super admins can delete logs
  const isSuperAdmin = c.get('isSuperAdmin');
  if (!isSuperAdmin) {
    return c.json({ error: 'Only super admins can delete logs' }, 403);
  }

  if (!tenantId) {
    return c.json({ error: 'tenantId query parameter is required' }, 400);
  }

  const beforeDate = before ? new Date(before) : new Date();

  try {
    const prefix = `logs/${tenantId}/`;
    const listed = await c.env.FILES.list({
      prefix,
      limit: 1000,
    });

    const deletePromises: Promise<void>[] = [];

    for (const obj of listed.objects) {
      const parts = obj.key.split('/');
      if (parts.length < 4) continue;

      const dateStr = parts[2];
      const logDate = new Date(dateStr);

      if (logDate < beforeDate) {
        deletePromises.push(c.env.FILES.delete(obj.key));
      }
    }

    await Promise.all(deletePromises);

    return c.json({
      tenantId,
      deleted: deletePromises.length,
      before: beforeDate.toISOString(),
    });
  } catch (error) {
    console.error('Failed to delete logs:', error);
    return c.json({ error: 'Failed to delete logs' }, 500);
  }
});

export { app as logsRoute };
