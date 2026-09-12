export interface ReadingInput {
  angle: number;
  amplitude: number;
}

export interface BaselineInput {
  angle: number;
  value: number;
}

export interface SegmentResult {
  startAngle: number;
  endAngle: number;
  span: number;
  peakAngle: number;
  peakAmplitude: number;
  angles: number[];
  peakRawAmplitude?: number;
  peakBaseline?: number;
}

export interface CorrectedPoint {
  angle: number;
  amplitude: number;
  baseline: number;
  correctedAmplitude: number;
}

export interface AnalysisResponse {
  threshold: number;
  sampleCount: number;
  baselineApplied: boolean;
  segments: SegmentResult[];
  points?: CorrectedPoint[];
}

export interface FieldError {
  field: string;
  message: string;
}

export const wrapSample = (): ReadingInput[] => {
  const samples: ReadingInput[] = [];
  for (let angle = 0; angle < 360; angle += 1) {
    const defective = angle >= 357 || angle <= 2;
    samples.push({
      angle,
      amplitude: defective ? 4.8 : Number((0.35 + (angle % 7) * 0.09).toFixed(2)),
    });
  }
  return samples;
};

export const wrapBaseline = (): BaselineInput[] => {
  const baseline: BaselineInput[] = [];
  for (let angle = 0; angle < 360; angle += 1) {
    baseline.push({ angle, value: Number((0.3 + (angle % 5) * 0.08).toFixed(2)) });
  }
  return baseline;
};

export const wrapCompensatedSample = (): {
  samples: ReadingInput[];
  baseline: BaselineInput[];
} => {
  const baseline = wrapBaseline();
  const samples = baseline.map(({ angle, value }) => {
    const defective = angle >= 357 || angle <= 2;
    return {
      angle,
      amplitude: Number((value + (defective ? 4.8 : 0.12 + (angle % 3) * 0.05)).toFixed(2)),
    };
  });
  return { samples, baseline };
};

export const serializeSamples = (
  samples: ReadingInput[],
  baseline?: BaselineInput[],
): string =>
  JSON.stringify(
    {
      threshold: 2.5,
      samples,
      ...(baseline ? { baseline } : {}),
    },
    null,
    2,
  );

export async function analyzeReadings(payload: string): Promise<AnalysisResponse> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Promise.reject([{ field: 'request', message: `JSON 格式非法：${message}` }]);
  }

  const response = await fetch('/api/readings/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parsed),
  });

  const body = await response.json();
  if (!response.ok) {
    throw body.errors ?? [{ field: 'request', message: '接口返回未知错误' }];
  }
  return body as AnalysisResponse;
}
