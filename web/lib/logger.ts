import { AsyncLocalStorage } from 'async_hooks';

type RequestContext = { requestId: string };

const asyncLocalStorage = new AsyncLocalStorage<RequestContext>();

type LogLevel = 'info' | 'warn' | 'error' | 'debug';

interface LogEntry {
  level: number;
  time: string;
  name: string;
  msg?: string;
  requestId?: string;
  [key: string]: unknown;
}

const LEVEL_MAP: Record<LogLevel, number> = {
  debug: 20,
  info: 30,
  warn: 40,
  error: 50,
};

type LogWriter = (line: string) => void;

let writer: LogWriter = (line: string) => {
  process.stdout.write(line + '\n');
};

export function setWriter(w: LogWriter): void {
  writer = w;
}

interface Logger {
  info(obj: Record<string, unknown>, msg?: string): void;
  info(msg: string): void;
  warn(obj: Record<string, unknown>, msg?: string): void;
  warn(msg: string): void;
  error(obj: Record<string, unknown>, msg?: string): void;
  error(msg: string): void;
  debug(obj: Record<string, unknown>, msg?: string): void;
  debug(msg: string): void;
}

function makeLogger(bindings: Record<string, unknown> = {}): Logger {
  function emit(level: LogLevel, args: unknown[]): void {
    let extra: Record<string, unknown> = {};
    let msg: string | undefined;

    if (args.length === 1 && typeof args[0] === 'string') {
      msg = args[0] as string;
    } else if (args.length === 1 && typeof args[0] === 'object' && args[0] !== null) {
      extra = args[0] as Record<string, unknown>;
    } else if (args.length >= 2 && typeof args[0] === 'object' && args[0] !== null && typeof args[1] === 'string') {
      extra = args[0] as Record<string, unknown>;
      msg = args[1] as string;
    } else if (args.length >= 2 && typeof args[0] === 'string') {
      msg = args[0];
    }

    const entry: LogEntry = {
      level: LEVEL_MAP[level],
      time: new Date().toISOString(),
      name: 'camera-web',
      ...bindings,
      ...extra,
    };
    if (msg !== undefined) entry.msg = msg;

    writer(JSON.stringify(entry));
  }

  return {
    info: (...args: unknown[]) => emit('info', args),
    warn: (...args: unknown[]) => emit('warn', args),
    error: (...args: unknown[]) => emit('error', args),
    debug: (...args: unknown[]) => emit('debug', args),
  };
}

const baseLogger = makeLogger();

export function withRequestLogger<T>(requestId: string, fn: () => T): T {
  return asyncLocalStorage.run({ requestId }, fn);
}

export function getRequestId(): string | undefined {
  return asyncLocalStorage.getStore()?.requestId;
}

export function log(): Logger {
  const ctx = asyncLocalStorage.getStore();
  if (ctx) {
    return makeLogger({ requestId: ctx.requestId });
  }
  return baseLogger;
}
