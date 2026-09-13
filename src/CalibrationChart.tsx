import type { CalibrationFittedPoint } from './api';

interface CalibrationChartProps {
  points: CalibrationFittedPoint[];
  slope: number;
  zeroOffset: number;
  maxResidualIndex: number;
  tolerance: number;
}

const width = 660;
const height = 440;
const margin = { top: 28, right: 28, bottom: 56, left: 68 };
const plotWidth = width - margin.left - margin.right;
const plotHeight = height - margin.top - margin.bottom;

const formatTick = (value: number): string => String(Math.round(value * 100) / 100);

export default function CalibrationChart({
  points,
  slope,
  zeroOffset,
  maxResidualIndex,
  tolerance,
}: CalibrationChartProps) {
  const maxThickness = Math.max(...points.map((point) => point.thickness));
  const maxTime = Math.max(...points.map((point) => Math.max(point.travelTime, point.predictedTime)));
  const lineEnd = maxThickness * 1.05;
  const xMax = maxThickness * 1.08;
  const yMax = Math.max(maxTime, slope * lineEnd + zeroOffset) * 1.1;

  const x = (thickness: number) => margin.left + (thickness / xMax) * plotWidth;
  const y = (time: number) => margin.top + plotHeight - (time / yMax) * plotHeight;

  const xTicks = Array.from({ length: 6 }, (_, index) => (xMax / 5) * index);
  const yTicks = Array.from({ length: 6 }, (_, index) => (yMax / 5) * index);

  return (
    <div className="ring-card" data-testid="calibration-chart" aria-label="声程校准拟合图">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="cal-chart-title cal-chart-desc">
        <title id="cal-chart-title">实测测点与最小二乘拟合直线</title>
        <desc id="cal-chart-desc">
          横轴为参考试块厚度（毫米），纵轴为往返时间（微秒）。蓝色圆点为实测测点，青色直线为拟合声程，红色光晕标出最大绝对残差点。
        </desc>

        {xTicks.map((tick) => (
          <g key={`x-${tick}`} className="cal-grid">
            <line x1={x(tick)} y1={margin.top} x2={x(tick)} y2={y(0)} />
            <text x={x(tick)} y={y(0) + 20} textAnchor="middle">
              {formatTick(tick)}
            </text>
          </g>
        ))}
        {yTicks.map((tick) => (
          <g key={`y-${tick}`} className="cal-grid">
            <line x1={x(0)} y1={y(tick)} x2={width - margin.right} y2={y(tick)} />
            <text x={x(0) - 10} y={y(tick)} textAnchor="end" dominantBaseline="middle">
              {formatTick(tick)}
            </text>
          </g>
        ))}

        <line x1={x(0)} y1={y(0)} x2={width - margin.right} y2={y(0)} className="cal-axis" />
        <line x1={x(0)} y1={margin.top} x2={x(0)} y2={y(0)} className="cal-axis" />

        <text x={margin.left + plotWidth / 2} y={height - 12} textAnchor="middle" className="cal-axis-title">
          厚度 d（mm）
        </text>
        <text
          x={18}
          y={margin.top + plotHeight / 2}
          textAnchor="middle"
          className="cal-axis-title"
          transform={`rotate(-90 18 ${margin.top + plotHeight / 2})`}
        >
          往返时间 t（µs）
        </text>

        <line
          x1={x(0)}
          y1={y(zeroOffset)}
          x2={x(lineEnd)}
          y2={y(slope * lineEnd + zeroOffset)}
          className="cal-fit-line"
          data-testid="fitted-line"
        >
          <title>{`拟合直线 t = ${slope.toFixed(5)}·d + ${zeroOffset.toFixed(4)}`}</title>
        </line>

        {points.map((point, index) => (
          <line
            key={`residual-${index}`}
            x1={x(point.thickness)}
            y1={y(point.travelTime)}
            x2={x(point.thickness)}
            y2={y(point.predictedTime)}
            className={
              point.withinTolerance ? 'cal-residual-line' : 'cal-residual-line cal-residual-line--out'
            }
          />
        ))}

        {points.map((point, index) => {
          const isMax = index === maxResidualIndex;
          const className = [
            'cal-point',
            point.withinTolerance ? '' : 'cal-point--out',
            isMax ? 'cal-point--max' : '',
          ]
            .filter(Boolean)
            .join(' ');
          return (
            <g key={`point-${index}`}>
              {isMax && (
                <circle
                  cx={x(point.thickness)}
                  cy={y(point.travelTime)}
                  r="13"
                  className="cal-point-halo"
                />
              )}
              <circle
                cx={x(point.thickness)}
                cy={y(point.travelTime)}
                r="6"
                className={className}
                data-testid={isMax ? 'max-residual-point' : `chart-point-${index}`}
              >
                <title>
                  {`第 ${index + 1} 点：厚度 ${point.thickness} mm，实测 ${point.travelTime} µs，` +
                    `预测 ${point.predictedTime.toFixed(4)} µs，残差 ${point.residual.toFixed(4)} µs` +
                    `${Math.abs(point.residual) <= tolerance ? '（容差内）' : '（超差）'}`}
                </title>
              </circle>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
