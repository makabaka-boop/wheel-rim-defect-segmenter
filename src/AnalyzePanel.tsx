import { useMemo, useState } from 'react';
import {
  analyzeReadings,
  serializeSamples,
  wrapCompensatedSample,
  type CorrectedPoint,
  type FieldError,
  type ReadingInput,
  type SegmentResult,
} from './api';
import SamplingRing from './SamplingRing';

const initialPayload = () => {
  const { samples, baseline } = wrapCompensatedSample();
  return serializeSamples(samples, baseline);
};

function segmentText(segment: SegmentResult): string {
  return segment.startAngle === segment.endAngle
    ? `${segment.startAngle}°`
    : `${segment.startAngle}° → ${segment.endAngle}°（顺时针跨 0°）`;
}

export default function AnalyzePanel() {
  const [payload, setPayload] = useState(initialPayload);
  const [segments, setSegments] = useState<SegmentResult[]>([]);
  const [samples, setSamples] = useState<ReadingInput[]>(() => wrapCompensatedSample().samples);
  const [points, setPoints] = useState<CorrectedPoint[] | null>(null);
  const [baselineApplied, setBaselineApplied] = useState(false);
  const [threshold, setThreshold] = useState<number | null>(2.5);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const errorFields = useMemo(() => new Set(errors.map((error) => error.field)), [errors]);

  const clearResult = () => {
    setSegments([]);
    setSamples([]);
    setPoints(null);
    setBaselineApplied(false);
    setThreshold(null);
    setSelectedIndex(null);
    setErrors([]);
    setSubmitted(false);
  };

  const submit = async () => {
    setSubmitting(true);
    setErrors([]);
    setSegments([]);
    setSamples([]);
    setPoints(null);
    setBaselineApplied(false);
    setThreshold(null);
    setSelectedIndex(null);
    try {
      const result = await analyzeReadings(payload);
      const parsed = JSON.parse(payload) as { samples: ReadingInput[]; threshold: number };
      setSamples(parsed.samples);
      setSegments(result.segments);
      setPoints(result.points ?? null);
      setBaselineApplied(result.baselineApplied);
      setThreshold(result.threshold);
      setSubmitted(true);
      setSelectedIndex(result.segments.length === 0 ? null : 0);
    } catch (receivedErrors) {
      setErrors(
        Array.isArray(receivedErrors)
          ? (receivedErrors as FieldError[])
          : [{ field: 'request', message: '无法连接判读 API' }],
      );
      setSubmitted(false);
    } finally {
      setSubmitting(false);
    }
  };

  const loadWrapExample = () => {
    const { samples, baseline } = wrapCompensatedSample();
    setPayload(serializeSamples(samples, baseline));
    clearResult();
  };

  const selectedSegment = selectedIndex === null ? null : segments[selectedIndex] ?? null;

  return (
    <section className="workspace">
      <div className="input-column">
        <div className="panel">
          <div className="panel-heading">
            <h2>提交采样 JSON</h2>
            <button type="button" className="secondary-button" onClick={loadWrapExample}>
              载入跨零度样例
            </button>
          </div>
          <label className="field-label" htmlFor="payload">
            JSON 载荷（包含非负 threshold、360 条 samples，可选 360 条 baseline 基线）
          </label>
          <textarea
            id="payload"
            className={errorFields.has('request') || errorFields.has('$') ? 'invalid' : ''}
            value={payload}
            onChange={(event) => setPayload(event.target.value)}
            spellCheck={false}
            rows={22}
          />
          <div className="actions">
            <button type="button" className="primary-button" onClick={submit} disabled={submitting}>
              {submitting ? '判读中…' : '提交判读'}
            </button>
            <button type="button" className="secondary-button" onClick={clearResult}>
              清空结果
            </button>
          </div>
        </div>

        {errors.length > 0 && (
          <div className="panel error-panel" role="alert">
            <h2>输入未通过，本次结果已清空</h2>
            <ul>
              {errors.map((error, index) => (
                <li key={`${error.field}-${index}`}>
                  <code>{error.field}</code>
                  <span>{error.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="panel results-panel">
          <h2>连续区段结果</h2>
          {!submitted ? (
            <p className="muted">提交合法数据后显示计算结果。每次输入失败都会清空现有结果和图形高亮。</p>
          ) : segments.length === 0 ? (
            <p className="muted">本次没有达到阈值的缺陷点。</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>区段</th>
                    <th>起点</th>
                    <th>终点</th>
                    <th>跨度（采样点数）</th>
                    <th>峰值角</th>
                    <th>{baselineApplied ? '校正峰值（mm）' : '峰值（mm）'}</th>
                  </tr>
                </thead>
                <tbody>
                  {segments.map((segment, index) => (
                    <tr
                      key={`${segment.startAngle}-${segment.endAngle}`}
                      className={index === selectedIndex ? 'selected-row' : ''}
                      onClick={() => setSelectedIndex(index)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          setSelectedIndex(index);
                        }
                      }}
                      tabIndex={0}
                      aria-selected={index === selectedIndex}
                    >
                      <td>#{index + 1}</td>
                      <td>{segment.startAngle}°</td>
                      <td>{segment.endAngle}°</td>
                      <td>{segment.span}</td>
                      <td>{segment.peakAngle}°</td>
                      <td>{segment.peakAmplitude.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="table-note">
                {segments.length === 1 && segments[0].startAngle > segments[0].endAngle
                  ? `唯一区段为 ${segmentText(segments[0])}，未在零度拆成两段。`
                  : '点击任意结果行或环形弧，可突出该段对应的采样角点。'}
              </p>
              {selectedSegment && baselineApplied && (
                <p className="peak-detail" data-testid="peak-detail">
                  选中区段峰值角 {selectedSegment.peakAngle}°：原幅值{' '}
                  {(selectedSegment.peakRawAmplitude ?? 0).toFixed(3)} mm，基线{' '}
                  {(selectedSegment.peakBaseline ?? 0).toFixed(3)} mm，校正幅值{' '}
                  {selectedSegment.peakAmplitude.toFixed(3)} mm
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="visual-column">
        <SamplingRing
          samples={samples}
          segments={segments}
          selectedIndex={selectedIndex}
          onSelectSegment={setSelectedIndex}
          threshold={threshold}
          points={points}
        />
        <div className="legend panel">
          <span><i className="legend-normal" />非缺陷采样</span>
          <span><i className="legend-defect" />缺陷采样</span>
          <span><i className="legend-selected" />当前选中区段</span>
        </div>
      </div>
    </section>
  );
}
