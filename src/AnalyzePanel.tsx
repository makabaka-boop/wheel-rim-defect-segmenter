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

// Client-side guard matching the API contract so editing the offset hides the
// previous result immediately and the error is pinned to the field.
const OFFSET_PATTERN = /^-?\d+$/;

const MAX_OCCLUSIONS = 8;

interface OcclusionRow {
  id: number;
  start: string;
  end: string;
}

let nextOcclusionRowId = 1;

function segmentText(segment: SegmentResult): string {
  return segment.startAngle === segment.endAngle
    ? `${segment.startAngle}°`
    : `${segment.startAngle}° → ${segment.endAngle}°（顺时针跨 0°）`;
}

export default function AnalyzePanel() {
  const [payload, setPayload] = useState(initialPayload);
  const [angleOffset, setAngleOffset] = useState('');
  const [occlusionRows, setOcclusionRows] = useState<OcclusionRow[]>([]);
  const [occludedAngles, setOccludedAngles] = useState<number[]>([]);
  const [segments, setSegments] = useState<SegmentResult[]>([]);
  const [samples, setSamples] = useState<ReadingInput[]>(() => wrapCompensatedSample().samples);
  const [points, setPoints] = useState<CorrectedPoint[] | null>(null);
  const [baselineApplied, setBaselineApplied] = useState(false);
  const [appliedOffset, setAppliedOffset] = useState(0);
  const [threshold, setThreshold] = useState<number | null>(2.5);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const errorFields = useMemo(() => new Set(errors.map((error) => error.field)), [errors]);
  const offsetInvalid = errorFields.has('angleOffset');

  // Editing the payload or the offset makes the previous judgment stale: its
  // angles no longer match the inputs. Results and highlight stay hidden until
  // a successful resubmission; the raw JSON and samples themselves are left
  // untouched.
  const hideStaleResult = () => {
    setSegments([]);
    setPoints(null);
    setBaselineApplied(false);
    setThreshold(null);
    setSelectedIndex(null);
    setErrors([]);
    setSubmitted(false);
    setAppliedOffset(0);
    setOccludedAngles([]);
  };

  const clearResult = () => {
    hideStaleResult();
    setSamples([]);
  };

  const submit = async () => {
    setSubmitting(true);
    setErrors([]);
    setSegments([]);
    setPoints(null);
    setBaselineApplied(false);
    setThreshold(null);
    setSelectedIndex(null);
    setSubmitted(false);
    setAppliedOffset(0);
    setOccludedAngles([]);

    let parsed: { samples?: ReadingInput[]; angleOffset?: number };
    try {
      parsed = JSON.parse(payload);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrors([{ field: 'request', message: `JSON 格式非法：${message}` }]);
      setSubmitting(false);
      setSamples([]);
      return;
    }

    const offsetText = angleOffset.trim();
    let submittedOffset = 0;
    if (offsetText !== '') {
      if (!OFFSET_PATTERN.test(offsetText)) {
        setErrors([{ field: 'angleOffset', message: '角度偏移必须是整数' }]);
        setSubmitting(false);
        return;
      }
      submittedOffset = Number(offsetText);
      if (!Number.isSafeInteger(submittedOffset) || submittedOffset < -359 || submittedOffset > 359) {
        setErrors([{ field: 'angleOffset', message: '角度偏移必须在 -359 至 359 之间' }]);
        setSubmitting(false);
        return;
      }
    }

    // Occlusion rows are validated against the same contract as the API so a
    // bad endpoint is pinned to its own field while the typed values stay in
    // place for correction. Row index matches the submitted interval index.
    const occlusionErrors: FieldError[] = [];
    const intervals: { start: number; end: number }[] = [];
    if (occlusionRows.length > MAX_OCCLUSIONS) {
      occlusionErrors.push({
        field: 'occlusions',
        message: `occlusions 至多包含 ${MAX_OCCLUSIONS} 个遮挡区间，当前为 ${occlusionRows.length} 个`,
      });
    }
    occlusionRows.forEach((row, index) => {
      const endpoints: { key: 'start' | 'end'; text: string }[] = [
        { key: 'start', text: row.start.trim() },
        { key: 'end', text: row.end.trim() },
      ];
      const parsedEndpoints: Partial<Record<'start' | 'end', number>> = {};
      for (const { key, text } of endpoints) {
        if (!OFFSET_PATTERN.test(text)) {
          occlusionErrors.push({
            field: `occlusions[${index}].${key}`,
            message: `${key} 必须是整数`,
          });
          continue;
        }
        const value = Number(text);
        if (!Number.isSafeInteger(value) || value < 0 || value > 359) {
          occlusionErrors.push({
            field: `occlusions[${index}].${key}`,
            message: `${key} 必须在 0 至 359 之间`,
          });
          continue;
        }
        parsedEndpoints[key] = value;
      }
      if (parsedEndpoints.start !== undefined && parsedEndpoints.end !== undefined) {
        intervals.push({ start: parsedEndpoints.start, end: parsedEndpoints.end });
      }
    });
    if (occlusionErrors.length > 0) {
      setErrors(occlusionErrors);
      setSubmitting(false);
      return;
    }

    try {
      // Omit the optional fields entirely when left blank so legacy payloads
      // stay byte-for-byte compatible; the baseline keeps pairing against
      // source angles server-side and occlusions apply in display space.
      const requestPayload =
        offsetText === '' && intervals.length === 0
          ? payload
          : JSON.stringify({
              ...parsed,
              ...(offsetText === '' ? {} : { angleOffset: submittedOffset }),
              ...(intervals.length === 0 ? {} : { occlusions: intervals }),
            });
      const result = await analyzeReadings(requestPayload);
      // The ring places dots by the response's display coordinates, so rotate
      // the raw sample ring in lockstep with the offset the server actually
      // applied and echoed back: the offset-box value when set, otherwise the
      // payload's own angleOffset. Baseline pairing itself stayed on source
      // angles server-side.
      const effectiveOffset = result.angleOffset ?? 0;
      setSamples(
        (parsed.samples ?? []).map((sample) => ({
          ...sample,
          angle: (((sample.angle + effectiveOffset) % 360) + 360) % 360,
        })),
      );
      setSegments(result.segments);
      setPoints(result.points ?? null);
      setBaselineApplied(result.baselineApplied);
      setThreshold(result.threshold);
      setAppliedOffset(result.angleOffset ?? 0);
      setOccludedAngles(result.occludedAngles ?? []);
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
    const { samples: exampleSamples, baseline } = wrapCompensatedSample();
    setPayload(serializeSamples(exampleSamples, baseline));
    setAngleOffset('');
    clearResult();
  };

  // Editing, adding or removing an occlusion interval makes the previous
  // judgment stale exactly like editing the payload does: results and ring
  // highlight hide immediately while the typed endpoints stay for correction.
  const updateOcclusionRow = (id: number, key: 'start' | 'end', value: string) => {
    setOcclusionRows((rows) =>
      rows.map((row) => (row.id === id ? { ...row, [key]: value } : row)),
    );
    hideStaleResult();
  };

  const addOcclusionRow = () => {
    setOcclusionRows((rows) => [
      ...rows,
      { id: (nextOcclusionRowId += 1), start: '', end: '' },
    ]);
    hideStaleResult();
  };

  const removeOcclusionRow = (id: number) => {
    setOcclusionRows((rows) => rows.filter((row) => row.id !== id));
    hideStaleResult();
  };

  const selectedSegment = selectedIndex === null ? null : segments[selectedIndex] ?? null;
  const peakDetail = (() => {
    if (!selectedSegment) return null;
    const sourceNote =
      selectedSegment.sourcePeakAngle !== undefined
        ? `，对应原始来源角 ${selectedSegment.sourcePeakAngle}°`
        : '';
    if (baselineApplied) {
      return (
        `选中区段峰值展示角 ${selectedSegment.peakAngle}°${sourceNote}：` +
        `原幅值 ${(selectedSegment.peakRawAmplitude ?? 0).toFixed(3)} mm，基线 ${(selectedSegment.peakBaseline ?? 0).toFixed(3)} mm，` +
        `校正幅值 ${selectedSegment.peakAmplitude.toFixed(3)} mm`
      );
    }
    return `选中区段峰值展示角 ${selectedSegment.peakAngle}°${sourceNote}（峰值 ${selectedSegment.peakAmplitude.toFixed(3)} mm）`;
  })();

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
            onChange={(event) => {
              setPayload(event.target.value);
              hideStaleResult();
            }}
            spellCheck={false}
            rows={20}
          />
          <label className="field-label" htmlFor="angle-offset">
            零位角度偏移 angleOffset（整数，-359 至 359；留空表示不校正）
          </label>
          <input
            id="angle-offset"
            data-testid="angle-offset"
            type="text"
            inputMode="numeric"
            className={['text-input', 'offset-input', offsetInvalid ? 'invalid' : '']
              .filter(Boolean)
              .join(' ')}
            value={angleOffset}
            placeholder="例如 5：编码器零位相对现场标记偏 5°"
            onChange={(event) => {
              setAngleOffset(event.target.value);
              hideStaleResult();
            }}
            spellCheck={false}
          />
          <p className="muted offset-hint">
            修改偏移后旧结果立即隐藏并清除高亮，重新提交成功才恢复；基线仍按原始角度配对，不随展示坐标错配。
          </p>
          <label className="field-label">
            遮挡区间 occlusions（至多 {MAX_OCCLUSIONS} 个；整数展示角 0–359，顺时针闭区间，起止相同仅遮挡该点）
          </label>
          <div className="occlusion-rows">
            {occlusionRows.map((row, index) => (
              <div className="occlusion-row" key={row.id}>
                <input
                  data-testid={`occlusion-start-${index}`}
                  type="text"
                  inputMode="numeric"
                  className={[
                    'text-input',
                    'occlusion-input',
                    errorFields.has(`occlusions[${index}].start`) ? 'invalid' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  value={row.start}
                  placeholder="起点"
                  aria-label={`遮挡区间 ${index + 1} 起点`}
                  onChange={(event) => updateOcclusionRow(row.id, 'start', event.target.value)}
                  spellCheck={false}
                />
                <span className="occlusion-arrow">→</span>
                <input
                  data-testid={`occlusion-end-${index}`}
                  type="text"
                  inputMode="numeric"
                  className={[
                    'text-input',
                    'occlusion-input',
                    errorFields.has(`occlusions[${index}].end`) ? 'invalid' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  value={row.end}
                  placeholder="终点"
                  aria-label={`遮挡区间 ${index + 1} 终点`}
                  onChange={(event) => updateOcclusionRow(row.id, 'end', event.target.value)}
                  spellCheck={false}
                />
                <button
                  type="button"
                  className="occlusion-remove"
                  onClick={() => removeOcclusionRow(row.id)}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
          <div className="actions">
            <button
              type="button"
              className="secondary-button"
              onClick={addOcclusionRow}
              disabled={occlusionRows.length >= MAX_OCCLUSIONS}
            >
              添加遮挡区间
            </button>
          </div>
          <p className="muted offset-hint">
            螺栓孔或夹具遮挡的角区标为未判读并从区段计算中剔除；跨零与重叠区间会合并。填写或修改后旧结果立即隐藏，重新提交成功才恢复。
          </p>
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
            <p className="muted">提交合法数据后显示计算结果。修改输入或校验失败都会立即隐藏现有结果和图形高亮。</p>
          ) : (
            <>
              {appliedOffset !== 0 && (
                <p className="table-note" data-testid="offset-note">
                  当前角度已按零位偏移 {appliedOffset > 0 ? `+${appliedOffset}` : appliedOffset}°
                  环形归一化到现场标记坐标（0°–359°）；基线按原始角度配对后再校正。
                </p>
              )}
              {occludedAngles.length > 0 && (
                <p className="table-note" data-testid="occlusion-note">
                  已合并遮挡 {occludedAngles.length} 个展示角（未判读，不参与区段计算）：
                  {occludedAngles.length <= 12
                    ? `${occludedAngles.join('°、')}°`
                    : '范围详见采样环纹理'}
                  。
                </p>
              )}
              {segments.length === 0 ? (
                <p className="muted">本次没有达到阈值的缺陷点。</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>区段</th>
                        <th>起点（展示角）</th>
                        <th>终点（展示角）</th>
                        <th>跨度（采样点数）</th>
                        <th>峰值角（展示角）</th>
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
                  {peakDetail && (
                    <p className="peak-detail" data-testid="peak-detail">
                      {peakDetail}
                    </p>
                  )}
                </div>
              )}
            </>
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
          angleOffset={appliedOffset}
          occludedAngles={occludedAngles}
        />
        <div className="legend panel">
          <span><i className="legend-normal" />非缺陷采样</span>
          <span><i className="legend-defect" />缺陷采样</span>
          <span><i className="legend-selected" />当前选中区段</span>
          <span><i className="legend-occluded" />遮挡未判读</span>
        </div>
      </div>
    </section>
  );
}
