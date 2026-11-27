"use strict";
const $ = (id) => document.getElementById(id);
const {kinds: names, models: families, statusOf, attention} = ChatUI;
const state = {tab: "inbox", id: null, local: null, view: null, group: null, generation: 0,
  cache: new Map(), detail: null, previewRequest: 0, loading: false};
const direct = location.protocol === "file:";
const markdown = ChatUI.renderer(window.markdownit);
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined && text !== null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function btn(text, action, cls) {
  const b = el("button", text, cls);
  b.onclick = event => Promise.resolve(action(event)).catch(report);
  return b;
}
function options(id, items) {
  const node = $(id),
    old = node.value;
  if (items.length === node.options.length && items.every(([v, label], i) =>
    node.options[i].value === v && node.options[i].text === label)) return;
  node.replaceChildren(...items.map(([value, label]) => new Option(label, value)));
  if (items.some(([v]) => v === old)) node.value = old;
}
function report(err) {
  if (err.name !== "AbortError") $("warnings").replaceChildren(el("p", err.message, "warning"));
}
function time(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "";
}
function waiting(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60000));
  if (minutes < 60) return minutes + " 分钟";
  if (minutes < 1440) return Math.floor(minutes / 60) + " 小时";
  return Math.floor(minutes / 1440) + " 天";
}
function badge(text, cls = "") {
  return el("span", text, "chip " + cls);
}
function searchable(g, m) {
  if ($("model").value && m?.sender_model !== $("model").value) return false;
  if ($("version").value && g.task?.version !== $("version").value) return false;
  return [
    g.title,
    g.task?.code,
    g.task_id,
    g.task?.owner,
    g.task?.reviewer,
    m?.body,
    m?.sender,
    m?.sender_model,
    m?.id,
    ...(m?.to || []),
    ...(m?.refs || []).map((r) => r.path),
  ]
    .join(" ")
    .toLowerCase()
    .includes($("search").value.trim().toLowerCase());
}
async function go(gid, mid) {
  state.tab = "chat";
  state.group = gid;
  if (mid) {
    $("status").value = "";
    $("search").value = "";
    $("model").value = "";
  }
  await refresh();
  if (mid) {
    const card = $(mid);
    card?.scrollIntoView({ block: "center" });
    card?.classList.add("focus");
  }
}
function groupTitle(g) {
  return [g.task?.code, g.title].filter(Boolean).join(" · ");
}

function inbox(view) {
  const groups = new Map(view.groups.map((g) => [g.group_id, g]));
  const role = $("role").value;
  const items = view.pending_items.filter((p) => {
    const g = groups.get(p.group_id);
    return (
      (!role || p.recipient === role) &&
      g &&
      searchable(
        g,
        g.messages?.find((m) => m.id === p.message_id) || p,
      )
    );
  });
  const result = el("section");
  result.append(el("p", `全项目 ${view.pending_total} 项待办 · 当前显示 ${items.length} 项`, "summary"));
  if (!items.length) {
    result.append(el("div", view.pending_total ? "没有符合筛选条件的待办" : !view.initialized ? "此项目尚未启用角色通讯" : view.warnings.length ? "可读取的群组中没有待办" : "全队待办已清零", "empty"));
    return result;
  }
  const matrix = el("div", null, "matrix");
  for (const recipient of new Set(items.map((p) => p.recipient))) {
    const panel = el("section", null, "panel"),
      mine = items.filter((p) => p.recipient === recipient);
    panel.dataset.key = recipient;
    panel.append(el("h2", recipient + " · " + mine.length));
    for (const p of mine) {
      const row = btn("", () => go(p.group_id, p.message_id), "row");
      row.dataset.key = p.message_id;
      row.append(
        badge("P" + p.priority, "pending"),
        badge(names[p.kind], p.kind),
        el("strong", " " + groupTitle(groups.get(p.group_id))),
        el("div", p.preview),
        el("small", p.sender + " · " + p.sender_model + " · 已等待 " + waiting(p.created_at)),
      );
      panel.append(row);
    }
    matrix.append(panel);
  }
  result.append(matrix);
  return result;
}
async function filePreview(ref, g) {
  const ticket = ++state.previewRequest;
  let path = ref.path;
  const read = async (p) =>
    state.local
      ? LocalChat.preview(state.local, p)
      : await request("/api/projects/" + state.id + "/file?path=" + encodeURIComponent(p) + (ref.lines ? "&lines=" + encodeURIComponent(ref.lines) : ""));
  const latest = g.task?.path,
    a = path.split("/"),
    b = latest?.split("/") || [];
  if (latest && a.length === 4 && b.length === 4 && a[0] === b[0] && a[1] === "workspace" && a[3] === b[3])
    path = latest;
  const f = await read(path);
  if (ticket !== state.previewRequest) return;
  $("fileTitle").textContent = path;
  $("fileInfo").textContent = [
    path !== ref.path ? "需求已流转，显示当前位置" : "",
    ref.note,
    f.truncated ? "内容截取前 256 KB" : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const [first, last] = f.highlight || String(ref.lines || "")
    .split("-")
    .map(Number);
  const pre = $("fileBody");
  const fragment = document.createDocumentFragment();
  for (const [i, line] of f.content.split(/\r?\n/).entries()) {
    const highlight = first && i + 1 >= first && i + 1 <= (last || first);
    fragment.append(el("span", String(i + 1).padStart(4) + "  " + line, highlight ? "line" : ""));
  }
  pre.replaceChildren(fragment);
  if (!$("preview").open) $("preview").show();
  document.body.classList.add("previewing");
  const highlighted = pre.querySelector(".line");
  pre.scrollTop = highlighted ? highlighted.offsetTop - pre.offsetTop - pre.clientHeight / 2 : 0;
}
function card(g, m, role) {
  const box = el("article", null, attention(m, role));
  box.id = m.id;
  const meta = el("div", null, "meta");
  meta.append(
    el("strong", m.sender),
    badge((families[m.model_family] || families.other) + " · " + m.sender_model, m.model_family),
    badge(names[m.kind], m.kind),
    el("small", m.id + " · " + time(m.created_at)),
  );
  if (box.className === "outgoing") meta.append(el("small", "等接收者处理"));
  box.append(meta);
  if (m.reply_to)
    box.append(
      btn(
        "↩ " + m.reply_to,
        () => {
          $("role").value = "";
          go(g.group_id, m.reply_to);
        },
        "ref",
      ),
    );
  const body = el("div", null, "msgbody");
  if (markdown) body.innerHTML = markdown.render(m.body);
  else body.textContent = m.body;
  box.append(body);
  for (const [recipient, r] of Object.entries(m.recipients)) {
    const row = el("div", null, "meta");
    row.append(badge(recipient + " · " + (r.status === "handled" ? "已处理" : "未处理"), r.status));
    if (r.blocked) row.append(el("small", "受阻 · " + r.blocked.note + " · " + r.blocked.model));
    if (r.status === "handled")
      row.append(
        el(
          "small",
          [r.resolution, r.resolution_note, r.handled_by_model, time(r.handled_at)]
            .filter(Boolean)
            .join(" · "),
        ),
      );
    box.append(row);
  }
  for (const r of m.refs) {
    box.append(
      btn("预览 " + r.path + (r.lines ? " · " + r.lines : ""), () => filePreview(r, g), "ref"),
      btn("复制路径", async event => {
        const button = event.currentTarget;
        try {
          await navigator.clipboard.writeText(r.path);
          button.textContent = "已复制 ✓";
        } catch {
          button.textContent = "复制失败，请选中路径复制";
        }
        setTimeout(() => { button.textContent = "复制路径"; }, 2000);
      }, "ref"),
    );
  }
  return box;
}
function chat(view) {
  const role = $("role").value,
    status = $("status").value;
  const matches = (m) =>
    (!role || m.to.includes(role) || m.sender === role) && (!status || status === statusOf(m, role));
  const visible = view.groups.filter(
    (g) => (!role && !status && searchable(g)) || (g.messages || []).some((m) => matches(m) && searchable(g, m)),
  );
  const pending = (g) =>
    role ? (g.messages || []).filter((m) => m.recipients[role]?.status === "pending").length : g.pending_count;
  visible.sort(
    (a, b) =>
      Number(pending(b) > 0) - Number(pending(a) > 0) ||
      Number(a.archived) - Number(b.archived) ||
      String(b.last_message_at || "").localeCompare(String(a.last_message_at || "")),
  );
  const g = visible.find((x) => x.group_id === state.group) || visible[0];
  if (!g) return el("div", "暂无符合条件的群聊记录", "empty");
  state.group = g.group_id;
  const grid = el("div", null, "grid"),
    side = el("aside", null, "groups");
  const archived = el("details");
  archived.dataset.key = "archived";
  archived.append(el("summary", "已归档需求群"));
  let hasArchived = false;
  for (const row of visible) {
    const b = btn(groupTitle(row), () => go(row.group_id), "group" + (row === g ? " active" : ""));
    b.dataset.key = row.group_id;
    b.append(el("small", row.last_preview, "snippet"), el("small", time(row.last_message_at)));
    b.append(el("small", [row.task?.stage || "专题协作", pending(row) + " 项待办"].join(" · ")));
    if (row.archived && !pending(row)) {
      archived.append(b);
      hasArchived = true;
      if (row === g) archived.open = true;
    } else side.append(b);
  }
  if (hasArchived) side.append(archived);
  const center = el("section");
  center.append(el("h2", groupTitle(g)));
  center.dataset.key = g.group_id;
  if (g.task) center.append(el("p", [g.task.stage, "所属 " + g.task.owner, "验收 " + g.task.reviewer].join(" · "), "task-banner"));
  for (const m of (g.messages || []).filter((m) => matches(m) && searchable(g, m))) center.append(card(g, m, role));
  if (!g.message_count) center.append(el("p", "群中尚无消息", "empty"));
  const detail = el("aside", null, "context panel");
  detail.append(el("h2", g.task ? "需求详情" : "专题协作"));
  if (g.task) {
    const t = g.task;
    detail.append(
      badge(t.stage),
      el("p", t.owner + " → " + t.reviewer + " · " + t.version),
      el("p", t.goal),
      el("h3", "验收条件"),
    );
    const list = el("ol");
    for (const c of t.criteria) list.append(el("li", c));
    detail.append(list);
    if (t.events?.length) {
      const history = el("details");
      history.dataset.key = "events";
      history.append(el("summary", "流转与追加记录"));
      for (const e of t.events)
        history.append(el("p", [e.actor, e.to, e.reason].filter(Boolean).join(" · ")));
      detail.append(history);
    }
  }
  detail.append(el("h3", "本群待办"));
  for (const p of view.pending_items.filter((p) => p.group_id === g.group_id))
    detail.append(
      btn(
        p.recipient + " · " + p.message_id,
        () => {
          $("role").value = "";
          go(g.group_id, p.message_id);
        },
        "ref",
      ),
    );
  grid.append(side, center, detail);
  return grid;
}
function render(passive = false) {
  const isInbox = state.tab === "inbox",
    view = state.view;
  $("title").textContent = isInbox ? "待办总览" : "群聊记录";
  $("inbox").setAttribute("aria-pressed", String(isInbox));
  $("chat").setAttribute("aria-pressed", String(!isInbox));
  $("status").hidden = isInbox;
  $("projectName").textContent = view
    ? view.project.name + " · " + view.project.current_version
    : "AgentTeam";
  $("inboxCount").textContent = view?.pending_total ?? 0;
  const content = $("content");
  const next = view ? (isInbox ? inbox(view) : chat(view))
                    : el("div", "打开含 AT.json 的项目目录，查看角色待办。", "empty");
  if (passive && content.firstElementChild) {
    const anchor = [...content.querySelectorAll("article, .row")].find(n => n.getBoundingClientRect().bottom > 0);
    const top = anchor?.getBoundingClientRect().top;
    ChatUI.patch(content.firstElementChild, next);
    if (anchor?.isConnected) window.scrollBy(0, anchor.getBoundingClientRect().top - top);
  } else content.replaceChildren(next);
}

async function request(path, opts = {}) {
  if (opts.method === "POST") opts.headers = {"X-Chat-Request": "1"};
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Error(data.error || "读取失败 (" + res.status + ")");
  return data;
}

async function refresh(passive = false) {
  if (passive && state.loading) return;
  const epoch = ++state.generation;
  state.loading = true;
  try { await loadView(epoch, passive); }
  finally { if (epoch === state.generation) state.loading = false; }
}

async function loadView(epoch, passive) {
  let view;
  if (state.local) view = await LocalChat.load(state.local);
  else if (state.id) {
    const base = "/api/projects/" + state.id;
    const filtered = $("search").value.trim() || $("model").value ||
      (state.tab === "chat" && ($("role").value || $("status").value || $("version").value));
    const endpoint = filtered ? "snapshot" : "overview";
    const cached = state.cache.get(endpoint);
    const res = await fetch(base + "/" + endpoint, {
      headers: cached ? {"If-None-Match": cached.tag} : {},
    });
    if (epoch !== state.generation) return;
    if (res.status === 304) {
      if (passive && state.view?.tag === cached.tag && state.view.endpoint === endpoint) return;
      view = cached.view;
    } else {
      view = await res.json();
      if (!res.ok) throw Error(view.error);
      if (epoch !== state.generation) return;
      state.cache.set(endpoint, {tag: res.headers.get("ETag"), view});
    }
    view = {...view, tag: state.cache.get(endpoint).tag, endpoint};
    if (endpoint === "overview" && state.tab === "chat" && view.groups.length) {
      const groups = [...view.groups].sort((a, b) => Number(!!b.pending_count) - Number(!!a.pending_count)
        || Number(a.archived) - Number(b.archived) || String(b.last_message_at || "").localeCompare(a.last_message_at || ""));
      const group = groups.find(g => g.group_id === state.group) || groups[0];
      if (!state.detail || state.detail.tag !== group.detail_tag || state.detail.data.group_id !== group.group_id) {
        const data = await request(base + "/groups/" + encodeURIComponent(group.group_id));
        if (epoch !== state.generation) return;
        state.detail = {tag: group.detail_tag, data};
      }
      view.groups = groups.map(g => g === group ? state.detail.data : g);
    }
  } else {
    render();
    return;
  }
  if (epoch !== state.generation) return;
  const prior = state.view?.groups.find(g => g.group_id === state.group);
  const readingHistory = passive && state.tab === "chat" &&
    window.scrollY + window.innerHeight < document.documentElement.scrollHeight - 48;
  state.view = view;
  options("role", [["", "全部角色"], ...view.project.roles.map((r) => [r, r])]);
  const models = view.stats?.models_seen || new Set(view.groups.flatMap((g) => g.messages.map((m) => m.sender_model)));
  const versions = new Set(view.groups.map((g) => g.task?.version).filter(Boolean));
  options("model", [["", "全部模型"], ...[...models].sort().map((m) => [m, m])]);
  options("version", [["", "全部版本"], ...[...versions].sort().map((v) => [v, v])]);
  $("warnings").replaceChildren(...view.warnings.map((w) => el("p", w, "warning")));
  render(passive);
  if (readingHistory && prior && view.groups.find(g => g.group_id === prior.group_id)?.message_count > prior.message_count)
    $("newMessages").hidden = false;
}

function resetProject() {
  ++state.generation;
  ++state.previewRequest;
  state.loading = false;
  state.cache.clear();
  state.view = state.group = state.detail = null;
  $("preview").close();
  $("newMessages").hidden = true;
  $("warnings").replaceChildren();
  for (const id of ["search", "role", "model", "version", "status"]) $(id).value = "";
}
async function projects(list) {
  list ||= await request("/api/projects");
  options(
    "project",
    list.projects.length ? list.projects.map((r) => [r.id, r.name]) : [["", "尚未打开项目"]],
  );
  state.id = list.active;
  $("project").value = list.active || "";
  resetProject();
  $("remove").hidden = !state.id;
  $("unavailable").replaceChildren(...(list.unavailable || []).map(row => {
    const line = el("div", row.root + " · 无法打开 ", "warning");
    line.append(btn("从列表移除", () => removeProject(row.id)));
    return line;
  }));
  render();
  await refresh();

}
$("open").onclick = async () => {
  try {
    if (direct) {
      const source = await LocalChat.pick();
      resetProject();
      state.local = source;
      await refresh();
      options("project", [["", state.view.project.name]]);
    } else {
      const list = await request("/api/projects/pick", {method: "POST"});
      if (!list.cancelled) await projects(list);
    }
  } catch (e) {
    report(e);
  }
};
$("project").onchange = () =>
  request("/api/projects/" + $("project").value + "/select", { method: "POST" })
    .then(projects)
    .catch(report);
async function removeProject(id) {
  await projects(await request("/api/projects/" + id + "/remove", {method: "POST"}));
}
$("remove").onclick = () => removeProject(state.id).catch(report);
$("refresh").onclick = () => refresh(true).catch(report);
$("close").onclick = () => $("preview").close();
$("preview").onclose = () => document.body.classList.remove("previewing");
$("newMessages").onclick = () => {
  document.querySelector("#content article:last-of-type")?.scrollIntoView({block: "end"});
  $("newMessages").hidden = true;
};
for (const tab of ["inbox", "chat"]) $(tab).onclick = () => {
  state.tab = tab;
  $("newMessages").hidden = true;
  refresh().catch(report);
};
for (const id of ["search", "role", "status", "model", "version"])
  $(id).oninput = () => refresh().catch(report);
render();
if (!direct) projects().catch(report);
setInterval(() => {
  if (!document.hidden && !direct && state.id) refresh(true).catch(report);
}, 5000);
