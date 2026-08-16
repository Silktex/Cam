import { test, expect } from '@playwright/test';

test.describe('Global Navigation & StudioHeader Telemetry', () => {
  test.beforeEach(async ({ page }) => {
    // Intercept backend API calls with mock responses so tests are reliable
    await page.route('**/api/camera/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connected: true,
          model: 'Sony ILCE-7RM3',
          port: 'usb:001,005',
          battery_level: 88,
        }),
      });
    });

    await page.route('**/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          services: { api_server: true, camera_detected: true, camera_connected: true },
        }),
      });
    });

    await page.route('**/api/camera/troubleshoot', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'recovered',
          message: 'PTP re-detected successfully in 2.34s',
          camera: { connected: true, model: 'Sony ILCE-7RM3' },
        }),
      });
    });

    await page.goto('/');
  });

  test('NAV-01: renders brand logo and station subtitle', async ({ page }) => {
    await expect(page.getByText('OPTIX.RIG')).toBeVisible();
    await expect(page.getByText('CAPTURE STUDIO', { exact: true })).toBeVisible();
  });

  test('NAV-02: provides 5-station navigation links with active routing indicators', async ({ page }) => {
    // Station 1: Capture Studio
    const st1 = page.getByRole('link', { name: '1. Capture Studio' });
    await expect(st1).toBeVisible();
    await expect(st1).toHaveClass(/bg-accent/);

    // Navigate to Station 2: Batch Sequencer
    const st2 = page.getByRole('link', { name: '2. Batch Sequencer' });
    await expect(st2).toBeVisible();
    await st2.click();
    await expect(page).toHaveURL(/\/batch/);
    await expect(page.getByText('BATCH SEQUENCER', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '2. Batch Sequencer' })).toHaveClass(/bg-accent/);

    // Navigate to Station 3: Color Calibration
    const st3 = page.getByRole('link', { name: '3. Color Calibration' });
    await expect(st3).toBeVisible();
    await st3.click();
    await expect(page).toHaveURL(/\/calibration/);
    await expect(page.getByText('COLOR SCIENCE', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '3. Color Calibration' })).toHaveClass(/bg-accent/);

    // Navigate to Station 4: PBR Synthesis
    const st4 = page.getByRole('link', { name: '4. PBR Synthesis' });
    await expect(st4).toBeVisible();
    await st4.click();
    await expect(page).toHaveURL(/\/processing/);
    await expect(page.getByText('PBR SYNTHESIS LAB', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '4. PBR Synthesis' })).toHaveClass(/bg-accent/);

    // Navigate to Station 5: Lightbox Gallery
    const st5 = page.getByRole('link', { name: '5. Lightbox Gallery' });
    await expect(st5).toBeVisible();
    await st5.click();
    await expect(page).toHaveURL(/\/gallery/);
    await expect(page.getByText('INSPECTION LIGHTBOX', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '5. Lightbox Gallery' })).toHaveClass(/bg-accent/);

    // Direct legacy alias /capture navigates to Capture Studio
    await page.goto('/capture');
    await expect(page.getByText('CAPTURE STUDIO', { exact: true })).toBeVisible();

    // Direct legacy alias /pbr navigates to PBR Synthesis
    await page.goto('/pbr');
    await expect(page.getByText('PBR SYNTHESIS LAB', { exact: true })).toBeVisible();

    // Direct legacy alias /color-calibration navigates to Color Calibration
    await page.goto('/color-calibration');
    await expect(page.getByText('COLOR SCIENCE', { exact: true })).toBeVisible();
  });

  test('NAV-03: displays live hardware telemetry pods for camera and ESP32 rig', async ({ page }) => {
    // Camera status pod
    await expect(page.getByText('Sony ILCE-7RM3')).toBeVisible();
    await expect(page.getByText('61.0 MP')).toBeVisible();

    // ESP32 status pod
    await expect(page.getByText('ESP32 RIG')).toBeVisible();
    await expect(page.getByText('/9 LED')).toBeVisible();
  });

  test('NAV-04: executes non-destructive PTP re-detect recovery', async ({ page }) => {
    const reDetectBtn = page.getByRole('button', { name: /Re-Detect/i });
    await expect(reDetectBtn).toBeVisible();
    await reDetectBtn.click();
    await expect(page.getByText('PTP re-detected successfully in 2.34s')).toBeVisible();
  });

  test('NAV-05: toggles keyboard shortcuts modal via button and ? key', async ({ page }) => {
    // Click keyboard shortcut button
    const shortcutBtn = page.getByTitle(/Keyboard Shortcuts/i);
    await expect(shortcutBtn).toBeVisible();
    await shortcutBtn.click();

    // Verify modal content
    await expect(page.getByRole('heading', { name: 'Keyboard Shortcuts' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Navigation' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Lights' })).toBeVisible();

    // Close modal via Escape
    await page.keyboard.press('Escape');
    await expect(page.getByRole('heading', { name: 'Keyboard Shortcuts' })).not.toBeVisible();

    // Open modal via '?' key
    await page.keyboard.press('?');
    await expect(page.getByRole('heading', { name: 'Keyboard Shortcuts' })).toBeVisible();

    // Close via close button
    const closeBtn = page.getByRole('button', { name: /Close/i });
    if (await closeBtn.isVisible()) {
      await closeBtn.click();
      await expect(page.getByRole('heading', { name: 'Keyboard Shortcuts' })).not.toBeVisible();
    }
  });
});
