import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { log, withRequestLogger, setWriter } from '@/lib/logger';

describe('logger', () => {
  let lines: string[];

  beforeEach(() => {
    lines = [];
    setWriter((line: string) => {
      lines.push(line);
    });
  });

  afterEach(() => {
    setWriter((line: string) => {
      process.stdout.write(line + '\n');
    });
  });

  it('emits JSON with requestId inside withRequestLogger', () => {
    withRequestLogger('test-123', () => {
      log().info({ event: 'test' }, 'test message');
    });

    expect(lines.length).toBe(1);
    const parsed = JSON.parse(lines[0]);
    expect(parsed.requestId).toBe('test-123');
    expect(parsed.event).toBe('test');
    expect(parsed.msg).toBe('test message');
    expect(parsed.name).toBe('camera-web');
    expect(parsed.level).toBe(30);
    expect(typeof parsed.time).toBe('string');
  });

  it('does not crash without ALS store', () => {
    expect(() => {
      log().info('no request context');
    }).not.toThrow();
    expect(lines.length).toBe(1);
    const parsed = JSON.parse(lines[0]);
    expect(parsed.requestId).toBeUndefined();
    expect(parsed.msg).toBe('no request context');
  });
});
