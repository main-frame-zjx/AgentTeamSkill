import { buildCatalog, matchesSearch, parseDocument } from "./catalog.mjs";

const $ = (selector) => document.querySelector(selector);
const page = $("#page");
const nav = $("#navigation");
const renderer = window.markdownit({ html: false });
let index;
let pending;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function viewURL(name, doc, fragment = "") {
  const url = new URL("/", location.origin);
  url.searchParams.set("skill", name);
  if (doc) url.searchParams.set("doc", doc);
  url.hash = fragment;
  return url;
}

function link(label, url, className) {
  const node = el("a", className, label);
  node.href = url;
  return node;
}

function documentURL(path) {
  return new URL("/docs/" + path.split("/").map(encodeURIComponent).join("/"), location.origin);
}

function currentSkill() {
  const requested = new URL(location.href).searchParams.get("skill");
  const name = requested ?? (index.skills.some(s => s.name === "at-init-team") ? "at-init-team" : index.skills[0]?.name);
  return index.skills.find(s => s.name === name);
}

function drawNav() {
  const current = currentSkill();
  const filter = $("#search").value.trim().toLowerCase();
  nav.replaceChildren();
  for (const category of index.categories) {
    const matches = index.skills.filter(s => s.category === category && matchesSearch(s, filter));
    if (!matches.length) continue;
    const group = el("section", "nav-group");
    group.append(el("h3", "", category));
    for (const skill of matches) {
      const item = link(skill.name, viewURL(skill.name), "nav-link");
      if (skill === current) item.setAttribute("aria-current", "page");
      group.append(item);
    }
    nav.append(group);
  }
  if (!nav.childElementCount) nav.append(el("p", "empty", "没有匹配的技能"));
}

function sectionTitle(title, count) {
  const head = el("div", "section-head");
  head.append(el("h2", "", title));
  if (count !== undefined) head.append(el("span", "count", String(count)));
  return head;
}

function relations(skill) {
  const section = el("section");
  section.id = "next";
  section.append(sectionTitle("后续可调用技能", skill.next?.length));
  if (skill.next === null) {
    section.append(el("p", "empty", "后续调用尚未整理"));
    return section;
  }
  for (const edge of skill.next) {
    const card = el("article", "relation");
    card.append(link(edge.target, viewURL(edge.target), "target"));
    for (const item of edge.evidence) {
      card.append(el("p", "condition", item.condition));
      const details = el("details", "evidence");
      const sourceURL = viewURL(skill.name, item.source === skill.document ? null : item.source);
      details.append(el("summary", "", "查看原文依据"), el("blockquote", "", item.quote),
                     link(item.source, sourceURL, "source"));
      card.append(details);
    }
    section.append(card);
  }
  if (!skill.next.length) {
    const message = skill.removedTargets ? "索引中的调用目标已移除" : "文档未声明后续调用";
    section.append(el("p", "empty", message));
  }
  return section;
}

function renderMarkdown(body, path, skill, primary) {
  const article = el("article", "markdown");
  article.innerHTML = renderer.render(body);
  const title = article.firstElementChild;
  const normalize = (text) => text.toLowerCase().replaceAll("_", "-");
  if (primary && title?.tagName === "H1" && normalize(title.textContent.trim()) === normalize(skill.name)) title.remove();
  const used = new Set(["next", "main", "page", "navigation", "directory", "sidebar", "total", "search", "mobile-toggle"]);
  for (const heading of article.querySelectorAll("h1,h2,h3,h4,h5,h6")) {
    const slug = heading.textContent.trim().toLowerCase().replace(/[^\p{L}\p{N}_ -]/gu, "").replace(/\s+/g, "-");
    let id = slug || "section";
    for (let n = 1; used.has(id); n++) id = (slug || "section") + "-" + n;
    heading.id = id;
    used.add(id);
  }
  for (const anchor of article.querySelectorAll("a[href]")) {
    const url = new URL(anchor.getAttribute("href"), documentURL(path));
    if (url.origin !== location.origin) {
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      continue;
    }
    if (!url.pathname.startsWith("/docs/") || !/\.md$/i.test(url.pathname)) {
      anchor.removeAttribute("href");
      continue;
    }
    const relative = decodeURIComponent(url.pathname.slice("/docs/".length));
    const owner = index.skills.find(s => s.document === relative);
    anchor.href = viewURL(owner?.name ?? skill.name, owner ? null : relative, url.hash);
  }
  return article;
}

function scrollToFragment() {
  if (!location.hash) return;
  let id;
  try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
  document.getElementById(id)?.scrollIntoView();
}

function showError(message) {
  page.replaceChildren(el("h1", "", "无法打开文档"), el("p", "notice", message));
}

async function readPage() {
  pending?.abort();
  const request = new AbortController();
  pending = request;
  drawNav();
  const skill = currentSkill();
  if (!skill) {
    showError(index.skills.length ? "磁盘目录中找不到这项技能。请从侧栏选择现有技能。" : "skills/ 下还没有技能文档。添加 SKILL.md 后刷新即可查看。");
    return;
  }
  const path = new URL(location.href).searchParams.get("doc") || skill.document;
  const primary = path === skill.document;
  try {
    const response = await fetch(documentURL(path), { signal: request.signal });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const raw = await response.text();
    if (request.signal.aborted) return;
    const { body, description } = parseDocument(path, raw);
    const article = renderMarkdown(body, path, skill, primary);
    const title = primary ? skill.name : (article.querySelector("h1")?.textContent || path.split("/").pop());
    const hero = el("header");
    const crumb = el("div", "crumb");
    crumb.append(primary ? el("span", "", skill.category) : link(skill.name, viewURL(skill.name)));
    hero.append(crumb, el("h1", "doc-title", title));
    if (primary) hero.append(el("p", "lead", description));
    else if (article.firstElementChild?.tagName === "H1") article.firstElementChild.remove();
    const meta = el("div", "meta");
    const source = link("skills/" + path, documentURL(path), "source");
    source.target = "_blank";
    source.rel = "noopener";
    source.title = "打开 Markdown 源文档";
    meta.append(source);
    if (primary) meta.append(link(skill.next === null ? "后续调用" : "后续调用 (" + skill.next.length + ")", "#next", "jump"));
    hero.append(meta);
    page.replaceChildren(hero, sectionTitle(primary ? "技能文档" : "参考文档"), article);
    if (primary) page.append(relations(skill));
    document.title = title + " · AgentTeam 技能手册";
    scrollToFragment();
  } catch (error) {
    if (request.signal.aborted) return;
    showError("无法读取 skills/" + path + "（" + error.message + "）。请核对文件路径，若文档已移动，请刷新目录。");
  }
}

function toggleDirectory(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#mobile-toggle").setAttribute("aria-expanded", String(open));
  $("#mobile-toggle").textContent = open ? "收起目录" : "展开目录";
}

$("#mobile-toggle").onclick = () => toggleDirectory(!$("#sidebar").classList.contains("open"));
$("#search").oninput = drawNav;

document.addEventListener("click", (event) => {
  const a = event.target.closest("a[href]");
  if (!a || a.target === "_blank" || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const url = new URL(a.href);
  if (url.origin !== location.origin || url.pathname !== "/" || !index) return;
  if (url.search === location.search && url.hash) return;
  event.preventDefault();
  if (url.href !== location.href) history.pushState(null, "", url);
  toggleDirectory(false);
  if (a.classList.contains("target") && $("#search").value) $("#search").value = "";
  window.scrollTo(0, 0);
  $("#main").focus({ preventScroll: true });
  readPage();
});
window.addEventListener("popstate", () => { if (index) readPage(); });

async function fetchJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(path + " HTTP " + response.status);
  return response.json();
}

async function readRelations() {
  try {
    const data = await fetchJSON("/skill-relation.json");
    if (!Array.isArray(data.categories) || !Array.isArray(data.skills) ||
        !data.skills.every(s => data.categories.includes(s.category) && Array.isArray(s.next))) {
      throw new Error("索引格式错误");
    }
    return data;
  } catch (error) {
    const warning = $("#index-warning");
    warning.textContent = "关系索引不可用（" + error.message + "）。运行 $update-skills-relation 可恢复分类和跳转。";
    warning.hidden = false;
    return { categories: [], skills: [] };
  }
}

async function init() {
  try {
    const [documents, relations] = await Promise.all([fetchJSON("/api/skill-documents"), readRelations()]);
    index = buildCatalog(documents, relations);
    $("#total").textContent = index.skills.length;
    await readPage();
  } catch (error) {
    showError("无法读取技能目录（" + error.message + "）。请检查 skills/ 和本地手册服务后刷新。");
  }
}
init();
