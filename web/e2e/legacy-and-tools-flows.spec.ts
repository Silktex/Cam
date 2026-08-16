import { test, expect } from '@playwright/test';

test.describe('Specialized & Legacy Studio Flows', () => {
  test('LEG-01: renders dedicated ESP32 Light Controller page (/lights)', async ({ page }) => {
    await page.goto('/lights');
    await expect(page.getByRole('heading', { name: 'ESP32 Light Controller' })).toBeVisible();

    // Master buttons
    await expect(page.getByRole('button', { name: 'ALL ON' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'ALL OFF' })).toBeVisible();

    // Click ALL ON
    await page.getByRole('button', { name: 'ALL ON' }).click();
    await expect(page.getByText('All lights ON')).toBeVisible();

    // Click ALL OFF
    await page.getByRole('button', { name: 'ALL OFF' }).click();
    await expect(page.getByText('All lights OFF')).toBeVisible();
  });

  test('LEG-02: renders all-in-one cockpit page (/all) and switches tabs', async ({ page }) => {
    await page.goto('/all');

    // Tab buttons
    const singleTab = page.getByRole('button', { name: 'Single' });
    const colorTab = page.getByRole('button', { name: 'Color' });
    const batchTab = page.getByRole('button', { name: 'Batch' });

    await expect(singleTab).toBeVisible();
    await expect(colorTab).toBeVisible();
    await expect(batchTab).toBeVisible();

    // Switch to Color Tab
    await colorTab.click();
    await expect(page.getByRole('heading', { name: 'Color Checker' })).toBeVisible();

    // Switch to Batch Tab
    await batchTab.click();
    await expect(page.getByRole('heading', { name: 'Batch Capture' })).toBeVisible();

    // Switch back to Single Tab
    await singleTab.click();
    await expect(page.getByRole('heading', { name: 'Image Capture' })).toBeVisible();
  });

  test('LEG-03: renders Processing Tools Hub (/processing/tools) and displays pipeline steps', async ({ page }) => {
    // Mock all batch and tools requests with CORS headers
    await page.route('**/api/batches**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          batches: [
            {
              name: 'batch_test_linen_4355',
              image_count: 9,
              crop_status: 'completed',
              calibration_status: 'completed',
              pbr_status: 'completed',
              created_at: '14:00:00',
            },
          ],
        }),
      });
    });

    await page.route('**/api/processing/tools-status/**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          perspective_corrected: true,
          equalized: true,
          flattened: true,
          delighted: true,
          seamless: true,
          tiled: true,
        }),
      });
    });

    await page.goto('/processing/tools');
    await expect(page.getByRole('heading', { name: 'Material Tools' })).toBeVisible();

    // Select batch from list
    const batchBtn = page.getByText('batch_test_linen_4355');
    await expect(batchBtn).toBeVisible({ timeout: 10000 });
    await batchBtn.click();

    // Verify main pipeline steps are visible
    await expect(page.getByRole('heading', { name: 'Perspective' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Equalize' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Flatten' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Delight' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Make Seamless' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Tiling' })).toBeVisible();

    // Utility tools
    await expect(page.getByRole('heading', { name: 'PBR Validate' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Clone Stamp' })).toBeVisible();
  });

  test('LEG-04: loads Image Processing batch manager (/image-processing)', async ({ page }) => {
    await page.route('**/api/image-processing/batches**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          'access-control-allow-origin': '*',
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          batches: [
            {
              name: 'batch_fabric_4355',
              image_count: 9,
              raw_count: 9,
              cropped_count: 9,
              calibrated_count: 9,
              total_phases: 6,
              completed_phases: 3,
              phase_statuses: {
                crop_align: 'completed',
                color: 'completed',
                pbr: 'completed',
              },
            },
          ],
        }),
      });
    });

    await page.goto('/image-processing');
    await expect(page.getByRole('heading', { name: 'Texturize' })).toBeVisible();
    await expect(page.getByText('batch_fabric_4355')).toBeVisible();
  });

  test('LEG-05: renders classic UI cockpit at /v1 with WebRTC live stream', async ({ page }) => {
    await page.goto('/v1');

    // Header & Tabs
    await expect(page.getByRole('heading', { name: 'Batch Capture' })).toBeVisible();
    const singleTab = page.getByRole('button', { name: 'Single', exact: true });
    const colorTab = page.getByRole('button', { name: 'Color', exact: true });
    const batchTab = page.getByRole('button', { name: 'Batch', exact: true });

    await expect(singleTab).toBeVisible();
    await expect(colorTab).toBeVisible();
    await expect(batchTab).toBeVisible();

    // Live View with WebRTC Stream & Source Switcher
    await expect(page.getByText('1080p H.264 (HDMI HW Encoded)')).toBeVisible();
    await expect(page.getByRole('button', { name: /SRC: HDMI/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /FREEZE/i })).toBeVisible();

    // Switch to Single Tab
    await singleTab.click();
    await expect(page.getByRole('heading', { name: 'Image Capture' })).toBeVisible();

    // Switch to Color Tab
    await colorTab.click();
    await expect(page.getByRole('heading', { name: 'Color Checker' })).toBeVisible();
  });
});
