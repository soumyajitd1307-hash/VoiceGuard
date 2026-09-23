import React from 'react';
import { getRiskTheme } from '../../utils/risk';

interface DataPoint {
  timestamp: number;
  risk: number;
  syntheticProbability?: number;
}

interface RiskChartProps {
  data: DataPoint[];
  height?: number;
  width?: string | number;
  showThresholds?: boolean;
  showLabels?: boolean;
}

export const RiskChart: React.FC<RiskChartProps> = ({
  data = [],
  height = 160,
  width = '100%',
  showThresholds = true,
  showLabels = true
}) => {
  // Ensure we have at least 2 points to draw
  const safeData = data.length > 0 ? data : [{ timestamp: 0, risk: 18 }];
  const points = safeData.length === 1 ? [{ timestamp: 0, risk: safeData[0].risk }, { timestamp: 1, risk: safeData[0].risk }] : safeData;

  const maxTime = Math.max(20, Math.max(...points.map(p => p.timestamp)));
  const minTime = 0;
  const maxRisk = 100;

  const padding = { top: 12, right: 16, bottom: 24, left: 32 };
  const viewBoxWidth = 500;
  const viewBoxHeight = height;

  const chartWidth = viewBoxWidth - padding.left - padding.right;
  const chartHeight = viewBoxHeight - padding.top - padding.bottom;

  // Convert data points to SVG coordinates
  const getX = (t: number) => padding.left + ((t - minTime) / (maxTime - minTime || 1)) * chartWidth;
  const getY = (r: number) => padding.top + chartHeight - (r / maxRisk) * chartHeight;

  // Generate SVG path for the risk curve
  const pathD = points.reduce((acc, p, index) => {
    const x = getX(p.timestamp);
    const y = getY(p.risk);
    return index === 0 ? `M ${x} ${y}` : `${acc} L ${x} ${y}`;
  }, '');

  // Generate area fill path
  const lastPoint = points[points.length - 1];
  const firstPoint = points[0];
  const areaD = `${pathD} L ${getX(lastPoint.timestamp)} ${padding.top + chartHeight} L ${getX(firstPoint.timestamp)} ${padding.top + chartHeight} Z`;

  const latestRisk = points[points.length - 1]?.risk || 0;
  const currentTheme = getRiskTheme(latestRisk);

  return (
    <div style={{ width, position: 'relative' }}>
      <svg
        viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        <defs>
          <linearGradient id="riskAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={currentTheme.primary} stopOpacity="0.45" />
            <stop offset="100%" stopColor={currentTheme.primary} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {[0, 25, 50, 75, 100].map(val => {
          const y = getY(val);
          return (
            <g key={val}>
              <line
                x1={padding.left}
                y1={y}
                x2={viewBoxWidth - padding.right}
                y2={y}
                stroke="rgba(255, 255, 255, 0.06)"
                strokeDasharray="3 3"
              />
              {showLabels && (
                <text
                  x={padding.left - 6}
                  y={y + 3}
                  textAnchor="end"
                  fill="var(--text-dim)"
                  fontSize="9"
                  fontFamily="var(--font-mono)"
                >
                  {val}
                </text>
              )}
            </g>
          );
        })}

        {/* Threshold lines: 40 (Medium) and 70 (High) */}
        {showThresholds && (
          <>
            <line
              x1={padding.left}
              y1={getY(40)}
              x2={viewBoxWidth - padding.right}
              y2={getY(40)}
              stroke="rgba(245, 158, 11, 0.35)"
              strokeDasharray="2 4"
            />
            <line
              x1={padding.left}
              y1={getY(70)}
              x2={viewBoxWidth - padding.right}
              y2={getY(70)}
              stroke="rgba(239, 68, 68, 0.5)"
              strokeDasharray="4 4"
            />
            <text
              x={viewBoxWidth - padding.right - 2}
              y={getY(70) - 3}
              textAnchor="end"
              fill="#ef4444"
              fontSize="8"
              fontWeight="700"
              fontFamily="var(--font-mono)"
            >
              CRITICAL 70
            </text>
          </>
        )}

        {/* Area fill under curve */}
        <path d={areaD} fill="url(#riskAreaGrad)" />

        {/* Risk curve line */}
        <path
          d={pathD}
          fill="none"
          stroke={currentTheme.primary}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            filter: `drop-shadow(0 0 6px ${currentTheme.primary})`,
            transition: 'all 0.3s ease'
          }}
        />

        {/* Data points */}
        {points.map((p, idx) => {
          const isLatest = idx === points.length - 1;
          const pTheme = getRiskTheme(p.risk);
          return (
            <circle
              key={idx}
              cx={getX(p.timestamp)}
              cy={getY(p.risk)}
              r={isLatest ? 5 : 2.5}
              fill={pTheme.primary}
              stroke="#080c14"
              strokeWidth={isLatest ? 2 : 1}
              style={{
                filter: isLatest ? `drop-shadow(0 0 8px ${pTheme.primary})` : 'none'
              }}
            />
          );
        })}

        {/* X axis labels */}
        {showLabels && (
          <g>
            <text
              x={padding.left}
              y={viewBoxHeight - 6}
              textAnchor="start"
              fill="var(--text-dim)"
              fontSize="9"
              fontFamily="var(--font-mono)"
            >
              00:00
            </text>
            <text
              x={getX(maxTime)}
              y={viewBoxHeight - 6}
              textAnchor="end"
              fill="var(--text-dim)"
              fontSize="9"
              fontFamily="var(--font-mono)"
            >
              +{maxTime}s
            </text>
          </g>
        )}
      </svg>
    </div>
  );
};
