import { NextRequest, NextResponse } from 'next/server';
import { log, withRequestLogger } from '@/lib/logger';

export async function GET(request: NextRequest) {
  const requestId = request.headers.get('x-request-id') || 'unknown';

  const result = withRequestLogger(requestId, () => {
    log().info({ path: '/api/health' }, 'health check');
    return { status: 'ok' };
  });

  return NextResponse.json(result);
}
