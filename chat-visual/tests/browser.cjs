const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require(process.env.AT_CHAT_PLAYWRIGHT);

(async () => {
  const [project, url, python] = process.argv.slice(2);
  const browser = await chromium.launch({ channel: process.env.AT_CHAT_BROWSER || "msedge", headless: true });
  try {
    for (const entry of [pathToFileURL(path.resolve(__dirname, "../index.html")).href, url]) {
      const page = await browser.newPage();
      const errors = [], requests = [];
      page.on("request", req => requests.push(req.url()));
      page.on("console", (msg) => {
        if (msg.type() === "error" && !(msg.location().url.endsWith("/pick") && msg.text().includes("409"))) errors.push(msg.text());
      });
      page.on("pageerror", (e) => errors.push(e.message));
      // Exercise the real HTML directory-upload fallback, including Chinese paths.
      if (entry.startsWith("file:"))
        await page.addInitScript(() => {
          window.showDirectoryPicker = undefined;
        });
      await page.goto(entry);
      if (entry.startsWith("file:")) {
        const choose = page.waitForEvent("filechooser");
        await page.locator("#open").click();
        await (await choose).setFiles(project);
      }
      try {
        await page.getByText(/全项目 2 项待办/).waitFor({ timeout: 5000 });
      } catch (error) {
        console.error(entry, errors, await page.locator("body").innerText());
        throw error;
      }
      await page.selectOption("#role", "验收人");
      await page.getByText(/当前显示 1 项/).waitFor();
      await page.locator(".row").first().click();
      await page.getByRole("heading", { name: "需求详情" }).waitFor();
      await page.getByRole("button", { name: /预览 AT_/ }).click();
      await page.locator("dialog[open]").waitFor();
      assert.match(await page.locator("#fileInfo").innerText(), /需求已流转/);
      assert.match(await page.locator("#fileBody").innerText(), /坦克碰撞/);
      await page.locator("#close").click();
      await page.selectOption("#role", "");
      if (!entry.startsWith("file:")) {
        const eventPanel = page.locator("details").filter({hasText: "流转与追加记录"});
        await eventPanel.locator("summary").click();
        const original = page.locator(".msgbody p").first();
        await original.evaluate(p => {
          const range = document.createRange();
          range.selectNodeContents(p);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          p.closest("article").querySelector("button").focus({preventScroll: true});
        });
        const selected = await page.evaluate(() => window.getSelection().toString());
        const focused = await page.evaluate(() => document.activeElement.textContent);
        assert.ok(selected.length);
        function command(name, fields) {
          const script = path.resolve(__dirname, "../../skills/at-receive-message/scripts/at_chat.py");
          require("node:child_process").execFileSync(python, ["-B", "-X", "utf8", script, name,
            "--root", project, "--input", "-"], {input: JSON.stringify({role:"工程师", ...fields})});
        }
        command("create-group", {slug:"secondary", title:"另一协作群"});
        command("send", {group_id:"topic:secondary", kind:"info_sync", sender_model:"gpt", to:["验收人"],
          body:"跨群检索关键字", idempotency_key:"search"});
        await page.waitForFunction(() => document.getElementById("inboxCount").textContent === "3");
        assert.equal(await eventPanel.evaluate(node => node.open), true);
        assert.equal(await page.evaluate(() => window.getSelection().toString()), selected);
        assert.equal(await page.evaluate(() => document.activeElement.textContent), focused);
        assert.ok(requests.some(route => route.endsWith("/overview")));
        assert.ok(requests.some(route => route.includes("/groups/")));
        await page.locator("#search").fill("跨群检索关键字");
        await page.locator(".msgbody").filter({hasText:"跨群检索关键字"}).waitFor();
      }
      await page.setViewportSize({ width: 390, height: 820 });
      assert.equal(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth), true);
      if (!entry.startsWith("file:")) {
        if (process.env.AT_CHAT_TEST_PICKER) {
          const pick = status => page.waitForResponse(r => r.url().endsWith("/pick") && r.status() === status);
          const first = pick(200), busy = pick(409);
          await page.locator("#open").dblclick();
          await busy;
          assert.equal((await (await first).json()).cancelled, true);
          assert.equal(await page.locator("#search").inputValue(), "跨群检索关键字");
        }
        await page.locator("#remove").click();
        await page.getByText("打开含 AT.json 的项目目录，查看角色待办。").waitFor();
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
