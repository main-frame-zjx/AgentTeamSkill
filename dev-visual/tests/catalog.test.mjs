import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCatalog, matchesSearch } from "../catalog.mjs";

test("a refresh reflects disk changes while the relation index can be rebuilt separately", () => {
  const source = { document: "first/SKILL.md", markdown: "---\nname: first\ndescription: 原简介\n---\n原正文" };
  const evidence = [{ condition: "交付后", quote: "交付后调用 second。", source: source.document }];
  const row = { name: "first", description: "索引旧简介", category: "执行", next: [] };
  const relations = { categories: ["准备", "执行"], skills: [row] };
  const docs = [source];
  const refresh = () => buildCatalog(docs, relations);

  assert.deepEqual(refresh().categories, ["执行"]);
  const added = { document: "draft/SKILL.md", markdown: "---\nname: second\ndescription: 新建\n---\n草稿正文" };
  docs.push(added);
  let catalog = refresh();
  assert.deepEqual(catalog.categories, ["执行", "未分类"]);
  assert.equal(catalog.skills[1].document, "draft/SKILL.md");
  assert.equal(catalog.skills[1].next, null);
  assert.equal(matchesSearch(catalog.skills[1], "草稿正文"), true);

  source.markdown = "\uFEFF---\r\nname: first\r\ndescription: >-\r\n  新简介\r\n  第二行\r\n---\r\n交付后调用 second。";
  catalog = refresh();
  assert.equal(catalog.skills[0].description, "新简介 第二行");
  assert.equal(matchesSearch(catalog.skills[0], "原正文"), false);
  assert.equal(matchesSearch(catalog.skills[0], "新简介"), true);
  assert.equal(matchesSearch(catalog.skills[0], "交付后调用"), true);

  relations.skills.unshift({ name: "second", category: "准备", next: [] });
  row.next = [{ target: "second", evidence }];
  catalog = refresh();
  assert.deepEqual(catalog.categories, ["准备", "执行"]);
  assert.deepEqual(catalog.skills.map(s => s.name), ["second", "first"]);
  assert.deepEqual(catalog.skills[0].next, []);
  assert.deepEqual(catalog.skills[1].next, row.next);

  docs.pop();
  catalog = refresh();
  assert.deepEqual(catalog.categories, ["执行"]);
  assert.deepEqual(catalog.skills.map(s => s.name), ["first"]);
  assert.deepEqual(catalog.skills[0].next, []);
  assert.equal(catalog.skills[0].removedTargets, true);
  assert.equal(row.next.length, 1);
});
