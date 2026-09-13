import type { CorrectedPoint, ReadingInput, SegmentResult } from './api';

interface SamplingRingProps {
  samples: ReadingInput[];
  segments: SegmentResult[];
  selectedIndex: number | null;
  onSelectSegment: (index: number) => void;
  threshold: number | null;
  points?: CorrectedPoint[] | null;
  // Non-zero when every displayed angle is rotated by the field zero offset;
  // tooltips then expose the source (encoder) angle alongside it.
  angleOffset?: number;
  // Merged unreadable display angles from submitted occlusion intervals;
  // rendered with an independent hatch texture, never as defective points.
  occludedAngles?: number[];
}

const size = 640;
const center = size / 2;
const ringRadius = 220;
const outerRadius = 288;
const innerRadius = 152;
const zero = -Math.PI / 2;

const pointPosition = (angle: number, radius = ringRadius) => {
  const radians = zero + (angle * Math.PI) / 180;
  return {
    x: center + radius * Math.cos(radians),
    y: center + radius * Math.sin(radians),
  };
};

const segmentArcRadius = ringRadius - 31;
const occlusionArcRadius = ringRadius + 17;

const describeArc = (startAngle: number, span: number, radius: number): string => {
  if (span >= 360) {
    // Exactly one turn around the circle: a 180° arc from 0° to 180° followed
    // by the other 180° arc back to 0°. Using four >180° arcs would accumulate
    // more than 360° of sweep and draw the full-circle segment several times.
    const start = pointPosition(0, radius);
    const opposite = pointPosition(180, radius);
    return [
      `M ${start.x} ${start.y}`,
      `A ${radius} ${radius} 0 0 1 ${opposite.x} ${opposite.y}`,
      `A ${radius} ${radius} 0 0 1 ${start.x} ${start.y}`,
    ].join(' ');
  }

  const endAngle = (startAngle + span - 1) % 360;
  const start = pointPosition(startAngle, radius);
  const end = pointPosition(endAngle, radius);
  const largeArcFlag = span > 181 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArcFlag} 1 ${end.x} ${end.y}`;
};

const angleSet = (segment: SegmentResult): Set<number> => new Set(segment.angles);

export default function SamplingRing({
  samples,
  segments,
  selectedIndex,
  onSelectSegment,
  threshold,
  points = null,
  angleOffset = 0,
  occludedAngles = [],
}: SamplingRingProps) {
  const byAngle = new Map(samples.map((sample) => [sample.angle, sample.amplitude]));
  const pointByAngle = new Map((points ?? []).map((point) => [point.angle, point]));
  const defectiveAngles = new Set(segments.flatMap((segment) => segment.angles));
  const occluded = new Set(occludedAngles);
  const selected = selectedIndex === null ? null : segments[selectedIndex] ?? null;
  const selectedAngles = selected ? angleSet(selected) : new Set<number>();
  const ticks = Array.from({ length: 36 }, (_, index) => index * 10);

  // Maximal clockwise runs of occluded angles, drawn as one hatched arc per
  // run so the unreadable range reads as a single texture band.
  const occludedRuns: { start: number; span: number }[] = [];
  if (occluded.size === 360) {
    occludedRuns.push({ start: 0, span: 360 });
  } else if (occluded.size > 0) {
    for (const angle of occluded) {
      if (occluded.has((angle + 359) % 360)) continue;
      let span = 1;
      while (span < 360 && occluded.has((angle + span) % 360)) span += 1;
      occludedRuns.push({ start: angle, span });
    }
  }

  const sourceSuffix = (sourceAngle: number | undefined): string =>
    angleOffset !== 0 && sourceAngle !== undefined ? `（原始来源角 ${sourceAngle}°）` : '';

  const sampleTitle = (angle: number, defective: boolean): string => {
    const point = pointByAngle.get(angle);
    if (occluded.has(angle)) {
      return `展示角 ${angle}°，遮挡未判读（不参与区段计算）${sourceSuffix(point?.sourceAngle)}`;
    }
    const status = `${defective ? '，缺陷' : ''}${sourceSuffix(point?.sourceAngle)}`;
    if (point) {
      return (
        `展示角 ${angle}°，原幅值 ${point.amplitude.toFixed(3)} mm，` +
        `基线 ${point.baseline.toFixed(3)} mm，` +
        `校正幅值 ${point.correctedAmplitude.toFixed(3)} mm${status}`
      );
    }
    const amplitude = byAngle.get(angle) ?? 0;
    return `展示角 ${angle}°，幅值 ${amplitude.toFixed(3)} mm${status}`;
  };

  return (
    <div className="ring-card" aria-label="360 度采样环">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-labelledby="ring-title ring-desc">
        <title id="ring-title">360 条轮对超声采样构成的环形图</title>
        <desc id="ring-desc">
          灰色圆点表示非缺陷点，橙色点表示达到阈值的缺陷点，斜纹点表示遮挡未判读点。选中的连续区段以黄色弧和放大点突出。
        </desc>

        <defs>
          <pattern
            id="occlusion-hatch"
            width="5"
            height="5"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="5" height="5" fill="#e2e8f0" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="#64748b" strokeWidth="1.6" />
          </pattern>
        </defs>

        <circle cx={center} cy={center} r={outerRadius} className="ring-outline" />
        <circle cx={center} cy={center} r={innerRadius} className="ring-outline" />

        {ticks.map((angle) => {
          const outer = pointPosition(angle, outerRadius);
          const inner = pointPosition(angle, angle % 90 === 0 ? outerRadius - 18 : outerRadius - 9);
          const label = pointPosition(angle, outerRadius + 24);
          return (
            <g key={angle} className="tick-group">
              <line x1={outer.x} y1={outer.y} x2={inner.x} y2={inner.y} />
              {(angle % 30 === 0 || angle === 0) && (
                <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle">
                  {angle}°
                </text>
              )}
            </g>
          );
        })}

        {Array.from({ length: 360 }, (_, angle) => {
          const point = pointPosition(angle, ringRadius);
          const inSelected = selectedAngles.has(angle);
          const isOccluded = occluded.has(angle);
          const defective = !isOccluded && defectiveAngles.has(angle);
          return (
            <circle
              key={angle}
              cx={point.x}
              cy={point.y}
              r={inSelected ? 4 : defective ? 2.8 : isOccluded ? 2.4 : 1.55}
              className={[
                'sample-dot',
                isOccluded
                  ? 'sample-dot--occluded'
                  : defective
                    ? 'sample-dot--defect'
                    : 'sample-dot--normal',
                inSelected ? 'sample-dot--selected' : '',
              ].join(' ')}
            >
              <title>{sampleTitle(angle, defective)}</title>
            </circle>
          );
        })}

        {occludedRuns.map((run) => {
          const title = (
            <title>
              {run.span === 1
                ? `遮挡未判读：展示角 ${run.start}°`
                : `遮挡未判读：展示角 ${run.start}° 起顺时针 ${run.span} 点`}
            </title>
          );
          if (run.span === 1) {
            // A one-point occlusion collapses the arc path into its start
            // point, so draw a hatched round marker instead.
            const marker = pointPosition(run.start, occlusionArcRadius);
            return (
              <circle
                key={`occluded-${run.start}`}
                cx={marker.x}
                cy={marker.y}
                r="7"
                className="occlusion-arc occlusion-arc--point"
              >
                {title}
              </circle>
            );
          }
          return (
            <path
              key={`occluded-${run.start}-${run.span}`}
              d={describeArc(run.start, run.span, occlusionArcRadius)}
              className="occlusion-arc"
            >
              {title}
            </path>
          );
        })}

        {segments.map((segment, index) => {
          const selectedClass = index === selectedIndex ? 'segment-arc segment-arc--selected' : 'segment-arc';
          const title = (
            <title>
              {`区段 ${index + 1}：展示角 ${segment.startAngle}° 至 ${segment.endAngle}°，跨度 ${segment.span} 点`}
              {segment.sourceStartAngle !== undefined &&
                `（原始来源角 ${segment.sourceStartAngle}° 至 ${segment.sourceEndAngle}°）`}
            </title>
          );
          if (segment.span === 1) {
            // A one-point segment collapses the arc path into its start point
            // (zero-length SVG paths are not clickable), so draw a round
            // marker on the arc radius that stays selectable like any arc.
            const marker = pointPosition(segment.startAngle, segmentArcRadius);
            return (
              <circle
                key={`${segment.startAngle}-${segment.span}-${index}`}
                cx={marker.x}
                cy={marker.y}
                r="9"
                className={`${selectedClass} segment-arc--point`}
                onClick={() => onSelectSegment(index)}
              >
                {title}
              </circle>
            );
          }
          return (
            <path
              key={`${segment.startAngle}-${segment.span}-${index}`}
              d={describeArc(segment.startAngle, segment.span, segmentArcRadius)}
              className={selectedClass}
              onClick={() => onSelectSegment(index)}
            >
              {title}
            </path>
          );
        })}

        {selected &&
          selected.angles.map((angle, position) => {
            const point = pointPosition(angle, ringRadius);
            const sourceAngle = selected.sourceAngles?.[position];
            return (
              <circle key={`selected-${angle}`} cx={point.x} cy={point.y} r="7" className="selected-halo">
                <title>
                  {`已选区段包含展示角 ${angle}°`}
                  {sourceAngle !== undefined ? `（原始来源角 ${sourceAngle}°）` : ''}
                </title>
              </circle>
            );
          })}

        {selected &&
          (() => {
            const peak = pointPosition(selected.peakAngle, ringRadius + 36);
            return (
              <g className="peak-label">
                <line
                  x1={pointPosition(selected.peakAngle, ringRadius).x}
                  y1={pointPosition(selected.peakAngle, ringRadius).y}
                  x2={peak.x}
                  y2={peak.y}
                />
                <text x={peak.x} y={peak.y} textAnchor="middle" dominantBaseline="middle">
                  {`${points ? '校正峰值' : '峰值'} ${selected.peakAmplitude.toFixed(3)}@${selected.peakAngle}°`}
                  {selected.sourcePeakAngle !== undefined
                    ? `（来源 ${selected.sourcePeakAngle}°）`
                    : ''}
                </text>
              </g>
            );
          })()}

        <text x={center} y={center - 14} textAnchor="middle" className="center-title">
          {segments.length} 个连续区段
        </text>
        <text x={center} y={center + 18} textAnchor="middle" className="center-value">
          {threshold === null
            ? '等待阈值'
            : `阈值 ${threshold} mm${angleOffset !== 0 ? ` · 偏移 ${angleOffset > 0 ? `+${angleOffset}` : angleOffset}°` : ''}`}
        </text>
      </svg>
    </div>
  );
}
