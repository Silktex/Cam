import { test, expect } from '@playwright/test';

test.describe('Station 2: Photometric Batch Sequencer', () => {
  test.beforeEach(async ({ page }) => {
    // Mock backend batches endpoint
    await page.route('**/api/batches', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          batches: [
            {
              name: 'batch_silk_velvet_4355',
              image_count: 9,
              pbr_status: 'completed',
              created_at: '16:25:10',
            },
          ],
        }),
      });
    });

    await page.goto('/batch');
  });

  test('BAT-01: renders batch configuration parameters and defaults', async ({ page }) => {
    await expect(page.getByText('Photometric Batch Configuration')).toBeVisible();

    // Folder input
    const folderInput = page.locator('input[type="text"]').first();
    await expect(folderInput).toBeVisible();
    await folderInput.fill('batch_e2e_test_sample');

    // Prefix input
    const prefixInput = page.locator('input[type="text"]').nth(1);
    await expect(prefixInput).toBeVisible();
    await expect(prefixInput).toHaveValue('sample_posh');

    // Calibration profile select
    const profileSelect = page.locator('select').first();
    await expect(profileSelect).toBeVisible();
    await profileSelect.selectOption('STUDIO-DAYLIGHT-5600K.icc');
    await expect(profileSelect).toHaveValue('STUDIO-DAYLIGHT-5600K.icc');

    // Stabilize delay
    const delayInput = page.locator('input[type="number"]');
    await expect(delayInput).toBeVisible();
    await delayInput.fill('0.5'); // faster test execution
  });

  test('BAT-02: renders 9-step sequential firing order cards matrix', async ({ page }) => {
    await expect(page.getByText('Sequential Firing Order (9 Steps)')).toBeVisible();

    await expect(page.getByText('TOP DOME')).toBeVisible();
    await expect(page.getByText('SIDE 1 (N)')).toBeVisible();
    await expect(page.getByText('SIDE 2 (NE)')).toBeVisible();
    await expect(page.getByText('SIDE 3 (E)')).toBeVisible();
    await expect(page.getByText('SIDE 4 (SE)')).toBeVisible();
    await expect(page.getByText('SIDE 5 (S)')).toBeVisible();
    await expect(page.getByText('SIDE 6 (SW)')).toBeVisible();
    await expect(page.getByText('SIDE 7 (W)')).toBeVisible();
    await expect(page.getByText('SIDE 8 (NW)')).toBeVisible();
  });

  test('BAT-03: executes automated dry-run sequence and registers completed batch', async ({ page }) => {
    // Set delay to 0.5s for fast test
    const delayInput = page.locator('input[type="number"]');
    await delayInput.fill('0.5');

    // Click Dry Run
    const dryRunBtn = page.getByRole('button', { name: /Dry Run/i });
    await expect(dryRunBtn).toBeVisible();
    await dryRunBtn.click();

    // Verify running status
    await expect(page.getByText('DRY RUN ACTIVE')).toBeVisible();
    await expect(page.getByText(/Capturing Light/i)).toBeVisible();

    // Wait for sequence completion
    await expect(page.getByText('BATCH COMPLETED', { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Dry run sequence completed successfully/i)).toBeVisible();
  });

  test('BAT-04: executes 9-light capture sequence, shows live PIP and registers batch', async ({ page }) => {
    const delayInput = page.locator('input[type="number"]');
    await delayInput.fill('0.5');

    const folderInput = page.locator('input[type="text"]').first();
    await folderInput.fill('batch_photometric_e2e');

    const startBtn = page.getByRole('button', { name: /START 9-LIGHT AUTOMATED SEQUENCE/i });
    await expect(startBtn).toBeVisible();
    await startBtn.click();

    // Active state indicators
    await expect(page.getByText('CAPTURING BATCH...')).toBeVisible();
    await expect(page.getByText(/FIRING LED/i)).toBeVisible();

    // Wait for full batch completion
    await expect(page.getByText('BATCH COMPLETED', { exact: true })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/Batch sequence finished: 9 RAW images captured in batch_photometric_e2e/i)).toBeVisible();

    // Verify newly registered batch appears in Completed Batches table
    await expect(page.getByText('batch_photometric_e2e', { exact: true })).toBeVisible();
  });

  test('BAT-05: cancels batch sequence cleanly during execution', async ({ page }) => {
    const delayInput = page.locator('input[type="number"]');
    await delayInput.fill('2.0'); // Longer delay to allow clicking cancel

    const startBtn = page.getByRole('button', { name: /START 9-LIGHT AUTOMATED SEQUENCE/i });
    await startBtn.click();

    // Verify cancel button appeared
    const cancelBtn = page.getByRole('button', { name: /CANCEL BATCH SEQUENCE/i });
    await expect(cancelBtn).toBeVisible();
    await cancelBtn.click();

    // Verify cancellation toast and state
    await expect(page.getByText(/Batch sequence cancelled by operator/i)).toBeVisible();
    await expect(page.getByText('READY TO FIRE')).toBeVisible();
  });

  test('BAT-06: navigates to PBR processing from completed batch shortcuts', async ({ page }) => {
    const processLinks = page.getByRole('link', { name: /Process PBR/i });
    await expect(processLinks.first()).toBeVisible();
    await processLinks.first().click();

    await expect(page).toHaveURL(/\/processing\?batch=/);
    await expect(page.getByText('PBR SYNTHESIS LAB')).toBeVisible();
  });
});
