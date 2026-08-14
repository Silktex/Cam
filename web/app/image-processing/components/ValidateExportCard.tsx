'use client';

import { useState } from 'react';
import { ShieldCheck, Save, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { SliderControl } from '@/app/processing/tools/components/ParameterCard';
import { pbrValidateCheck, pipelineSave } from '@/lib/api';
import PhaseCard from './PhaseCard';

interface ValidateExportCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  disabled?: boolean;
  onRevert?: () => void;
}

export default function ValidateExportCard({
  batchName,
  status,
  params,
  onParamsChange,
  disabled = false,
  onRevert,
}: ValidateExportCardProps) {
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    passed: boolean;
    message: string;
  } | null>(null);
  const [saveResult, setSaveResult] = useState<string | null>(null);

  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    try {
      const res = await pbrValidateCheck(batchName, {
        albedo_dark_threshold: params.albedo_dark_threshold || 30,
      });
      setValidationResult({
        passed: res.data.passed,
        message: res.data.passed
          ? 'All PBR maps within acceptable ranges'
          : `Issues found: ${res.data.stats?.dark_pixels_pct?.toFixed(1)}% dark pixels`,
      });
    } catch (e: any) {
      setValidationResult({
        passed: false,
        message: e.response?.data?.detail || 'Validation failed',
      });
    } finally {
      setValidating(false);
    }
  };

  const handleSaveAll = async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      const res = await pipelineSave(batchName);
      const count = res.data.saved_files?.length || 0;
      setSaveResult(`Saved ${count} files successfully`);
    } catch (e: any) {
      setSaveResult(`Save failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <PhaseCard
      phaseNumber={6}
      title="Validate & Export"
      status={status}
      disabled={disabled}
      defaultOpen={status !== 'completed'}
      onRevert={onRevert}
    >
      <SliderControl
        label="Dark Threshold"
        value={params.albedo_dark_threshold || 30}
        min={0}
        max={100}
        step={5}
        onChange={(v) => onParamsChange({ albedo_dark_threshold: v })}
      />

      <button
        onClick={handleValidate}
        disabled={validating}
        className="w-full flex items-center justify-center gap-2 px-3 py-2
          bg-slate-800 hover:bg-slate-700 disabled:opacity-50
          rounded-lg text-xs text-slate-300 transition-colors"
      >
        {validating ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <ShieldCheck className="w-3.5 h-3.5" />
        )}
        Run Validation
      </button>

      {validationResult && (
        <div
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${
            validationResult.passed
              ? 'bg-teal-900/30 text-teal-400'
              : 'bg-red-900/30 text-red-400'
          }`}
        >
          {validationResult.passed ? (
            <CheckCircle2 className="w-3.5 h-3.5" />
          ) : (
            <XCircle className="w-3.5 h-3.5" />
          )}
          {validationResult.message}
        </div>
      )}

      {/* Save All Maps */}
      <div className="pt-3 border-t border-slate-800/50">
        <button
          onClick={handleSaveAll}
          disabled={saving}
          className="w-full flex items-center justify-center gap-2 px-3 py-3
            bg-teal-600 hover:bg-teal-500 disabled:bg-slate-700
            rounded-lg text-sm font-medium text-white transition-colors"
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Saving Pipeline...
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              Save All Maps
            </>
          )}
        </button>

        {saveResult && (
          <p className="text-xs text-slate-400 mt-2 text-center">{saveResult}</p>
        )}
      </div>
    </PhaseCard>
  );
}
