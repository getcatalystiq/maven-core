/**
 * Structured Logger for Maven Agent
 *
 * Captures all console.log/error/warn calls, batches them, and sends
 * to the Durable Object's /logs endpoint for persistence in R2.
 *
 * Falls back to stdout if send fails (to prevent log loss).
 */

export interface LogEntry {
  ts: string; // ISO timestamp
  level: 'info' | 'warn' | 'error';
  msg: string;
  tenant?: string;
  session?: string;
  context?: Record<string, unknown>;
}

interface LoggerConfig {
  /** DO endpoint to send logs to (e.g., http://localhost:8788/logs) */
  endpoint?: string;
  /** Tenant ID for log context */
  tenantId?: string;
  /** Max entries before flushing */
  maxBatchSize?: number;
  /** Max time (ms) between flushes */
  flushIntervalMs?: number;
  /** Enable console passthrough for local debugging */
  passthrough?: boolean;
}

// Store original console methods
const originalConsole = {
  log: console.log.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

class StructuredLogger {
  private buffer: LogEntry[] = [];
  private config: Required<LoggerConfig>;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private currentSessionId: string | null = null;
  private isFlushing = false;

  constructor(config: LoggerConfig = {}) {
    this.config = {
      endpoint: config.endpoint || '',
      tenantId: config.tenantId || '',
      maxBatchSize: config.maxBatchSize ?? 50,
      flushIntervalMs: config.flushIntervalMs ?? 5000,
      passthrough: config.passthrough ?? true,
    };
  }

  /**
   * Initialize the logger and replace console methods
   */
  init(): void {
    // Start periodic flush
    if (this.config.flushIntervalMs > 0) {
      this.flushTimer = setInterval(() => {
        this.flush().catch((err) => {
          originalConsole.error('[Logger] Flush error:', err);
        });
      }, this.config.flushIntervalMs);
    }

    // Replace console methods
    console.log = (...args: unknown[]) => this.log('info', args);
    console.warn = (...args: unknown[]) => this.log('warn', args);
    console.error = (...args: unknown[]) => this.log('error', args);
  }

  /**
   * Set the current session ID for log context
   */
  setSessionId(sessionId: string): void {
    this.currentSessionId = sessionId;
  }

  /**
   * Clear the current session ID
   */
  clearSessionId(): void {
    this.currentSessionId = null;
  }

  /**
   * Update configuration (e.g., when tenant ID becomes available)
   */
  configure(config: Partial<LoggerConfig>): void {
    if (config.endpoint !== undefined) this.config.endpoint = config.endpoint;
    if (config.tenantId !== undefined) this.config.tenantId = config.tenantId;
    if (config.maxBatchSize !== undefined) this.config.maxBatchSize = config.maxBatchSize;
    if (config.passthrough !== undefined) this.config.passthrough = config.passthrough;
  }

  /**
   * Internal log method
   */
  private log(level: LogEntry['level'], args: unknown[]): void {
    // Format message from args
    const msg = args
      .map((arg) => {
        if (typeof arg === 'string') return arg;
        if (arg instanceof Error) return `${arg.message}\n${arg.stack}`;
        try {
          return JSON.stringify(arg);
        } catch {
          return String(arg);
        }
      })
      .join(' ');

    // Create log entry
    const entry: LogEntry = {
      ts: new Date().toISOString(),
      level,
      msg,
    };

    // Add context if available
    if (this.config.tenantId) {
      entry.tenant = this.config.tenantId;
    }
    if (this.currentSessionId) {
      entry.session = this.currentSessionId;
    }

    // Add to buffer
    this.buffer.push(entry);

    // Pass through to original console if enabled
    if (this.config.passthrough) {
      const consoleFn = level === 'error' ? originalConsole.error :
                        level === 'warn' ? originalConsole.warn :
                        originalConsole.log;
      consoleFn(msg);
    }

    // Flush if buffer is full
    if (this.buffer.length >= this.config.maxBatchSize) {
      this.flush().catch((err) => {
        originalConsole.error('[Logger] Flush error:', err);
      });
    }
  }

  /**
   * Flush buffered logs to the endpoint
   */
  async flush(): Promise<void> {
    // Prevent concurrent flushes
    if (this.isFlushing || this.buffer.length === 0) {
      return;
    }

    // No endpoint configured, just clear buffer
    if (!this.config.endpoint) {
      this.buffer = [];
      return;
    }

    this.isFlushing = true;
    const entries = this.buffer;
    this.buffer = [];

    try {
      const response = await fetch(this.config.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-Id': this.config.tenantId,
        },
        body: JSON.stringify({ entries }),
      });

      if (!response.ok) {
        // Log failure but don't throw - we've already cleared the buffer
        // to prevent memory growth
        originalConsole.error(`[Logger] Failed to send logs: ${response.status}`);
      }
    } catch (err) {
      // Log failure to original console
      originalConsole.error('[Logger] Failed to send logs:', err);
      // Logs are lost at this point, but we can't buffer indefinitely
    } finally {
      this.isFlushing = false;
    }
  }

  /**
   * Shutdown the logger, flushing any remaining logs
   */
  async shutdown(): Promise<void> {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();

    // Restore original console methods
    console.log = originalConsole.log;
    console.warn = originalConsole.warn;
    console.error = originalConsole.error;
  }
}

// Singleton instance
let loggerInstance: StructuredLogger | null = null;

/**
 * Get or create the logger instance
 */
export function getLogger(): StructuredLogger {
  if (!loggerInstance) {
    loggerInstance = new StructuredLogger();
  }
  return loggerInstance;
}

/**
 * Initialize the structured logger
 */
export function initLogger(config: LoggerConfig): StructuredLogger {
  const logger = getLogger();
  logger.configure(config);
  logger.init();
  return logger;
}

/**
 * Shutdown the logger (call on process exit)
 */
export async function shutdownLogger(): Promise<void> {
  if (loggerInstance) {
    await loggerInstance.shutdown();
  }
}

export { originalConsole };
