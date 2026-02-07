'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCameraSettings, setCameraSetting, getCameraStatus, type CameraSetting } from '@/lib/api';
import { Settings, RefreshCw, Loader2 } from 'lucide-react';
import { useState, useEffect } from 'react';

export function CameraSettings() {
  const queryClient = useQueryClient();
  const [localSettings, setLocalSettings] = useState<Record<string, any>>({});
  const [isDirty, setIsDirty] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then(res => res.data),
    refetchInterval: 10000,
  });

  const { data: settings, isLoading } = useQuery({
    queryKey: ['camera', 'settings'],
    queryFn: () => getCameraSettings().then(res => res.data as CameraSetting[]),
    enabled: status?.connected ?? false,
    refetchInterval: 30000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: any }) => setCameraSetting(name, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] });
    },
  });

  // Sync local state with server settings
  useEffect(() => {
    if (settings && !isDirty) {
      const settingsMap: Record<string, any> = {};
      settings.forEach(s => {
        settingsMap[s.name] = s.value;
      });
      setLocalSettings(settingsMap);
    }
  }, [settings, isDirty]);

  const handleSettingChange = (name: string, value: any) => {
    setLocalSettings(prev => ({ ...prev, [name]: value }));
    setIsDirty(true);
  };

  const handleApplySetting = (name: string, value: any) => {
    updateMutation.mutate({ name, value });
    setIsDirty(false);
  };

  const isConnected = status?.connected ?? false;

  // Filter to show only commonly used settings
  const importantSettings = ['iso', 'shutterspeed', 'aperture', 'whitebalance', 'focusmode', 'imageformat'];
  const filteredSettings = settings?.filter(s => 
    importantSettings.some(important => s.name.toLowerCase().includes(important))
  ) || [];

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-gray-700" />
          <h2 className="text-lg font-semibold text-gray-900">Camera Settings</h2>
        </div>
        <button
          onClick={() => queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] })}
          className="p-1 text-gray-500 hover:text-gray-700"
          title="Refresh settings"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {!isConnected ? (
        <div className="text-sm text-gray-500 text-center py-4">
          Connect camera to view settings
        </div>
      ) : isLoading ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
        </div>
      ) : (
        <div className="space-y-3">
          {filteredSettings.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-4">
              {status?.live_view_active 
                ? "Stop live view to access settings"
                : "No settings available"}
            </div>
          ) : (
            filteredSettings.map(setting => (
              <SettingControl
                key={setting.name}
                setting={setting}
                localValue={localSettings[setting.name]}
                onChange={(value) => handleSettingChange(setting.name, value)}
                onApply={(value) => handleApplySetting(setting.name, value)}
                isUpdating={updateMutation.isPending}
              />
            ))
          )}
        </div>
      )}

      {/* Show all settings toggle - future enhancement */}
      {settings && settings.length > filteredSettings.length && (
        <div className="mt-4 pt-3 border-t text-xs text-gray-500 text-center">
          Showing {filteredSettings.length} of {settings.length} settings
        </div>
      )}
    </div>
  );
}

function SettingControl({
  setting,
  localValue,
  onChange,
  onApply,
  isUpdating,
}: {
  setting: CameraSetting;
  localValue: any;
  onChange: (value: any) => void;
  onApply: (value: any) => void;
  isUpdating: boolean;
}) {
  const value = localValue ?? setting.value;
  const hasChanged = value !== setting.value;

  if (setting.readonly) {
    return (
      <div className="flex justify-between items-center py-2 border-b border-gray-100">
        <span className="text-sm font-medium text-gray-700">{setting.label}</span>
        <span className="text-sm text-gray-500">{String(setting.value)}</span>
      </div>
    );
  }

  // Menu/Radio - dropdown
  if ((setting.type === 'menu' || setting.type === 'radio') && setting.choices) {
    return (
      <div className="py-2 border-b border-gray-100">
        <div className="flex justify-between items-center mb-1">
          <label className="text-sm font-medium text-gray-700">{setting.label}</label>
          {hasChanged && (
            <button
              onClick={() => onApply(value)}
              disabled={isUpdating}
              className="px-2 py-0.5 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300"
            >
              Apply
            </button>
          )}
        </div>
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-2 py-1 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-blue-500"
        >
          {setting.choices.map(choice => (
            <option key={choice} value={choice}>{choice}</option>
          ))}
        </select>
      </div>
    );
  }

  // Range - slider
  if (setting.type === 'range' && setting.range) {
    return (
      <div className="py-2 border-b border-gray-100">
        <div className="flex justify-between items-center mb-1">
          <label className="text-sm font-medium text-gray-700">{setting.label}</label>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">{value}</span>
            {hasChanged && (
              <button
                onClick={() => onApply(value)}
                disabled={isUpdating}
                className="px-2 py-0.5 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300"
              >
                Apply
              </button>
            )}
          </div>
        </div>
        <input
          type="range"
          min={setting.range.min}
          max={setting.range.max}
          step={setting.range.step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
        />
      </div>
    );
  }

  // Toggle
  if (setting.type === 'toggle') {
    return (
      <div className="flex justify-between items-center py-2 border-b border-gray-100">
        <span className="text-sm font-medium text-gray-700">{setting.label}</span>
        <button
          onClick={() => {
            const newValue = !value;
            onChange(newValue);
            onApply(newValue);
          }}
          disabled={isUpdating}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            value ? 'bg-blue-500' : 'bg-gray-300'
          } ${isUpdating ? 'opacity-50' : ''}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform ${
              value ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
      </div>
    );
  }

  // Text - default
  return (
    <div className="py-2 border-b border-gray-100">
      <div className="flex justify-between items-center mb-1">
        <label className="text-sm font-medium text-gray-700">{setting.label}</label>
        {hasChanged && (
          <button
            onClick={() => onApply(value)}
            disabled={isUpdating}
            className="px-2 py-0.5 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-300"
          >
            Apply
          </button>
        )}
      </div>
      <input
        type="text"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1 text-sm border border-gray-300 rounded focus:ring-1 focus:ring-blue-500"
      />
    </div>
  );
}
