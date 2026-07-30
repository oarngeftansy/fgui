import { expect, test, type Page } from "playwright/test";

function pngFixture(): Buffer {
  return Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg==", "base64");
}

function crc32(data: Uint8Array): number {
  let value = 0xffffffff;
  for (const byte of data) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  }
  return (value ^ 0xffffffff) >>> 0;
}

function projectZip(): Buffer {
  const encoder = new TextEncoder();
  const bytes: number[] = [];
  const central: number[] = [];
  const write = (target: number[], value: number, width: number) => {
    for (let index = 0; index < width; index += 1) target.push((value >>> (index * 8)) & 0xff);
  };
  const entries = {
    "Sample/package.xml": "<package id='sample01'><resources/></package>",
    "Sample/Panel/Panel_Sample_LiveCheckout.xml": "<component name='old'/>",
    "Alternative/package.xml": "<package id='altern01'><resources/></package>",
    "Alternative/Panel/Panel_Alternative_LiveCheckout.xml": "<component name='old'/>",
  };
  for (const [name, content] of Object.entries(entries)) {
    const nameBytes = encoder.encode(name);
    const contentBytes = encoder.encode(content);
    const offset = bytes.length;
    const checksum = crc32(contentBytes);
    write(bytes, 0x04034b50, 4); write(bytes, 20, 2); write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, checksum, 4); write(bytes, contentBytes.length, 4); write(bytes, contentBytes.length, 4); write(bytes, nameBytes.length, 2); write(bytes, 0, 2); bytes.push(...nameBytes, ...contentBytes);
    write(central, 0x02014b50, 4); write(central, 20, 2); write(central, 20, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, checksum, 4); write(central, contentBytes.length, 4); write(central, contentBytes.length, 4); write(central, nameBytes.length, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 4); write(central, offset, 4); central.push(...nameBytes);
  }
  const centralOffset = bytes.length;
  bytes.push(...central);
  write(bytes, 0x06054b50, 4); write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, Object.keys(entries).length, 2); write(bytes, Object.keys(entries).length, 2); write(bytes, central.length, 4); write(bytes, centralOffset, 4); write(bytes, 0, 2);
  return Buffer.from(bytes);
}

async function simulatePluginUpload(page: Page, pairingCode: string): Promise<void> {
  const exchange = await page.request.post("/v1/figma/pairings/exchange", {
    data: { version: 1, code: pairingCode, device_name: "Chromium Figma plugin" },
  });
  expect(exchange.ok()).toBe(true);
  const credential = (await exchange.json()).credential as string;
  const headers = { Authorization: `Bearer ${credential}` };
  const created = await page.request.post("/v1/figma/selections/uploads", {
    data: { version: 1, idempotency_key: "chromium-live-selection" }, headers,
  });
  expect(created.status()).toBe(201);
  const uploadId = (await created.json()).upload_id as string;
  const png = pngFixture();
  const manifest = {
    version: 1,
    display_name: "LiveCheckout",
    top_level_nodes: [{
      id: "private-chromium-node",
      name: "LiveCheckout",
      type: "FRAME",
      bounds: { x: 0, y: 0, width: 600, height: 400 },
      resource_keys: ["asset-1"],
      children: [{ id: "private-chromium-text", name: "Button", type: "TEXT", bounds: { x: 20, y: 20, width: 100, height: 32 }, text: "Buy now" }],
    }],
    resources: [{ key: "asset-1", mime_type: "image/png", size: png.length }],
    warnings: [],
  };
  expect((await page.request.put(`/v1/figma/selections/uploads/${uploadId}/manifest`, { data: manifest, headers })).ok()).toBe(true);
  const uploadedResource = await page.request.put(`/v1/figma/selections/uploads/${uploadId}/resources/asset-1`, {
    data: png, headers: { ...headers, "Content-Type": "image/png" },
  });
  expect(uploadedResource.ok(), await uploadedResource.text()).toBe(true);
  expect((await page.request.post(`/v1/figma/selections/uploads/${uploadId}/commit`, { headers })).ok()).toBe(true);
}

test("designer continues a real live selection through review without network interception", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const pairingCode = await page.locator(".pairing-code").textContent();
  expect(pairingCode).toMatch(/^\d{6}$/);
  await simulatePluginUpload(page, pairingCode!);
  await expect(page.locator(".selection-summary")).toContainText("LiveCheckout", { timeout: 10_000 });

  await page.locator('input[type="file"]').setInputFiles({
    name: "GameUI.zip", mimeType: "application/zip", buffer: projectZip(),
  });
  await page.locator("#project-package").selectOption("Alternative");
  await page.getByTestId("create-review").click();
  const workspace = page.getByTestId("review-workspace");
  await expect(workspace).toBeVisible();
  expect(await workspace.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length)).toBe(3);
  const jobId = new URL(page.url()).pathname.split("/").at(-1)!;
  const previewResponse = await page.request.get(`/v1/jobs/${jobId}/designer-preview?details=advanced`);
  const preview = await previewResponse.json();
  expect(preview.preview.changes.length, JSON.stringify(preview)).toBeGreaterThan(0);
  await page.locator(".change-button").first().click();
  const advanced = page.locator(".advanced-button");
  await advanced.click();
  await expect(advanced).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".advanced-details")).toContainText("Alternative/Panel/Panel_Alternative_LiveCheckout.xml");
  await advanced.click();
  await expect(advanced).toHaveAttribute("aria-expanded", "false");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".mobile-review-note")).toBeVisible();
  await expect(page.locator(".review-action-buttons")).toBeHidden();
  const mobileLayout = await page.evaluate(() => ({
    fits: document.documentElement.scrollWidth <= window.innerWidth,
    overflow: Array.from(document.querySelectorAll("*")).filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1).map((element) => ({ tag: element.tagName, className: element.className, parentClassName: element.parentElement?.className, text: element.textContent, right: element.getBoundingClientRect().right })),
  }));
  expect(mobileLayout.fits, JSON.stringify(mobileLayout.overflow)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator(".review-action-buttons .primary-button").click();
  await page.locator("[role=dialog] .primary-button").click();
  await expect(page.locator(".review-success")).toContainText("已确认完整更新，正在等待本地助手处理。");
});
