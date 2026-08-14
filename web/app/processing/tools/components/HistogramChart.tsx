'use client';

interface HistogramData {
  r: number[];
  g: number[];
  b: number[];
  luminance?: number[];
}

interface HistogramChartProps {
  data: HistogramData;
  width?: number;
  height?: number;
  showChannels?: ('r' | 'g' | 'b' | 'luminance')[];
}

export default function HistogramChart({
  data,
  width = 256,
  height = 80,
  showChannels = ['r', 'g', 'b'],
}: HistogramChartProps) {
  const channelColors = {
    r: 'rgba(239, 68, 68, 0.6)',
    g: 'rgba(34, 197, 94, 0.6)',
    b: 'rgba(59, 130, 246, 0.6)',
    luminance: 'rgba(255, 255, 255, 0.5)',
  };

  // Normalize all channels to the same max
  const allValues = showChannels.flatMap((ch) => data[ch] || []);
  const maxVal = Math.max(...allValues, 1);

  const renderChannel = (channel: keyof HistogramData, color: string) => {
    const values = data[channel];
    if (!values || values.length === 0) return null;

    const points = values.map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - (v / maxVal) * height;
      return `${x},${y}`;
    });

    return (
      <polygon
        key={channel}
        points={`0,${height} ${points.join(' ')} ${width},${height}`}
        fill={color}
        stroke={color.replace(/[\d.]+\)$/, '0.8)')}
        strokeWidth={0.5}
      />
    );
  };

  return (
    <div className="bg-slate-900/50 rounded-lg p-2 border border-slate-700/30">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height: `${height}px`, maxHeight: '80px' }}
        preserveAspectRatio="none"
      >
        {showChannels.map((ch) => renderChannel(ch, channelColors[ch]))}
      </svg>
      <div className="flex items-center gap-3 mt-1 px-1">
        {showChannels.map((ch) => (
          <div key={ch} className="flex items-center gap-1">
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: channelColors[ch] }}
            />
            <span className="text-[10px] text-slate-500 uppercase">{ch}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
