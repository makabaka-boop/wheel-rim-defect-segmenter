export interface ReadingInput {
  angle: number;
  amplitude: number;
}

export interface SegmentResult {
  startAngle: number;
  endAngle: number;
  span: number;
  peakAngle: number;
  peakAmplitude: number;
  angles: number[];
}

export interface AnalysisResponse {
  threshold: number;
  sampleCount: number;
  segments: SegmentResult[];
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

export const serializeSamples = (samples: ReadingInput[]): string =>
  JSON.stringify(
    {
      threshold: 2.5,
      samples,
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
