import { useState } from 'react';
import AnalyzePanel from './AnalyzePanel';
import CalibrationPanel from './CalibrationPanel';

type ViewKey = 'analyze' | 'calibration';

const viewMeta: Record<
  ViewKey,
  { eyebrow: string; description: string; badgeTitle: string; badgeLine: string }
> = {
  analyze: {
    eyebrow: 'WHEELSET ULTRASONIC REVIEW',
    description:
      '服务端接收恰好 360 条整数角度采样，并实时计算顺时针连续缺陷区段；359° 与 0° 按环形相邻处理。',
    badgeTitle: '判读规则',
    badgeLine: '幅值 ≥ 阈值即为缺陷点',
  },
  calibration: {
    eyebrow: 'SOUND PATH CALIBRATION',
    description:
      '更换探头或耦合剂后，在已知厚度的参考试块上录入 3–8 个厚度与往返时间测点，按普通最小二乘拟合声程直线并评定记录。',
    badgeTitle: '评定规则',
    badgeLine: '最大|残差| ≤ 允许残差即为合格',
  },
};

export default function App() {
  const [view, setView] = useState<ViewKey>('analyze');
  const meta = viewMeta[view];

  return (
    <main className="page-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">{meta.eyebrow}</p>
          <h1>轮对超声环形读数判读台</h1>
          <p>{meta.description}</p>
        </div>
        <div className="rule-badge">
          <strong>{meta.badgeTitle}</strong>
          <span>{meta.badgeLine}</span>
        </div>
      </header>

      <nav className="view-tabs" aria-label="功能切换">
        <button
          type="button"
          className={view === 'analyze' ? 'tab tab--active' : 'tab'}
          aria-pressed={view === 'analyze'}
          onClick={() => setView('analyze')}
        >
          缺陷判读
        </button>
        <button
          type="button"
          className={view === 'calibration' ? 'tab tab--active' : 'tab'}
          aria-pressed={view === 'calibration'}
          onClick={() => setView('calibration')}
        >
          声程校准
        </button>
      </nav>

      {view === 'analyze' ? <AnalyzePanel /> : <CalibrationPanel />}
    </main>
  );
}
