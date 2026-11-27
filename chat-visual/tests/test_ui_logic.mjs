import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import ui from "../ui.js";
import markdownit from "../../dev-visual/vendor/markdown-it.min.js";

test("per-recipient state and sender filters", () => {
  const msg = {sender: "甲", recipients: {乙: {status: "handled"}, 丙: {status: "pending"}}, overall_status: "partial"};
  assert.equal(ui.statusOf(msg, "乙"), "handled");
  assert.equal(ui.attention(msg, "乙"), "");
  assert.equal(ui.attention(msg, "丙"), "unread");
  assert.equal(ui.attention(msg, "甲"), "outgoing");
  msg.overall_status = "handled";
  assert.equal(ui.statusOf(msg, "甲"), "handled");
  assert.equal(ui.attention(msg, "甲"), "");
});

test("all message kinds and model families have badge styles", async () => {
  const css = await readFile(new URL("../style.css", import.meta.url), "utf8");
  assert.equal(Object.keys(ui.kinds).length, 5);
  assert.equal(Object.keys(ui.models).length, 6);
  for (const name of [...Object.keys(ui.kinds), ...Object.keys(ui.models)]) assert.ok(css.includes("." + name));
});

test("message Markdown renders formatting and treats embedded HTML as text", () => {
  const html = ui.renderer(markdownit).render("**确认** <strong>原文</strong> [依据](https://example.org)");
  assert.match(html, /<strong>确认<\/strong>/);
  assert.match(html, /&lt;strong&gt;原文/);
  assert.doesNotMatch(html, /<a /);
});

test("file mode keeps healthy groups when a workspace directory is missing", async () => {
  const js = await readFile(new URL("../local.js", import.meta.url), "utf8");
  const local = vm.runInNewContext(js + "\nLocalChat", {DOMException});
  const data = {id: "demo", format: "agent-team/v3", team_repo: "public/game", members: [{name: "甲", dir: "AT_甲"}]};
  const files = new Map([["AT.json", data]]);
  const src = {
    async list() { throw new DOMException("missing", "NotFoundError"); },
    async file(path) {
      if (!files.has(path)) throw new DOMException("missing", "NotFoundError");
      return {text: async () => JSON.stringify(files.get(path))};
    },
  };
  assert.equal((await local.load(src)).initialized, false);
  const group = {format: "agent-team/chat-group-v1", group_id: "topic:qa", title: "协作", kind: "topic", task_id: null,
    messages: [{group_id: "topic:qa", id: "MSG-000001", seq: 1, kind: "info_sync", created_at: "now", sender: "乙",
      sender_model: "gpt", model_family: "gpt", idempotency_key: "once", reply_to: null, refs: [], to: ["甲"],
      recipients: {甲: {status: "pending"}}, overall_status: "pending", body: "字".repeat(161)}]};
  const meta = {format: "agent-team/chat-v1", project_id: "demo", next_seq: 2, groups: [{group_id: "topic:qa", file: "topic__qa.json"}]};
  files.set("public/chat/meta.json", meta);
  files.set("public/chat/groups/topic__qa.json", group);
  const result = await local.load(src);
  assert.equal(result.pending_total, 1);
  assert.ok(result.warnings.some(w => w.includes("AT_甲/workspace")));
  assert.equal(result.pending_items[0].preview.length, 160);
  const second = structuredClone(group);
  second.group_id = second.messages[0].group_id = "topic:qb";
  meta.groups.push({group_id: "topic:qb", file: "topic__qb.json"});
  files.set("public/chat/groups/topic__qb.json", second);
  assert.equal((await local.load(src)).groups.length, 0);
});
