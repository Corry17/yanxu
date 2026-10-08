import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";

test("离线包迁移、逐页讲解、无 JS、窄屏与打印", async ({ browser }, info) => {
  const output = execFileSync(
    path.resolve(".venv/bin/python"),
    [path.resolve("tests/export_fixture.py"), info.outputPath("fixture")],
    { encoding: "utf8", timeout: 60000 },
  );
  const entry = JSON.parse(output).entry;
  const url = pathToFileURL(entry).href;
  const context = await browser.newContext({
    offline: true,
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(url);
  await expect(page.locator(".page.current")).toContainText("问题与贡献");
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.locator(".page.current")).toContainText("缩放点积注意力");
  await expect(page.locator(".page.current svg").first()).toBeVisible();
  await page.locator(".step").nth(1).click();
  await expect(page.locator('[data-term="1"]')).toHaveClass("active");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".page.current")).toContainText("辅助教学图");
  expect(
    await page
      .locator(".page.current img")
      .evaluateAll((images) =>
        images.every((i) => (i as HTMLImageElement).naturalWidth > 0),
      ),
  ).toBe(true);
  await page.keyboard.press("End");
  await expect(page.locator(".page.current")).toContainText("证据与原始资料");
  await page.emulateMedia({ media: "print" });
  const visible = await page
    .locator(".page")
    .evaluateAll((pages) =>
      pages.every((p) => getComputedStyle(p).display !== "none"),
    );
  expect(visible).toBe(true);
  await page.pdf({
    path: info.outputPath("print.pdf"),
    format: "A4",
    printBackground: true,
  });
  await context.close();
  const noJS = await browser.newContext({
    offline: true,
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  const plain = await noJS.newPage();
  await plain.goto(url);
  await expect(plain.getByText("先认清每一个符号")).toBeVisible();
  await expect(plain.locator("img").first()).toBeVisible();
  expect(
    await plain.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await plain.getByRole("link", { name: "打开随包资料索引" }).click();
  await expect(plain.getByRole("heading", { level: 1 })).toContainText(
    "相关资料",
  );
  await noJS.close();
  expect(errors).toEqual([]);
});
