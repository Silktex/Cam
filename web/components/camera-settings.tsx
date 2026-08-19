'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCameraSettings, setCameraSetting, getCameraStatus, type CameraSetting } from '@/lib/api';
import { Settings, RefreshCw, Loader2, Star, ChevronDown, ChevronUp, Aperture, Gauge, Focus, Palette, Image, Zap, RotateCcw, Eye } from 'lucide-react';
import { useState, useEffect, useMemo } from 'react';

// Recommended values for Sony A7R III lightbox photography (exact gphoto2 config names & values)
const RECOMMENDATIONS: Record<string, { value: string; reason: string }> = {
  // Exposure Triangle — dark room with LED lights, tripod-mounted, static subject
  'iso':                    { value: '400',                      reason: 'Moderate ISO — balanced noise/exposure for LED lighting in dark room' },
  'f-number':               { value: 'f/8',                      reason: 'Sharpest aperture for most lenses, good depth of field' },
  'shutterspeed':           { value: '1/4',                      reason: 'Slow shutter OK — tripod + static subject, lets in more LED light' },
  'exposurecompensation':   { value: '0',                        reason: 'Start neutral, adjust if still too dark/bright' },
  'expprogram':             { value: 'M',                        reason: 'Full manual control for consistent exposure across all captures' },
  // Focus
  'focusmode':              { value: 'Manual',                   reason: 'Subject is static, lock focus once' },
  'focusarea':              { value: 'Flexible Spot: M',         reason: 'Precise focus point for product detail' },
  // White Balance
  'whitebalance':           { value: 'Choose Color Temperature', reason: 'Fixed Kelvin ensures consistent color across all captures' },
  'colortemperature':       { value: '5500',                     reason: 'Daylight-neutral — adjust to match your LED color temp' },
  // Image Quality
  'imagequality':           { value: 'RAW',                      reason: 'Maximum data — recover exposure in post if needed' },
  'imagesize':              { value: 'Large',                    reason: 'Full 42.4MP resolution' },
  'aspectratio':            { value: '3:2',                      reason: 'Native sensor ratio, no crop' },
  // Drive & Capture
  'capturemode':            { value: 'Single Shot',              reason: 'One precise capture per trigger' },
  'capturetarget':          { value: 'sdram',                    reason: 'Faster transfer — image stays in memory, no SD card write delay' },
  // Metering
  'exposuremetermode':      { value: 'Multi',                    reason: 'Balanced exposure across entire frame' },
  // Flash
  'flashmode':              { value: 'Flash off',                reason: 'Using LED lights, no flash needed' },
  // Sensor
  'sensorcrop':             { value: 'Off',                      reason: 'Use full sensor area for maximum resolution' },
};

// Setting groups with icons
interface SettingGroup {
  label: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  borderColor: string;
  keywords: string[];
}

const SETTING_GROUPS: SettingGroup[] = [
  {
    label: 'Exposure Triangle',
    icon: <Aperture className="w-4 h-4" />,
    color: 'text-teal-700',
    bgColor: 'bg-teal-50',
    borderColor: 'border-teal-200',
    keywords: ['iso', 'f-number', 'shutterspeed', 'exposurecompensation', 'expprogram'],
  },
  {
    label: 'Focus',
    icon: <Focus className="w-4 h-4" />,
    color: 'text-slate-700',
    bgColor: 'bg-slate-50',
    borderColor: 'border-slate-200',
    keywords: ['focusmode', 'focusarea', 'manualfocusdrive'],
  },
  {
    label: 'White Balance & Color',
    icon: <Palette className="w-4 h-4" />,
    color: 'text-cyan-700',
    bgColor: 'bg-cyan-50',
    borderColor: 'border-cyan-200',
    keywords: ['whitebalance', 'colortemperature'],
  },
  {
    label: 'Image Quality',
    icon: <Image className="w-4 h-4" />,
    color: 'text-teal-700',
    bgColor: 'bg-teal-50',
    borderColor: 'border-teal-200',
    keywords: ['imagequality', 'imagesize', 'aspectratio'],
  },
  {
    label: 'Drive & Capture',
    icon: <Zap className="w-4 h-4" />,
    color: 'text-slate-700',
    bgColor: 'bg-slate-50',
    borderColor: 'border-slate-200',
    keywords: ['capturemode', 'capturetarget'],
  },
  {
    label: 'Metering & Flash',
    icon: <Gauge className="w-4 h-4" />,
    color: 'text-teal-700',
    bgColor: 'bg-teal-50',
    borderColor: 'border-teal-200',
    keywords: ['exposuremetermode', 'flashmode', 'sensorcrop'],
  },
];

function findRecommendation(name: string): { value: string; reason: string } | null {
  const lower = name.toLowerCase();
  // Exact match on gphoto2 config name
  if (RECOMMENDATIONS[lower]) return RECOMMENDATIONS[lower];
  return null;
}

function matchesGroup(setting: CameraSetting, group: SettingGroup): boolean {
  const lower = setting.name.toLowerCase();
  return group.keywords.some(kw => lower === kw);
}

export function CameraSettings() {
  const queryClient = useQueryClient();
  const [localSettings, setLocalSettings] = useState<Record<string, any>>({});
  const [isDirty, setIsDirty] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [applyingPreset, setApplyingPreset] = useState(false);

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

  useEffect(() => {
    if (settings && !isDirty) {
      const settingsMap: Record<string, any> = {};
      settings.forEach(s => { settingsMap[s.name] = s.value; });
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

  const toggleGroup = (label: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  // Group settings
  const groupedSettings = useMemo(() => {
    if (!settings) return [];

    return SETTING_GROUPS.map(group => {
      const matched = settings.filter(s => matchesGroup(s, group));
      return { group, settings: matched };
    }).filter(g => g.settings.length > 0);
  }, [settings]);

  // Ungrouped settings
  const ungroupedSettings = useMemo(() => {
    if (!settings) return [];
    const allGrouped = new Set(
      SETTING_GROUPS.flatMap(g =>
        (settings || []).filter(s => matchesGroup(s, g)).map(s => s.name)
      )
    );
    return settings.filter(s => !allGrouped.has(s.name));
  }, [settings]);

  const isConnected = status?.connected ?? false;

  // Apply all recommended settings
  const applyRecommended = async () => {
    if (!settings) return;
    setApplyingPreset(true);
    for (const s of settings) {
      const rec = findRecommendation(s.name);
      if (rec && !s.readonly) {
        // Check if the recommended value exists in choices
        if (s.choices) {
          const match = s.choices.find(c =>
            c.toLowerCase() === rec.value.toLowerCase() ||
            c.toLowerCase().includes(rec.value.toLowerCase())
          );
          if (match) {
            try {
              await setCameraSetting(s.name, match);
            } catch (e) { /* skip failures silently */ }
          }
        }
      }
    }
    setApplyingPreset(false);
    queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] });
  };

  // Count how many settings match recommended
  const matchCount = useMemo(() => {
    if (!settings) return { matching: 0, total: 0 };
    let matching = 0;
    let total = 0;
    settings.forEach(s => {
      const rec = findRecommendation(s.name);
      if (rec) {
        total++;
        const current = String(s.value).toLowerCase();
        if (
          current === rec.value.toLowerCase() ||
          current.includes(rec.value.toLowerCase())
        ) {
          matching++;
        }
      }
    });
    return { matching, total };
  }, [settings]);

  return (
    <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-slate-700" />
          <h2 className="text-lg font-semibold text-slate-800">Camera Settings</h2>
          {isConnected && settings && (
            <span className="text-xs text-slate-400 ml-1">({settings.length} total)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isConnected && (
            <button
              onClick={applyRecommended}
              disabled={applyingPreset}
              title="Apply all recommended lightbox settings"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-teal-50 text-teal-700 border border-teal-200 rounded-xl hover:bg-teal-100 disabled:opacity-50 transition-colors"
            >
              {applyingPreset ? <Loader2 className="w-3 h-3 animate-spin" /> : <Star className="w-3 h-3" />}
              Apply Recommended
            </button>
          )}
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['camera', 'settings'] })}
            className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
            title="Refresh settings"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Recommendation Score */}
      {isConnected && matchCount.total > 0 && (
        <div className="px-5 py-2.5 bg-teal-50/50 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-teal-600" />
            <span className="text-xs text-slate-600">
              Lightbox Preset: <strong className="text-teal-700">{matchCount.matching}/{matchCount.total}</strong> recommended settings applied
            </span>
          </div>
          <div className="w-24 h-1.5 bg-slate-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-teal-500 rounded-full transition-all"
              style={{ width: `${matchCount.total ? (matchCount.matching / matchCount.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* Body */}
      <div className="p-4">
        {!isConnected ? (
          <div className="text-sm text-slate-500 text-center py-8">
            Connect camera to view and adjust settings
          </div>
        ) : isLoading ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
            <span className="text-sm text-slate-400">Loading settings...</span>
          </div>
        ) : (
          <div className="space-y-4">
            {groupedSettings.map(({ group, settings: groupSettings }) => {
              const isCollapsed = collapsedGroups.has(group.label);
              return (
                <div key={group.label} className={`rounded-xl border ${group.borderColor} overflow-hidden`}>
                  {/* Group header */}
                  <button
                    onClick={() => toggleGroup(group.label)}
                    className={`w-full flex items-center justify-between px-4 py-2.5 ${group.bgColor} transition-colors hover:brightness-95`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={group.color}>{group.icon}</span>
                      <span className={`text-sm font-semibold ${group.color}`}>{group.label}</span>
                      <span className="text-xs text-slate-400">({groupSettings.length})</span>
                    </div>
                    {isCollapsed
                      ? <ChevronDown className="w-4 h-4 text-slate-400" />
                      : <ChevronUp className="w-4 h-4 text-slate-400" />
                    }
                  </button>

                  {/* Group settings */}
                  {!isCollapsed && (
                    <div className="divide-y divide-slate-100 px-4">
                      {groupSettings.map(setting => (
                        <SettingControl
                          key={setting.name}
                          setting={setting}
                          localValue={localSettings[setting.name]}
                          onChange={(v) => handleSettingChange(setting.name, v)}
                          onApply={(v) => handleApplySetting(setting.name, v)}
                          isUpdating={updateMutation.isPending}
                          recommendation={findRecommendation(setting.name)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Show All toggle */}
            {ungroupedSettings.length > 0 && (
              <div>
                <button
                  onClick={() => setShowAll(prev => !prev)}
                  className="w-full flex items-center justify-center gap-1.5 py-2 text-xs text-slate-500 hover:text-slate-700 border border-dashed border-slate-300 rounded-xl hover:bg-slate-50 transition-colors"
                >
                  {showAll
                    ? <><ChevronUp className="w-3 h-3" /> Hide {ungroupedSettings.length} other settings</>
                    : <><ChevronDown className="w-3 h-3" /> Show {ungroupedSettings.length} other settings</>
                  }
                </button>

                {showAll && (
                  <div className="mt-3 rounded-xl border border-slate-200 divide-y divide-slate-100 px-4">
                    {ungroupedSettings.map(setting => (
                      <SettingControl
                        key={setting.name}
                        setting={setting}
                        localValue={localSettings[setting.name]}
                        onChange={(v) => handleSettingChange(setting.name, v)}
                        onApply={(v) => handleApplySetting(setting.name, v)}
                        isUpdating={updateMutation.isPending}
                        recommendation={null}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Individual Setting Control

function SettingControl({
  setting,
  localValue,
  onChange,
  onApply,
  isUpdating,
  recommendation,
}: {
  setting: CameraSetting;
  localValue: any;
  onChange: (value: any) => void;
  onApply: (value: any) => void;
  isUpdating: boolean;
  recommendation: { value: string; reason: string } | null;
}) {
  const value = localValue ?? setting.value;
  const hasChanged = value !== setting.value;
  const isRecommended = recommendation != null;
  const matchesRec = isRecommended && (
    String(value).toLowerCase() === recommendation!.value.toLowerCase() ||
    String(value).toLowerCase().includes(recommendation!.value.toLowerCase())
  );

  const applyRecommended = () => {
    if (!recommendation || !setting.choices) return;
    const match = setting.choices.find(c =>
      c.toLowerCase() === recommendation.value.toLowerCase() ||
      c.toLowerCase().includes(recommendation.value.toLowerCase())
    );
    if (match) {
      onChange(match);
      onApply(match);
    }
  };

  // Readonly
  if (setting.readonly) {
    return (
      <div className="flex justify-between items-center py-3">
        <div>
          <span className="text-sm font-medium text-slate-700">{setting.label}</span>
          {isRecommended && (
            <RecommendedBadge rec={recommendation!} matches={matchesRec} />
          )}
        </div>
        <span className="text-sm text-slate-400 font-mono">{String(setting.value)}</span>
      </div>
    );
  }

  // Menu/Radio - dropdown
  if ((setting.type === 'menu' || setting.type === 'radio') && setting.choices) {
    return (
      <div className="py-3">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-sm font-medium text-slate-700">{setting.label}</label>
            {isRecommended && (
              <RecommendedBadge rec={recommendation!} matches={matchesRec} onApply={!matchesRec ? applyRecommended : undefined} />
            )}
          </div>
          {hasChanged && (
            <button
              onClick={() => onApply(value)}
              disabled={isUpdating}
              className="px-2.5 py-1 text-xs font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:bg-slate-300 transition-colors"
            >
              Apply
            </button>
          )}
        </div>
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full px-3 py-1.5 text-sm border rounded-xl focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 transition-colors
            ${matchesRec ? 'border-teal-300 bg-teal-50/50' : 'border-slate-200 bg-white'}`}
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
    // gphoto2's get_range() is a (min, max, step) tuple; normalize either
    // that or the legacy {min,max,step} shape.
    const [rangeMin, rangeMax, rangeStep] = Array.isArray(setting.range)
      ? setting.range
      : [setting.range.min, setting.range.max, setting.range.step];
    return (
      <div className="py-3">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-slate-700">{setting.label}</label>
            {isRecommended && (
              <RecommendedBadge rec={recommendation!} matches={matchesRec} />
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-slate-600">{value}</span>
            {hasChanged && (
              <button
                onClick={() => onApply(value)}
                disabled={isUpdating}
                className="px-2.5 py-1 text-xs font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:bg-slate-300 transition-colors"
              >
                Apply
              </button>
            )}
          </div>
        </div>
        <input
          type="range"
          min={rangeMin}
          max={rangeMax}
          step={rangeStep}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full"
        />
      </div>
    );
  }

  // Toggle
  if (setting.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">{setting.label}</span>
          {isRecommended && (
            <RecommendedBadge rec={recommendation!} matches={matchesRec} />
          )}
        </div>
        <button
          onClick={() => {
            const newValue = !value;
            onChange(newValue);
            onApply(newValue);
          }}
          disabled={isUpdating}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
            ${value ? 'bg-teal-500' : 'bg-slate-300'}
            ${isUpdating ? 'opacity-50' : ''}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform
            ${value ? 'translate-x-6' : 'translate-x-1'}`}
          />
        </button>
      </div>
    );
  }

  // Text - default
  return (
    <div className="py-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-slate-700">{setting.label}</label>
          {isRecommended && (
            <RecommendedBadge rec={recommendation!} matches={matchesRec} />
          )}
        </div>
        {hasChanged && (
          <button
            onClick={() => onApply(value)}
            disabled={isUpdating}
            className="px-2.5 py-1 text-xs font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:bg-slate-300 transition-colors"
          >
            Apply
          </button>
        )}
      </div>
      <input
        type="text"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-1.5 text-sm border border-slate-200 rounded-xl focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500"
      />
    </div>
  );
}

// Recommended Badge

function RecommendedBadge({
  rec,
  matches,
  onApply,
}: {
  rec: { value: string; reason: string };
  matches: boolean;
  onApply?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 group relative">
      {matches ? (
        <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-teal-100 text-teal-700">
          <Star className="w-2.5 h-2.5 fill-current" /> Recommended
        </span>
      ) : (
        <button
          onClick={(e) => { e.stopPropagation(); onApply?.(); }}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors cursor-pointer"
          title={`Set to ${rec.value}`}
        >
          <RotateCcw className="w-2.5 h-2.5" /> Set {rec.value}
        </button>
      )}
      {/* Tooltip */}
      <span className="invisible group-hover:visible absolute left-0 top-full mt-1 z-10 px-2.5 py-1.5 bg-slate-900 text-white text-[11px] rounded-lg shadow-lg whitespace-nowrap max-w-[250px]">
        {rec.reason}
      </span>
    </span>
  );
}
