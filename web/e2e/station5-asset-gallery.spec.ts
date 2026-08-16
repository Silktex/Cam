import { test, expect } from '@playwright/test';

test.describe('Station 5: Asset Gallery & High-Res Inspection Lightbox', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/gallery?folder=batch_silk_velvet_4355');
  });

  test('GAL-01: renders 61.0 MP RAW image and EXIF metadata telemetry', async ({ page }) => {
    await expect(page.getByText(/9504 x 6336 px • 61\.0 MP Uncompressed RAW/i)).toBeVisible();

    // EXIF Telemetry card
    await expect(page.getByText('EXIF Hardware Telemetry')).toBeVisible();
    await expect(page.getByText('Sony ILCE-7RM3')).toBeVisible();
    await expect(page.getByText('FE 90mm F2.8 Macro G OSS')).toBeVisible();
    await expect(page.getByText('1/125s • f/8.0 • ISO 100')).toBeVisible();
    await expect(page.getByText('90.0 mm')).toBeVisible();
    await expect(page.getByText('sRGB (Calibrated D65)')).toBeVisible();
  });

  test('GAL-02: switches view modes between 100% 1:1 Pixel View and Fit to Screen', async ({ page }) => {
    const fitBtn = page.getByRole('button', { name: 'Fit to Screen' });
    await expect(fitBtn).toBeVisible();
    await fitBtn.click();
    await expect(page.getByText(/Fit to Screen Mode: ENABLED/i)).toBeVisible();

    const pixelBtn = page.getByRole('button', { name: '100% 1:1 Pixel View' });
    await expect(pixelBtn).toBeVisible();
    await pixelBtn.click();
    await expect(page.getByText(/100% 1:1 Pixel Loupe Mode: ENABLED/i)).toBeVisible();
  });

  test('GAL-03: switches directional light angles via 9-light toolbar', async ({ page }) => {
    // Switch to Light #3 (E)
    const light3Btn = page.getByRole('button', { name: '3', exact: true });
    await expect(light3Btn).toBeVisible();
    await light3Btn.click();

    // Verify view updated
    await expect(page.getByRole('heading', { name: 'sample_posh_4355_3.ARW' })).toBeVisible();
    await expect(page.getByText(/Switched view to Side Spot #3/i)).toBeVisible();

    // Switch to Light #7 (W)
    const light7Btn = page.getByRole('button', { name: '7', exact: true });
    await light7Btn.click();
    await expect(page.getByRole('heading', { name: 'sample_posh_4355_7.ARW' })).toBeVisible();
  });

  test('GAL-04: filters archive via Meilisearch input query', async ({ page }) => {
    const searchInput = page.getByPlaceholder(/Search SKU, fabric, batch/i);
    await expect(searchInput).toBeVisible();
    await searchInput.fill('Mohair Velvet');
    await expect(searchInput).toHaveValue('Mohair Velvet');
  });

  test('GAL-05: downloads RAW+TIFF batch set and navigates to PBR processing', async ({ page }) => {
    const downloadBtn = page.getByRole('button', { name: /Download RAW \+ TIFF Set/i });
    await expect(downloadBtn).toBeVisible();
    await downloadBtn.click();
    await expect(page.getByText(/Downloading batch_silk_velvet_4355_raw_set\.zip/i)).toBeVisible();

    const pbrLink = page.getByRole('link', { name: /Send Batch to PBR Processing/i });
    await expect(pbrLink).toBeVisible();
    await pbrLink.click();
    await expect(page).toHaveURL(/\/processing/);
  });
});
