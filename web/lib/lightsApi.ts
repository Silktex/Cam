const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

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
  /**
   * Get all light states
   */
  async getLights(): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights`);
    if (!response.ok) {
      throw new Error('Failed to fetch lights');
    }
    return response.json();
  },

  /**
   * Get health status
   */
  async getHealth(): Promise<HealthResponse> {
    const response = await fetch(`${API_URL}/api/lights/health`);
    if (!response.ok) {
      throw new Error('Failed to fetch health status');
    }
    return response.json();
  },

  /**
   * Get a specific light
   */
  async getLight(id: number): Promise<LightState> {
    const response = await fetch(`${API_URL}/api/lights/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch light ${id}`);
    }
    return response.json();
  },

  /**
   * Update a specific light
   */
  async setLight(id: number, on: boolean, brightness?: number): Promise<LightState> {
    const response = await fetch(`${API_URL}/api/lights/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, brightness }),
    });
    if (!response.ok) {
      throw new Error(`Failed to update light ${id}`);
    }
    return response.json();
  },

  /**
   * Turn all lights on
   */
  async allOn(brightness: number = 100): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all/on?brightness=${brightness}`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to turn all lights on');
    }
    return response.json();
  },

  /**
   * Turn all lights off
   */
  async allOff(): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all/off`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to turn all lights off');
    }
    return response.json();
  },

  /**
   * Update all lights
   */
  async setAll(on: boolean, brightness?: number): Promise<LightsResponse> {
    const response = await fetch(`${API_URL}/api/lights/all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on, brightness }),
    });
    if (!response.ok) {
      throw new Error('Failed to update all lights');
    }
    return response.json();
  },

  /**
   * Reconnect to ESP32
   */
  async reconnect(): Promise<{ success: boolean; connected: boolean; message: string }> {
    const response = await fetch(`${API_URL}/api/lights/reconnect`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to reconnect');
    }
    return response.json();
  },
};
