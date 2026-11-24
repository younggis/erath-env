import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = process.env.EARTHSIM_BASE_URL || 'http://127.0.0.1:8080'
const OUT = process.env.EARTHSIM_SHOT_DIR || 'F:/knowledgebase/earth/docs/shots'
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
})
const page = await browser.newPage({ viewport: { width: 1600, height: 950 }, deviceScaleFactor: 1 })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', e => errors.push(String(e)))
await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)
await page.screenshot({ path: `${OUT}/01-home.png` })

// Switch to temperature
const tempBtn = page.getByRole('button', { name: /2 m 气温/ }).first()
if (await tempBtn.count()) { await tempBtn.click(); await page.waitForTimeout(1200) }
await page.screenshot({ path: `${OUT}/02-temp.png` })

// Simulation tab
await page.getByRole('button', { name: '算这个区域' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${OUT}/03-sim.png` })

console.log(JSON.stringify({ errors, shots: fs.readdirSync(OUT).filter(f => f.endsWith('.png')) }, null, 2))
await browser.close()
