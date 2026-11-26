import { FAILSAFE_SCHEMA, load } from "./vendor/js-yaml.mjs";

const unclassified = "未分类";

export function parseDocument(document, markdown) {
  const header = /^\uFEFF?---[ \t]*\r?\n([\s\S]*?)^---[ \t]*(?:\r?\n|$)/m;
  const match = header.exec(markdown);
  let metadata;
  let body = markdown;
  if (match?.index === 0) {
    body = markdown.slice(match[0].length);
    try {
      metadata = load(match[1], { schema: FAILSAFE_SCHEMA });
    } catch {
      // An unfinished frontmatter edit should still leave the document readable.
    }
  }
  const name = typeof metadata?.name === "string" && metadata.name.trim();
  const description = typeof metadata?.description === "string" ? metadata.description.trim() : "";
  return { name: name || document.split("/")[0], description, document, body };
}

export function buildCatalog(documents, relations) {
  const live = new Map();
  for (const { document, markdown } of documents) {
    const skill = parseDocument(document, markdown);
    if (live.has(skill.name)) {
      throw new Error("技能名重复：" + live.get(skill.name).document + "、" + document);
    }
    live.set(skill.name, skill);
  }
  const skills = [];
  const indexed = new Set();
  for (const row of relations.skills) {
    const skill = live.get(row.name);
    if (!skill || indexed.has(skill.name)) continue;
    const next = row.next.filter(edge => live.has(edge.target));
    skills.push({ ...skill, category: row.category, next, removedTargets: next.length < row.next.length });
    indexed.add(skill.name);
  }
  for (const skill of live.values()) {
    if (!indexed.has(skill.name)) skills.push({ ...skill, category: unclassified, next: null });
  }
  const present = new Set(skills.map(s => s.category));
  const categories = relations.categories.filter(c => c !== unclassified && present.has(c));
  if (present.has(unclassified)) categories.push(unclassified);
  return { categories, skills };
}

export function matchesSearch(skill, filter) {
  return [skill.name, skill.category, skill.description, skill.body].some(value => value.toLowerCase().includes(filter));
}
