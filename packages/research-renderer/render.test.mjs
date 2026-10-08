import test from "node:test";
import assert from "node:assert/strict";
import { equation, render, esc } from "./render.mjs";

test("公式静态 SVG，不依赖浏览器脚本或在线字体", () => {
  const result = equation("\\frac{x}{\\sqrt{d}}");
  assert.ok(result.includes("<svg"));
  assert.ok(!/href="https?:|<script/.test(result));
});
test("不允许活动 LaTeX 扩展", () => {
  for (const input of [
    "\\href{javascript:alert(1)}{a}",
    "\\require{html}",
    "\\def\\x{\\x}",
  ]) {
    assert.throws(() => equation(input));
  }
});
test("用户文本按上下文转义", () => {
  const result = render({
    title: "<script>alert(1)</script>",
    kind: "weekly",
    style: "academic",
    mode: "scroll",
    sections: [
      {
        type: "text",
        label: "<img onerror=bad>",
        content: { text: "<img src=x onerror=bad>", items: [] },
      },
    ],
    evidence: [],
  });
  assert.ok(!result.includes("<img src=x"));
  assert.ok(result.includes("&lt;script&gt;"));
  assert.ok(result.includes("@media print"));
});
test("成品正文无脚本仍可见", () => {
  const result = render({
    title: "记录",
    kind: "weekly",
    style: "paper",
    mode: "deck",
    sections: [
      {
        type: "text",
        label: "观察",
        content: { text: "证据先于结论", items: [] },
      },
    ],
    evidence: [],
  });
  assert.ok(result.includes("证据先于结论"));
  assert.ok(!result.includes('class="deck-ready"'));
});
