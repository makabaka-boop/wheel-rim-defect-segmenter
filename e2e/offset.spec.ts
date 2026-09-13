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

test('零位偏移：载荷自带偏移而偏移框留空时，采样环幅值统一使用展示角', async ({ page }) => {
  await page.goto('/');

  // 载荷 JSON 自带 angleOffset: 5（不带基线，采样环幅值直接来自 samples），
  // 页面偏移框留空：服务端按载荷偏移旋转，采样环必须同步落到展示坐标。
  const samples = Array.from({ length: 360 }, (_, angle) => ({
    angle,
    amplitude: angle === 2 ? 4.4 : angle >= 357 || angle <= 2 ? 4.8 : 0.4,
  }));
  await page
    .locator('#payload')
    .fill(JSON.stringify({ threshold: 2.5, angleOffset: 5, samples }));
  await page.getByRole('button', { name: '提交判读' }).click();

  // 结果区段已旋转到展示坐标：跨零段变为 2°→7° 普通连续区段。
  await expect(page.getByTestId('offset-note')).toContainText('+5');
  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator('td').nth(1)).toHaveText('2°');
  await expect(rows.first().locator('td').nth(2)).toHaveText('7°');

  // 采样环幅值同样落在展示角：展示角 7° 对应来源角 2° 的 4.4 mm，
  // 展示角 8° 对应来源角 3° 的 0.4 mm，而不是停留在来源角 7°/8° 的幅值。
  const dots = page.locator('.sample-dot');
  await expect(dots.nth(7).locator('title')).toContainText('展示角 7°，幅值 4.400 mm');
  await expect(dots.nth(8).locator('title')).toContainText('展示角 8°，幅值 0.400 mm');
});

test('结果交互：判读成功后改动采样载荷，旧区段、峰值与环形高亮立即隐藏', async ({ page }) => {
  await page.goto('/');

  // 默认样例提交成功：区段表、峰值明细与环形高亮均可见。
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('peak-detail')).toBeVisible();
  await expect(page.locator('.segment-arc').first()).toBeVisible();
  await expect(page.locator('.selected-halo').first()).toBeVisible();

  // 直接改动采样载荷内容（换成阈值 3.5 的紧凑载荷）：旧结果与环形高亮立即隐藏，
  // 结果区回到待提交提示。
  const samples = Array.from({ length: 360 }, (_, angle) => ({
    angle,
    amplitude: angle >= 357 || angle <= 2 ? 4.8 : 0.4,
  }));
  await page.locator('#payload').fill(JSON.stringify({ threshold: 3.5, samples }));
  await expect(page.getByText('357° → 2°')).toHaveCount(0);
  await expect(page.getByTestId('peak-detail')).toHaveCount(0);
  await expect(page.locator('.segment-arc')).toHaveCount(0);
  await expect(page.locator('.selected-halo')).toHaveCount(0);
  await expect(page.getByText('提交合法数据后显示计算结果。')).toBeVisible();

  // 重新提交成功后结果按新载荷恢复。
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('peak-detail')).toBeVisible();
});
