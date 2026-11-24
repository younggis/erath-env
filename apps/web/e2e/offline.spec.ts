/**
 * Playwright E2E for the offline vertical slice (AC-01 / AC-05 / AC-06).
 * Requires a running fixture-mode API at 127.0.0.1:8080 with fixtures installed.
 *   npx playwright install chromium
 *   npx playwright test
 */
import { test, expect } from '@playwright/test'

const BASE = process.env.EARTHSIM_BASE_URL || 'http://127.0.0.1:8080'

test('offline boot shows demo badge, layers and timeline', async ({ page }) => {
  await page.goto(BASE)
  await expect(page.getByText('● 演示')).toBeVisible()
  await expect(page.getByText('数据图层')).toBeVisible()
  await expect(page.getByText('10 m 风')).toBeVisible()
  await expect(page.getByText('观测')).toBeVisible()
  await expect(page.locator('input[type=range]').first()).toBeVisible()
})

test('switching layer updates legend, unit and source time', async ({ page }) => {
  await page.goto(BASE)
  await page.getByRole('button', { name: /2 m 气温/ }).first().click()
  await expect(page.locator('.detail')).toContainText('2 m 气温')
  await expect(page.locator('.globe-hud')).toContainText('2026-11-20T00:00:00Z')
})

test('clicking the globe issues a sample query with metadata', async ({ page }) => {
  const requests: string[] = []
  page.on('request', r => { if (r.url().includes('/api/v1/sample')) requests.push(r.url()) })
  await page.goto(BASE)
  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  if (!box) throw new Error('globe canvas not rendered')
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
})
