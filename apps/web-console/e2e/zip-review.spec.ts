import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "playwright/test";

const worktreeDataDir = resolve(import.meta.dirname, "../../../.figma-to-fgui");

test.afterAll(() => expect(existsSync(worktreeDataDir)).toBe(false));

function crc32(data: Uint8Array): number {
  let value = 0xffffffff;
  for (const byte of data) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  }
  return (value ^ 0xffffffff) >>> 0;
}

function zipFixture(entries: Record<string, string>): Buffer {
  const encoder = new TextEncoder();
  const bytes: number[] = [];
  const central: number[] = [];
  const write = (target: number[], value: number, width: number) => {
    for (let index = 0; index < width; index += 1) target.push((value >>> (index * 8)) & 0xff);
  };
  for (const [name, content] of Object.entries(entries)) {
    const nameBytes = encoder.encode(name);
    const contentBytes = encoder.encode(content);
    const offset = bytes.length;
    const checksum = crc32(contentBytes);
    write(bytes, 0x04034b50, 4); write(bytes, 20, 2); write(bytes, 0, 2); write(bytes, 0, 2);
    write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, checksum, 4); write(bytes, contentBytes.length, 4); write(bytes, contentBytes.length, 4);
    write(bytes, nameBytes.length, 2); write(bytes, 0, 2); bytes.push(...nameBytes, ...contentBytes);
    write(central, 0x02014b50, 4); write(central, 20, 2); write(central, 20, 2); write(central, 0, 2); write(central, 0, 2);
    write(central, 0, 2); write(central, 0, 2); write(central, checksum, 4); write(central, contentBytes.length, 4); write(central, contentBytes.length, 4);
    write(central, nameBytes.length, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 2); write(central, 0, 4); write(central, offset, 4); central.push(...nameBytes);
  }
  const centralOffset = bytes.length;
  bytes.push(...central);
  write(bytes, 0x06054b50, 4); write(bytes, 0, 2); write(bytes, 0, 2); write(bytes, Object.keys(entries).length, 2); write(bytes, Object.keys(entries).length, 2); write(bytes, central.length, 4); write(bytes, centralOffset, 4); write(bytes, 0, 2);
  return Buffer.from(bytes);
}

test("designer uploads, reviews, and approves a complete ZIP update", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles({
    name: "GameUI.zip",
    mimeType: "application/zip",
    buffer: zipFixture({
      "Sample/package.xml": "<package id='sample01'><resources/></package>",
      "Sample/Panel/Panel_Sample_Main.xml": "<component name='uploaded'/>",
    }),
  });
  await expect(page.getByText("GameUI.zip")).toBeVisible();
  await page.getByTestId("create-review").click();
  await expect(page.locator(".review-workspace")).toBeVisible();
  await expect(page.locator(".change-button").first()).toBeVisible();
  await page.locator(".change-button").first().click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".mobile-review-note")).toBeVisible();
  await expect(page.locator(".review-action-buttons")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 900 });
  const advanced = page.locator(".advanced-button");
  await advanced.click();
  await expect(advanced).toHaveAttribute("aria-expanded", "true");
  await advanced.click();
  await expect(advanced).toHaveAttribute("aria-expanded", "false");
  await page.locator(".review-action-buttons .primary-button").click();
  await page.locator("[role=dialog] .primary-button").click();
  await expect(page.locator(".review-success")).toContainText("正在等待本地助手处理");
});
