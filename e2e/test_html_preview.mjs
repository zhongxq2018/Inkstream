/**
 * HTML 预览功能 E2E 测试（Playwright）
 * 用法: node e2e/test_html_preview.mjs
 */
import { chromium } from "playwright";
import { createServer } from "http";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = join(__dirname, "..", "static");
const PORT = 8765;
const BASE = `http://127.0.0.1:${PORT}`;

const SAMPLE_HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>测试页</title>
  <style>body{background:#f3f4f6;color:#1f2937;padding:24px;font-family:sans-serif}h1{color:#4f46e5}</style>
</head>
<body>
  <h1>本地模型部署全景</h1>
  <p id="status">预览测试成功</p>
</body>
</html>`;

const ASSISTANT_REPLY = `这是 HTML 预览自动化测试。

\`\`\`html
${SAMPLE_HTML}
\`\`\`
`;

function startStaticServer() {
  const mime = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
  };

  return new Promise((resolve) => {
    const server = createServer((req, res) => {
      const path = req.url === "/" ? "/index.html" : req.url;
      const filePath = join(STATIC_DIR, path.split("?")[0].replace(/^\//, ""));
      try {
        const data = readFileSync(filePath);
        const ext = filePath.slice(filePath.lastIndexOf("."));
        res.writeHead(200, { "Content-Type": mime[ext] || "application/octet-stream" });
        res.end(data);
      } catch {
        res.writeHead(404).end("Not found");
      }
    });
    server.listen(PORT, "127.0.0.1", () => resolve(server));
  });
}

function sseBody(text) {
  const chunkSize = 48;
  let body = "";
  for (let i = 0; i < text.length; i += chunkSize) {
    body += `data: ${JSON.stringify({ text: text.slice(i, i + chunkSize) })}\n\n`;
  }
  body += "data: [DONE]\n\n";
  return body;
}

async function runTest(name, fn) {
  try {
    await fn();
    console.log(`✓ ${name}`);
    return true;
  } catch (err) {
    console.error(`✗ ${name}`);
    console.error(`  ${err.message}`);
    return false;
  }
}

async function launchBrowser() {
  const launchOpts = { headless: true };
  for (const channel of ["chrome", "msedge"]) {
    try {
      return await chromium.launch({ ...launchOpts, channel });
    } catch {
      /* try next channel */
    }
  }
  return chromium.launch(launchOpts);
}

async function main() {
  const server = await startStaticServer();
  const browser = await launchBrowser();
  const context = await browser.newContext();
  const page = await context.newPage();

  const results = [];

  // 1. preview-test.html 自测页
  results.push(
    await runTest("preview-test.html 自动验证", async () => {
      await page.goto(`${BASE}/preview-test.html`, { waitUntil: "networkidle" });
      await page.waitForSelector("#result .ok, #result .fail", { timeout: 10000 });
      const ok = await page.locator("#result .ok").count();
      if (!ok) {
        const text = await page.locator("#result").textContent();
        throw new Error(text || "自测未通过");
      }
    }),
  );

  // 2. index.html 完整预览弹窗流程（mock API）
  results.push(
    await runTest("index.html 弹窗预览（mock 流式回复）", async () => {
      await page.route("**/health", (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "ok",
            model: "test",
            device: "cpu",
            local_ip: "127.0.0.1",
            port: PORT,
          }),
        }),
      );

      await page.route("**/chat/stream", (route) =>
        route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache", Connection: "keep-alive" },
          body: sseBody(ASSISTANT_REPLY),
        }),
      );

      await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
      await page.waitForSelector("#statusDot.online, .status-dot.online", { timeout: 10000 }).catch(() => {});

      await page.fill("#input", "生成 HTML 预览测试页面");
      await page.click("#sendBtn");

      const previewBtn = page.locator('.btn-code-action[data-action="preview"]');
      await previewBtn.waitFor({ state: "visible", timeout: 15000 });
      await previewBtn.click();

      const modal = page.locator("#htmlPreviewModal.open");
      await modal.waitFor({ state: "visible", timeout: 5000 });

      const frame = page.frameLocator("#htmlPreviewFrame");
      await frame.locator("h1").waitFor({ state: "visible", timeout: 10000 });
      const h1 = await frame.locator("h1").textContent();
      const status = await frame.locator("#status").textContent();
      if (h1?.trim() !== "本地模型部署全景") {
        throw new Error(`iframe h1 不匹配: ${h1}`);
      }
      if (status?.trim() !== "预览测试成功") {
        throw new Error(`iframe 状态文本不匹配: ${status}`);
      }

      await page.click("#htmlPreviewClose");
      await modal.waitFor({ state: "hidden", timeout: 3000 });
    }),
  );

  // 3. 新标签页打开
  results.push(
    await runTest("index.html 新标签页打开", async () => {
      const previewBtn = page.locator('.btn-code-action[data-action="preview"]');
      await previewBtn.waitFor({ state: "visible", timeout: 5000 });

      const [popup] = await Promise.all([
        context.waitForEvent("page"),
        page.locator('.btn-code-action[data-action="newtab"]').click(),
      ]);

      await popup.waitForLoadState("domcontentloaded");
      const h1 = await popup.locator("h1").textContent();
      if (h1?.trim() !== "本地模型部署全景") {
        throw new Error(`新标签页 h1 不匹配: ${h1}`);
      }
      await popup.close();
    }),
  );

  await browser.close();
  server.close();

  const passed = results.filter(Boolean).length;
  const total = results.length;
  console.log(`\n${passed}/${total} 项测试通过`);
  process.exit(passed === total ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
