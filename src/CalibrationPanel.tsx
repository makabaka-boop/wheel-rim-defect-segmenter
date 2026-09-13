import { useMemo, useState } from 'react';
import {
  calibrationSample,
  evaluateCalibration,
  type CalibrationRequest,
  type CalibrationResponse,
  type FieldError,
} from './api';
import CalibrationChart from './CalibrationChart';

const MIN_ROWS = 3;
const MAX_ROWS = 8;

interface PointRow {
  thickness: string;
  travelTime: string;
}

const sampleRows = (): PointRow[] =>
  calibrationSample().points.map((point) => ({
    thickness: String(point.thickness),
    travelTime: String(point.travelTime),
  }));

// Invalid entries are sent through as their raw text so the server can
// localize the offending field instead of the browser failing silently.
const parseField = (value: string): number | string => {
  const trimmed = value.trim();
  if (trimmed === '') {
    return trimmed;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : trimmed;
};

const statusText = { unevaluated: '未评定', pass: '合格', fail: '不合格' } as const;

export default function CalibrationPanel() {
  const sample = calibrationSample();
  const [name, setName] = useState(sample.name);
  const [tolerance, setTolerance] = useState(String(sample.tolerance));
  const [rows, setRows] = useState<PointRow[]>(sampleRows);
  const [result, setResult] = useState<CalibrationResponse | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const errorFields = useMemo(() => new Set(errors.map((error) => error.field)), [errors]);

  const updateRow = (index: number, field: keyof PointRow, value: string) => {
    setRows((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, [field]: value } : row)),
    );
  };

  const addRow = () => {
    setRows((current) =>
      current.length >= MAX_ROWS ? current : [...current, { thickness: '', travelTime: '' }],
    );
  };

  const removeRow = (index: number) => {
    setRows((current) =>
      current.length <= MIN_ROWS ? current : current.filter((_, rowIndex) => rowIndex !== index),
    );
  };

  const loadSample = () => {
    const defaults = calibrationSample();
    setName(defaults.name);
    setTolerance(String(defaults.tolerance));
    setRows(sampleRows());
    setResult(null);
    setErrors([]);
  };

  const submit = async () => {
    setSubmitting(true);
    // A failed or fresh submission always clears the old curve and verdict.
    setErrors([]);
    setResult(null);
    const requestPayload = {
      name: name.trim(),
      tolerance: parseField(tolerance),
      points: rows.map((row) => ({
        thickness: parseField(row.thickness),
        travelTime: parseField(row.travelTime),
      })),
    } as unknown as CalibrationRequest;
    try {
      setResult(await evaluateCalibration(requestPayload));
    } catch (receivedErrors) {
      setErrors(
        Array.isArray(receivedErrors)
          ? (receivedErrors as FieldError[])
          : [{ field: 'request', message: '无法连接校准 API' }],
      );
    } finally {
      setSubmitting(false);
    }
  };

  const status = result?.status ?? 'unevaluated';
  const worstPoint = result ? result.points[result.maxResidualIndex] : null;

  return (
    <section className="workspace">
      <div className="input-column">
        <div className="panel">
          <div className="panel-heading">
            <h2>声程校准记录</h2>
            <button type="button" className="secondary-button" onClick={loadSample}>
              载入精确直线样例
            </button>
          </div>

          <label className="field-label" htmlFor="cal-name">
            记录名称
          </label>
          <input
            id="cal-name"
            className={`text-input ${errorFields.has('name') ? 'invalid' : ''}`}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />

          <label className="field-label" htmlFor="cal-tolerance">
            允许残差（µs，正数）
          </label>
          <input
            id="cal-tolerance"
            className={`text-input ${errorFields.has('tolerance') ? 'invalid' : ''}`}
            value={tolerance}
            onChange={(event) => setTolerance(event.target.value)}
            inputMode="decimal"
          />

          <div className="panel-heading points-heading">
            <label className="field-label">测点（{rows.length} / {MIN_ROWS}–{MAX_ROWS}，厚度 mm、往返时间 µs）</label>
            <button
              type="button"
              className="secondary-button"
              onClick={addRow}
              disabled={rows.length >= MAX_ROWS}
            >
              添加测点
            </button>
          </div>
          {errorFields.has('points') && (
            <p className="field-error-note" role="alert">
              {errors.find((error) => error.field === 'points')?.message}
            </p>
          )}
          <div className="table-wrap">
            <table className="points-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>厚度（mm）</th>
                  <th>往返时间（µs）</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    <td>{index + 1}</td>
                    <td>
                      <input
                        className={`cell-input ${
                          errorFields.has(`points[${index}].thickness`) ? 'invalid' : ''
                        }`}
                        value={row.thickness}
                        onChange={(event) => updateRow(index, 'thickness', event.target.value)}
                        inputMode="decimal"
                        aria-label={`第 ${index + 1} 点厚度`}
                        data-testid={`thickness-${index}`}
                      />
                    </td>
                    <td>
                      <input
                        className={`cell-input ${
                          errorFields.has(`points[${index}].travelTime`) ? 'invalid' : ''
                        }`}
                        value={row.travelTime}
                        onChange={(event) => updateRow(index, 'travelTime', event.target.value)}
                        inputMode="decimal"
                        aria-label={`第 ${index + 1} 点往返时间`}
                        data-testid={`travel-time-${index}`}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="row-remove"
                        onClick={() => removeRow(index)}
                        disabled={rows.length <= MIN_ROWS}
                        aria-label={`删除第 ${index + 1} 点`}
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="actions">
            <button type="button" className="primary-button" onClick={submit} disabled={submitting}>
              {submitting ? '评定中…' : '提交校准'}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setResult(null);
                setErrors([]);
              }}
            >
              清空结果
            </button>
          </div>
        </div>

        {errors.length > 0 && (
          <div className="panel error-panel" role="alert">
            <h2>输入未通过，本次曲线与结论已清空</h2>
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
          <div className="panel-heading">
            <h2>评定结论</h2>
            <span
              className={`status-badge status-badge--${status}`}
              data-testid="calibration-status"
            >
              {statusText[status]}
            </span>
          </div>
          {!result ? (
            <p className="muted">
              提交合法测点后显示拟合声速、零点偏移与逐点残差；校验失败会清空旧曲线与结论，记录回到未评定。
            </p>
          ) : (
            <>
              <dl className="metrics-grid">
                <div>
                  <dt>拟合声速</dt>
                  <dd data-testid="sound-velocity">{result.soundVelocity.toFixed(4)} mm/µs</dd>
                </div>
                <div>
                  <dt>零点偏移</dt>
                  <dd data-testid="zero-offset">{result.zeroOffset.toFixed(4)} µs</dd>
                </div>
                <div>
                  <dt>拟合直线</dt>
                  <dd>
                    t = {result.slope.toFixed(5)}·d + {result.zeroOffset.toFixed(4)}
                  </dd>
                </div>
                <div>
                  <dt>允许残差</dt>
                  <dd>±{result.tolerance} µs</dd>
                </div>
                <div className="metrics-wide">
                  <dt>最大绝对残差</dt>
                  <dd data-testid="max-abs-residual">
                    {result.maxAbsResidual.toFixed(4)} µs（第 {result.maxResidualIndex + 1} 点，厚度{' '}
                    {worstPoint?.thickness} mm）
                  </dd>
                </div>
              </dl>
              <p className="table-note">
                复算：max|残差| = {result.maxAbsResidual.toFixed(4)} µs
                {result.status === 'pass' ? ' ≤ ' : ' > '}
                允许残差 {result.tolerance} µs → {statusText[result.status]}
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>厚度（mm）</th>
                      <th>实测（µs）</th>
                      <th>预测（µs）</th>
                      <th>残差（µs）</th>
                      <th>判定</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.points.map((point, index) => {
                      const isMax = index === result.maxResidualIndex;
                      return (
                        <tr
                          key={index}
                          className={[
                            point.withinTolerance ? '' : 'out-row',
                            isMax ? 'max-residual-row' : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                          data-testid={isMax ? 'max-residual-row' : undefined}
                        >
                          <td>{index + 1}</td>
                          <td>{point.thickness}</td>
                          <td>{point.travelTime}</td>
                          <td>{point.predictedTime.toFixed(4)}</td>
                          <td>{point.residual.toFixed(4)}</td>
                          <td>
                            {point.withinTolerance ? '容差内' : '超差'}
                            {isMax ? '（最大）' : ''}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="visual-column">
        {result ? (
          <CalibrationChart
            points={result.points}
            slope={result.slope}
            zeroOffset={result.zeroOffset}
            maxResidualIndex={result.maxResidualIndex}
            tolerance={result.tolerance}
          />
        ) : (
          <div className="ring-card chart-placeholder">
            <p className="muted">提交后在此绘制实测点与拟合直线；校验失败时旧曲线会被清除。</p>
          </div>
        )}
        <div className="legend panel">
          <span><i className="legend-measured" />实测测点</span>
          <span><i className="legend-fit" />拟合直线</span>
          <span><i className="legend-max-residual" />最大绝对残差点</span>
        </div>
      </div>
    </section>
  );
}
