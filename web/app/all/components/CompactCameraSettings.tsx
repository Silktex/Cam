'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getCameraSettings,
  setCameraSetting,
  getCameraStatus,
  type CameraSetting,
} from '@/lib/api';
import { Settings, RefreshCw, Loader2 } from 'lucide-react';
import { useState, useEffect, useMemo } from 'react';

// Primary settings to show (by gphoto2 config name)
const PRIMARY_SETTINGS = [
  'iso',
  'shutterspeed',
  'f-number',
  'whitebalance',
];

const SECONDARY_SETTINGS = [
  'exposurecompensation',
  'focusmode',
  'capturemode',
  'exposuremetermode',
  'imagequality',
];

export default function CompactCameraSettings() {
  const queryClient = useQueryClient();
  const [showSecondary, setShowSecondary] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['camera', 'status'],
    queryFn: () => getCameraStatus().then((res) => res.data),
    refetchInterval: 10000,
  });

  const { data: settings, isLoading } = useQuery({
    queryKey: ['camera', 'settings'],
    queryFn: () =>
      getCameraSettings().then((res) => res.data as CameraSetting[]),
    enabled: status?.connected ?? false,
    refetchInterval: 30000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ name, value }: { name: string; value: any }) =>
      setCameraSetting(name, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] });
    },
  });

  const isConnected = status?.connected ?? false;

  const findSetting = (name: string): CameraSetting | undefined => {
    return settings?.find(
      (s) => s.name.toLowerCase() === name.toLowerCase()
    );
  };

  const primarySettings = useMemo(
    () =>
      PRIMARY_SETTINGS.map((name) => findSetting(name)).filter(
        Boolean
      ) as CameraSetting[],
    [settings]
  );

  const secondarySettings = useMemo(
    () =>
      SECONDARY_SETTINGS.map((name) => findSetting(name)).filter(
        Boolean
      ) as CameraSetting[],
    [settings]
  );

  const handleChange = (name: string, value: string) => {
    updateMutation.mutate({ name, value });
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-teal-400" />
          <h2 className="text-base font-semibold text-white">
            Camera Settings
          </h2>
          {settings && (
            <span className="text-xs text-slate-500">
              ({settings.length} total)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {updateMutation.isPending && (
            <Loader2 className="w-4 h-4 animate-spin text-teal-400" />
          )}
          <button
            onClick={() =>
              queryClient.invalidateQueries({
                queryKey: ['camera', 'settings'],
              })
            }
            className="p-1.5 text-slate-400 hover:text-slate-200 rounded-lg hover:bg-slate-800 transition-colors"
            title="Refresh settings"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {!isConnected ? (
        <div className="text-sm text-slate-500 text-center py-6">
          Connect camera to view settings
        </div>
      ) : isLoading ? (
        <div className="flex items-center justify-center py-6 gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
          <span className="text-sm text-slate-400">Loading...</span>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Primary row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {primarySettings.map((setting) => (
              <SettingDropdown
                key={setting.name}
                setting={setting}
                onChange={handleChange}
              />
            ))}
          </div>

          {/* Toggle secondary */}
          <button
            onClick={() => setShowSecondary(!showSecondary)}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            {showSecondary
              ? 'Hide additional settings'
              : 'Show more settings...'}
          </button>

          {/* Secondary row */}
          {showSecondary && (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {secondarySettings.map((setting) => (
                <SettingDropdown
                  key={setting.name}
                  setting={setting}
                  onChange={handleChange}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SettingDropdown({
  setting,
  onChange,
}: {
  setting: CameraSetting;
  onChange: (name: string, value: string) => void;
}) {
  const [localValue, setLocalValue] = useState(String(setting.value));

  // Sync when server value changes
  useEffect(() => {
    setLocalValue(String(setting.value));
  }, [setting.value]);

  const handleChange = (newValue: string) => {
    setLocalValue(newValue);
    onChange(setting.name, newValue);
  };

  if (setting.readonly) {
    return (
      <div>
        <label className="block text-xs text-slate-400 mb-1 truncate">
          {setting.label}
        </label>
        <div className="px-3 py-1.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-400 truncate">
          {String(setting.value)}
        </div>
      </div>
    );
  }

  if (setting.choices && setting.choices.length > 0) {
    return (
      <div>
        <label className="block text-xs text-slate-400 mb-1 truncate">
          {setting.label}
        </label>
        <select
          value={localValue}
          onChange={(e) => handleChange(e.target.value)}
          className="w-full px-2 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none appearance-none cursor-pointer"
        >
          {setting.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1 truncate">
        {setting.label}
      </label>
      <input
        type="text"
        value={localValue}
        onChange={(e) => setLocalValue(e.target.value)}
        onBlur={() => onChange(setting.name, localValue)}
        className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white focus:border-teal-500 focus:ring-1 focus:ring-teal-500 focus:outline-none"
      />
    </div>
  );
}
