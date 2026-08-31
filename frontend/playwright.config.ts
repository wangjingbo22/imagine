import { defineConfig, devices } from '@playwright/test'
import { S3_T001_VIEWPORTS } from './src/services/s2T024Acceptance'

const publicBaseUrl = process.env.S2_T024_BASE_URL?.trim()

export default defineConfig({
  testDir: './e2e',
  outputDir: 'test-results/s2-t024',
  fullyParallel: false,
  workers: process.env.CI ? 2 : 1,
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: publicBaseUrl || 'http://127.0.0.1:4173',
    locale: 'zh-CN',
    reducedMotion: 'reduce',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Public acceptance operators may enable video explicitly after installing
    // Playwright's ffmpeg helper. CI/local contract checks stay dependency-light.
    video: process.env.S2_T024_RECORD_VIDEO ? 'retain-on-failure' : 'off',
    ...devices['Desktop Chrome'],
  },
  webServer: publicBaseUrl
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 4173',
        url: 'http://127.0.0.1:4173',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: S3_T001_VIEWPORTS.map((viewport) => ({
    name: viewport.id,
    use: {
      viewport: { width: viewport.width, height: viewport.height },
      ...(process.env.CI ? {} : { channel: 'msedge' }),
    },
  })),
})
