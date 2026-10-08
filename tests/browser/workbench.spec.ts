import { test, expect } from "@playwright/test";

test("教学材料 → 公式图解 → 科研报告 → 窄屏阅读", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  if (await page.getByRole("button", { name: "体验教学示例" }).isVisible()) {
    await page.getByRole("button", { name: "体验教学示例" }).click();
  }
  await expect(
    page.getByRole("heading", { name: "把注意力放回研究本身" }),
  ).toBeVisible();
  await page.screenshot({
    path: ".research/screenshots/home.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "精读工作台", exact: false })
    .first()
    .click();
  await expect(page.locator(".math-render svg").first()).toBeVisible();
  await page.getByRole("button", { name: "02", exact: true }).click();
  await expect(page.locator(".step-content")).toContainText("缩放");
  await page.screenshot({
    path: ".research/screenshots/formula.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "图片拆解", exact: true }).click();
  await page
    .getByRole("button", { name: "查看区域 2. / sqrt(d_k)", exact: true })
    .click();
  await expect(page.locator(".figure-details")).toContainText("单一变量");
  await expect(page.locator(".crop")).toBeVisible();
  await page.screenshot({
    path: ".research/screenshots/figure.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "代码对应", exact: true }).click();
  await expect(page.locator("pre").first()).toContainText("torch.softmax");
  await page.getByRole("button", { name: "汇报中心", exact: true }).click();
  await page.getByRole("button", { name: /学术白/ }).click();
  await page.locator(".source-options input[type=checkbox]").first().check();
  async function generateReport() {
    const submitted = page.waitForResponse(r => r.url().endsWith('/reports') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '生成离线 HTML 汇报' }).click();
    const response = await submitted;
    expect(response.ok()).toBe(true);
    const job = await response.json();
    const project = await page.getByLabel('切换研究项目').inputValue();
    let result: any;
    await expect.poll(async () => {
      const jobs = await (await context.request.get(`/api/projects/${project}/jobs`)).json();
      const current = jobs.find((j: any) => j.id === job.id);
      if (current?.status === 'failed') throw new Error(current.error);
      if (current?.result) result = JSON.parse(current.result);
      return current?.status;
    }, { timeout: 60000 }).toBe('done');
    const card = page.locator('.report-card').filter({ has: page.locator(`a[href*="${result.id}"]`) });
    await expect(card).toBeVisible();
    return card;
  }
  const paperReport = await generateReport();
  await page.screenshot({
    path: ".research/screenshots/reports.png",
    fullPage: true,
  });
  const popupPromise = page.waitForEvent("popup");
  await paperReport.getByRole("link", { name: "打开汇报" }).click();
  const report = await popupPromise;
  await report.waitForLoadState();
  await expect(report.locator("svg").first()).toBeVisible();
  await expect(report.locator("img").first()).toBeVisible();
  expect(
    await report
      .locator("img")
      .evaluateAll((images) =>
        images.every((i) => (i as HTMLImageElement).naturalWidth > 0),
      ),
  ).toBe(true);
  await report.screenshot({
    path: ".research/screenshots/report-paper.png",
    fullPage: true,
  });
  await report.close();
  await page.getByRole("button", { name: /实验复盘 假设/ }).click();
  await page.locator(".source-options input[type=checkbox]").first().check();
  await generateReport();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole("button", { name: "打开导航" }).click();
    await page
      .getByRole("button", { name: "精读工作台", exact: false })
      .first()
      .click();
    await expect(page.locator(".math-render svg").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({
      path: `.research/screenshots/mobile-${width}.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
});
