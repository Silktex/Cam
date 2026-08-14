'use client';

import { useState } from 'react';
import { Grid3x3, Eye, Loader2 } from 'lucide-react';
import {
  SliderControl,
  ToggleControl,
  SelectControl,
} from '@/app/processing/tools/components/ParameterCard';
import { seamlessPreview, getFullUrl } from '@/lib/api';
import PhaseCard from './PhaseCard';

interface SeamlessTilingCardProps {
  batchName: string;
  status: string;
  params: Record<string, any>;
  onParamsChange: (params: Record<string, any>) => void;
  onPreview: () => void;
  disabled?: boolean;
  onRevert?: () => void;
}

export default function SeamlessTilingCard({
  batchName,
  status,
  params,
  onParamsChange,
  onPreview,
  disabled = false,
  onRevert,
}: SeamlessTilingCardProps) {
  const seamless = params.seamless || {};
  const tiling = params.tiling || {};
  const [tileCheck, setTileCheck] = useState(params.tile_check || 4);
  const [tilePreviewUrl, setTilePreviewUrl] = useState<string | null>(null);
  const [checkingTile, setCheckingTile] = useState(false);

  const handleTileCheck = async () => {
    setCheckingTile(true);
    try {
      const res = await seamlessPreview(batchName, {
        method: seamless.method || 'overlay',
        blend_width: seamless.blend_width || 64,
        tile_count: tileCheck,
      });
      if (res.data.tiled_url) {
        setTilePreviewUrl(res.data.tiled_url);
      }
    } catch {
      // ignore
    } finally {
      setCheckingTile(false);
    }
  };

  return (
    <PhaseCard
      phaseNumber={5}
      title="Seamless & Tiling"
      status={status}
      disabled={disabled}
      defaultOpen={status !== 'completed'}
      onRevert={onRevert}
    >
      {/* Seamless */}
      <SelectControl
        label="Seamless Method"
        value={seamless.method || 'overlay'}
        options={[
          { value: 'overlay', label: 'Overlay Blend' },
          { value: 'mirror', label: 'Mirror Fold' },
          { value: 'poisson', label: 'Poisson (Gradient)' },
        ]}
        onChange={(v) =>
          onParamsChange({ seamless: { ...seamless, method: v } })
        }
      />

      <SliderControl
        label="Blend Width"
        value={seamless.blend_width || 64}
        min={8}
        max={256}
        step={8}
        unit="px"
        onChange={(v) => {
          onParamsChange({ seamless: { ...seamless, blend_width: v } });
          onPreview();
        }}
      />

      <ToggleControl
        label="Spots Removal"
        value={seamless.spots_removal || false}
        onChange={(v) =>
          onParamsChange({ seamless: { ...seamless, spots_removal: v } })
        }
      />

      {/* Tile Check */}
      <div className="pt-2 border-t border-slate-800/50">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">Tile Check</label>
          <input
            type="number"
            min={1}
            max={8}
            value={tileCheck}
            onChange={(e) => setTileCheck(parseInt(e.target.value) || 4)}
            className="w-14 bg-slate-700 border border-slate-600 rounded px-2 py-1
              text-xs text-slate-200 text-center"
          />
          <span className="text-xs text-slate-500">x{tileCheck}</span>
          <button
            onClick={handleTileCheck}
            disabled={checkingTile}
            className="flex items-center gap-1 px-2 py-1 bg-slate-800 hover:bg-slate-700
              rounded text-xs text-slate-300 transition-colors ml-auto"
          >
            {checkingTile ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Eye className="w-3 h-3" />
            )}
            Check
          </button>
        </div>

        {tilePreviewUrl && (
          <div className="mt-2 rounded-lg overflow-hidden border border-slate-700">
            <img
              src={getFullUrl(tilePreviewUrl)}
              alt={`${tileCheck}x${tileCheck} tile check`}
              className="w-full"
            />
          </div>
        )}
      </div>

      {/* Tiling Export */}
      <div className="pt-2 border-t border-slate-800/50">
        <div className="flex items-center gap-2 mb-2">
          <Grid3x3 className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs text-slate-400">Tiling Export</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SliderControl
            label="Tile X"
            value={tiling.tile_x || 2}
            min={1}
            max={8}
            step={1}
            onChange={(v) =>
              onParamsChange({ tiling: { ...tiling, tile_x: v } })
            }
          />
          <SliderControl
            label="Tile Y"
            value={tiling.tile_y || 2}
            min={1}
            max={8}
            step={1}
            onChange={(v) =>
              onParamsChange({ tiling: { ...tiling, tile_y: v } })
            }
          />
        </div>
        <ToggleControl
          label="Half Drop"
          value={tiling.half_drop || false}
          onChange={(v) =>
            onParamsChange({ tiling: { ...tiling, half_drop: v } })
          }
        />
      </div>
    </PhaseCard>
  );
}
