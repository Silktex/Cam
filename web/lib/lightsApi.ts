const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface RequestIdError extends Error {
  requestId?: string;
}

function attachRequestId(error: Error, response: Response): Error {
  const requestId = response.headers.get('x-request-id');
  if (requestId) {
    (error as RequestIdError).requestId = requestId;
  }
  return error;
}

export interface LightState {
  id: number;
  name: string;
  pin: number;
  on: boolean;
  brightness: number;
}

export interface LightsResponse {
  lights: LightState[];
  connected: boolean;
  host: string;
}

export interface HealthResponse {
  status: string;
  connected: boolean;
  host: string;
  port: number;
  total_lights: number;
  message?: string;
}

export const lightsApi = {
  async getLights(): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights`);
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to fetch lights'), response);
    }
    return response.json();
  },

  async getHealth(): Promise<HealthResponse> {
    const response = await fetch(`${API_URL}/api/lights/health`);
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to fetch health status'), response);
    }
    return response.json();
  },

  async getLight(id: number): Promise<LightState> {
    const response = await fetch(`${API_URL}/api/lights/${id}`);
    if (!response.ok) {
      throw attachRequestId(new Error(`Failed to fetch light ${id}`), response);
    }
    return response.json();
  },

  async setLight(id: number, on: boolean, brightness?: number): Promise<LightState> {
    const response = await fetch(`${API_URL}/api/lights/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, brightness }),
    });
    if (!response.ok) {
      throw attachRequestId(new Error(`Failed to update light ${id}`), response);
    }
    return response.json();
  },

  async allOn(brightness: number = 100): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all/on?brightness=${brightness}`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to turn all lights on'), response);
    }
    return response.json();
  },

  async allOff(): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all/off`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to turn all lights off'), response);
    }
    return response.json();
  },

  async setAll(on: boolean, brightness?: number): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, brightness }),
    });
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to update all lights'), response);
    }
    return response.json();
  },

  async reconnect(): Promise<{ success: boolean; connected: boolean; message: string }> {
    const response = await fetch(`${API_URL}/api/lights/reconnect`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw attachRequestId(new Error('Failed to reconnect'), response);
    }
    return response.json();
  },
};
