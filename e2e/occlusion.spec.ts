import { test, expect } from '@playwright/test';

test('遮挡区间：跨零合并剔除高幅值点，纹理标出，非法端点字段反馈且输入保留', async ({ page }) => {
  await page.goto('/');

  // 默认载入带基线的跨零度样例（357°..359° 与 0°..2° 超限），提交前无遮挡。
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('occlusion-note')).toHaveCount(0);
  await expect(page.locator('.sample-dot--occluded')).toHaveCount(0);

  // 填写跨零遮挡区间 358° → 0°：编辑瞬间旧区段与高亮立即隐藏。
  await page.getByRole('button', { name: '添加遮挡区间' }).click();
  await expect(page.getByText('357° → 2°')).toHaveCount(0);
  await page.getByTestId('occlusion-start-0').fill('358');
  await page.getByTestId('occlusion-end-0').fill('0');

  // 提交后 358°/359°/0° 合并为一个遮挡集合，原跨零段被拆为 1°→2° 与 357° 两段。
  await page.getByRole('button', { name: '提交判读' }).click();
  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator('td').nth(1)).toHaveText('1°');
  await expect(rows.nth(0).locator('td').nth(2)).toHaveText('2°');
  await expect(rows.nth(0).locator('td').nth(3)).toHaveText('2');
  await expect(rows.nth(1).locator('td').nth(1)).toHaveText('357°');
  await expect(rows.nth(1).locator('td').nth(2)).toHaveText('357°');
  await expect(rows.nth(1).locator('td').nth(3)).toHaveText('1');

  // 遮挡角按 0..359 合并返回并在结果区与采样环以独立纹理标出。
  await expect(page.getByTestId('occlusion-note')).toContainText('3 个展示角');
  await expect(page.getByTestId('occlusion-note')).toContainText('0°、358°、359°');
  await expect(page.locator('.sample-dot--occluded')).toHaveCount(3);
  await expect(page.locator('.occlusion-arc').first()).toBeVisible();

  // 选中区段时峰值、基线明细保持可用（样例带基线补偿）。
  await rows.nth(1).click();
  const peakDetail = page.getByTestId('peak-detail');
  await expect(peakDetail).toBeVisible();
  await expect(peakDetail).toContainText('展示角 357°');
  await expect(peakDetail).toContainText('基线');
  await expect(peakDetail).toContainText('校正幅值');

  // 非法端点：错误定位到 occlusions[0].end，输入框标红且保留已填内容。
  await page.getByTestId('occlusion-end-0').fill('360');
  await expect(rows).toHaveCount(0);
  await page.getByRole('button', { name: '提交判读' }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toBeVisible();
  await expect(alert).toContainText('occlusions[0].end');
  await expect(page.getByTestId('occlusion-end-0')).toHaveClass(/invalid/);
  await expect(page.getByTestId('occlusion-end-0')).toHaveValue('360');
  await expect(page.getByTestId('occlusion-start-0')).toHaveValue('358');

  // 非整数端点同样定位到对应字段。
  await page.getByTestId('occlusion-end-0').fill('0.5');
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(alert).toContainText('occlusions[0].end');

  // 修正后重新提交，结果与遮挡纹理恢复。
  await page.getByTestId('occlusion-end-0').fill('0');
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(rows).toHaveCount(2);
  await expect(page.getByTestId('occlusion-note')).toContainText('3 个展示角');
  await expect(page.locator('.sample-dot--occluded')).toHaveCount(3);
});

test('遮挡区间：单点遮挡将原区段确定性拆分', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();

  // 起止相同的单点遮挡 0° → 0°：原唯一区段 357°→2° 拆成 1°→2° 与 357°→359°。
  await page.getByRole('button', { name: '添加遮挡区间' }).click();
  await page.getByTestId('occlusion-start-0').fill('0');
  await page.getByTestId('occlusion-end-0').fill('0');
  await page.getByRole('button', { name: '提交判读' }).click();

  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator('td').nth(1)).toHaveText('1°');
  await expect(rows.nth(0).locator('td').nth(2)).toHaveText('2°');
  await expect(rows.nth(1).locator('td').nth(1)).toHaveText('357°');
  await expect(rows.nth(1).locator('td').nth(2)).toHaveText('359°');
  await expect(rows.nth(1).locator('td').nth(3)).toHaveText('3');

  await expect(page.getByTestId('occlusion-note')).toContainText('1 个展示角');
  await expect(page.locator('.sample-dot--occluded')).toHaveCount(1);
  await expect(page.locator('.occlusion-arc--point')).toHaveCount(1);
});

test('遮挡区间：删除区间后恢复旧请求语义，响应不含遮挡字段', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: '添加遮挡区间' }).click();
  await page.getByTestId('occlusion-start-0').fill('358');
  await page.getByTestId('occlusion-end-0').fill('0');
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.locator('tbody tr')).toHaveCount(2);

  // 删除区间后旧结果立即隐藏；重新提交回到省略遮挡区间的旧请求。
  await page.getByRole('button', { name: '删除' }).click();
  await expect(page.locator('tbody tr')).toHaveCount(0);
  await page.getByRole('button', { name: '提交判读' }).click();
  await expect(page.getByText('357° → 2°').first()).toBeVisible();
  await expect(page.getByTestId('occlusion-note')).toHaveCount(0);
  await expect(page.locator('.sample-dot--occluded')).toHaveCount(0);
  await expect(page.locator('.occlusion-arc')).toHaveCount(0);
});
