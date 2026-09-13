import { test, expect } from '@playwright/test';

test('零位偏移：跨零缺陷转为普通连续区段，峰值可查来源角，非法偏移字段反馈', async ({ page }) => {
  await page.goto('/');

  // 默认载入带基线的跨零度样例（357°..359° 与 0°..2° 超限）。
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('offset-note')).toHaveCount(0);

  // 修改偏移的瞬间旧结果与高亮必须隐藏，直到重新提交成功。
  const offsetInput = page.getByTestId('angle-offset');
  await offsetInput.fill('5');
  await expect(page.getByText('357° → 2°')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('offset-note')).toHaveCount(0);

  // +5° 后采样环与结果表统一落到现场标记坐标：跨零段变为 2°→7° 普通连续区段。
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByTestId('offset-note')).toContainText('+5');
  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator('td').nth(1)).toHaveText('2°');
  await expect(rows.first().locator('td').nth(2)).toHaveText('7°');
  await expect(rows.first().locator('td').nth(4)).toHaveText('2°');

  // 选中区段展示峰值的展示角与原始来源角（六个校正幅值并列，取最小展示角 2°，来源 357°）。
  const peakDetail = page.getByTestId('peak-detail');
  await expect(peakDetail).toBeVisible();
  await expect(peakDetail).toContainText('展示角 2°');
  await expect(peakDetail).toContainText('来源角 357°');

  // 非法偏移：错误定位到 angleOffset 字段，结果与高亮清空。
  await offsetInput.fill('0.5');
  await expect(rows).toHaveCount(0);
  await page.getByRole('button', { name: '提交判读' }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText('angleOffset');
  await expect(offsetInput).toHaveClass(/invalid/);
  await expect(page.getByTestId('offset-note')).toHaveCount(0);

  // 超范围偏移同样定位到该字段。
  await offsetInput.fill('360');
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(alert).toContainText('angleOffset');

  // 清空偏移并重新提交：旧请求语义，跨零合段与当前版本完全一致。
  await offsetInput.fill('');
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('offset-note')).toHaveCount(0);
  await expect(page.getByTestId('peak-detail')).toContainText('展示角 0°');
  await expect(page.getByTestId('peak-detail')).not.toContainText('来源角');
});
