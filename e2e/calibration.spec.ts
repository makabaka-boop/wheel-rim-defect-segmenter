import { test, expect } from '@playwright/test';

test('声程校准：录入测点、提交评定并高亮不合格点', async ({ page }) => {
  await page.goto('/');

  // 判读台默认加载，标题保持可用。
  await expect(page.getByRole('heading', { name: '轮对超声环形读数判读台' })).toBeVisible();

  // 从判读台进入“声程校准”。
  await page.getByRole('button', { name: '声程校准' }).click();
  await expect(page.getByTestId('calibration-status')).toHaveText('未评定');

  // 录入记录名称与允许残差；默认 5 个测点位于精确直线上。
  await page.getByLabel('记录名称').fill('探头更换后参考试块校准');
  await page.getByLabel(/允许残差/).fill('0.1');
  await expect(page.getByTestId('travel-time-2')).toHaveValue('26.1');

  // 把第 3 点（75 mm）的往返时间改为超差值，制造单点超差。
  await page.getByTestId('travel-time-2').fill('26.4');
  await page.getByRole('button', { name: '提交校准' }).click();

  // 评定为不合格，返回拟合声速与零点偏移。
  await expect(page.getByTestId('calibration-status')).toHaveText('不合格');
  await expect(page.getByTestId('sound-velocity')).toContainText('5.88');
  await expect(page.getByTestId('zero-offset')).toBeVisible();

  // 最大绝对残差点在结果明细行与拟合曲线上同时高亮，可从明细复算结论。
  const maxRow = page.getByTestId('max-residual-row');
  await expect(maxRow).toBeVisible();
  await expect(maxRow).toContainText('75');
  await expect(maxRow).toContainText('超差');
  await expect(page.getByTestId('max-abs-residual')).toContainText('0.24');
  await expect(page.getByTestId('max-residual-point')).toBeVisible();

  // 非法容差导致校验失败：旧曲线与结论被清空，记录回到未评定。
  await page.getByLabel(/允许残差/).fill('-1');
  await page.getByRole('button', { name: '提交校准' }).click();
  await expect(page.getByTestId('calibration-status')).toHaveText('未评定');
  await expect(page.getByTestId('calibration-chart')).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('tolerance');

  // 原判读页仍可正常使用。
  await page.getByRole('button', { name: '缺陷判读' }).click();
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByRole('heading', { name: '连续区段结果' })).toBeVisible();
  await expect(page.getByText('357° → 2°', { exact: false }).first()).toBeVisible();
});
