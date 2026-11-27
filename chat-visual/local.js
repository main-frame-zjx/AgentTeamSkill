/* Directory access for double-clicked HTML. The journal contains the committed after-images. */
"use strict";
const LocalChat = (() => {
  const stages = ["1新需求", "2处理中", "3待验收", "4已归档"];
  const priority = {
    review_rejected: 0,
    review_request: 1,
    review_feedback: 2,
    collab_request: 2,
    info_sync: 3,
  };
  const allowed = /\.(md|py|ts|js|mjs|vue|json|ya?ml|txt|css|html|cs|cpp|h|ps1|sh|toml|ini)$/i;

  function parts(path) {
    const names = path.split("/");
    if (names.some((n) => !n || [".", "..", ".git"].includes(n.toLowerCase()) || /[:\\]/.test(n))) {
      throw Error("路径不在项目内");
    }
    return names;
  }
  function source(handle, files) {
    async function dir(names) {
      let current = handle;
      for (const name of names) current = await current.getDirectoryHandle(name);
      return current;
    }
    return {
      async file(path) {
        const names = parts(path);
        if (files) {
          if (!files.has(path)) throw new DOMException(path, "NotFoundError");
          return files.get(path);
        }
        const name = names.pop();
        return (await (await dir(names)).getFileHandle(name)).getFile();
      },
      async list(path) {
        parts(path);
        if (files) {
          const nested = [...files.keys()].filter(n => n.startsWith(path + "/"));
          if (!nested.length) throw new DOMException(path, "NotFoundError");
          return nested.map(n => n.slice(path.length + 1)).filter(n => !n.includes("/"));
        }
        const entries = [];
        for await (const [name, entry] of (await dir(parts(path))).entries())
          if (entry.kind === "file") entries.push(name);
        return entries;
      },
    };
  }
  async function pick() {
    if (window.showDirectoryPicker) {
      try {
        return source(await window.showDirectoryPicker({ mode: "read" }));
      } catch (err) {
        if (!["SecurityError", "NotAllowedError"].includes(err.name)) throw err;
      }
    }
    const input = document.createElement("input");
    input.type = "file";
    input.webkitdirectory = true;
    return new Promise((resolve, reject) => {
      input.oncancel = () => reject(new DOMException("已取消", "AbortError"));
      input.onchange = () =>
        resolve(
          source(
            null,
            new Map([...input.files].map((f) => [f.webkitRelativePath.split("/").slice(1).join("/"), f])),
          ),
        );
      input.click();
    });
  }
  async function read(src, path, optional = false) {
    try {
      const value = JSON.parse(await (await src.file(path)).text());
      if (!value || typeof value !== "object" || Array.isArray(value)) throw Error(path + " · 需要 JSON 对象");
      return value;
    } catch (err) {
      if (optional && err.name === "NotFoundError") return null;
      throw err;
    }
  }
  async function tasks(src, data, warnings) {
    const result = new Map(), ids = new Set(), numbers = new Map(), duplicates = new Set();
    for (const role of data.members) {
      if (role.dir !== "AT_" + role.name) {
        warnings.push("AT.json · 角色目录与登记不符");
        continue;
      }
      for (const stage of stages) {
        const folder = role.dir + "/workspace/" + stage;
        let entries;
        try { entries = await src.list(folder); }
        catch (error) { warnings.push(folder + " · 无法读取需求目录"); continue; }
        for (const name of entries.filter(n => n.toLowerCase().endsWith(".md"))) {
          const path = folder + "/" + name;
          try {
            const raw = await (await src.file(path)).text();
            const blocks = [...raw.matchAll(/^\x60{3}json\r?\n([\s\S]*?)\r?\n\x60{3}\r?$/gm)].map((m) =>
              JSON.parse(m[1]),
            );
            const [task, ...events] = blocks;
            const fence = String.fromCharCode(96).repeat(3);
            const block = record => fence + "json\n" + JSON.stringify(record, null, 2) + "\n" + fence + "\n";
            if (!task || raw !== "# " + task.id + " · " + task.title + "\n\n## 需求\n\n" +
                block(task) + "\n## 追加记录\n" + events.map(e => "\n" + block(e)).join(""))
              throw Error("需求格式或历史损坏");
            const filename = name.match(/^AT-([A-Za-z]+)([0-9]{5})-(.+)\.md$/);
            if (task.format !== "agent-team/task-v1" || task.owner !== role.name ||
              !/^AT-[a-f0-9]{32}$/.test(task.id) || !filename || filename[1] !== role.task_prefix)
              throw Error("需求信息或文件名不符");
            const number = role.name + "/" + filename[2];
            if (ids.has(task.id) || numbers.has(number)) {
              duplicates.add(task.id);
              if (numbers.has(number)) duplicates.add(numbers.get(number));
              warnings.push(path + " · 需求编号或流水号重复");
            }
            ids.add(task.id);
            numbers.set(number, task.id);
            let current = stages[0];
            for (const e of events) {
              if (!["type","actor","key","reason"].every(k => typeof e[k] === "string" && e[k].trim()))
                throw Error("追加记录缺少事件信息");
              if (e.type === "amend") Object.assign(task, e.changes);
              if (e.type === "move") {
                const before = stages.indexOf(current), after = stages.indexOf(e.to);
                if (e.from !== current || !(after === before + 1 || (before === 2 && after === 1)) || after < 0)
                  throw Error("需求流转历史不符");
                current = e.to;
              }
            }
            if (current !== stage || !Array.isArray(task.criteria) || !task.criteria.every(c => typeof c === "string") ||
              !["reviewer","title","goal","version"].every(k => typeof task[k] === "string" && task[k].trim()))
              throw Error("需求阶段或验收条件不符");
            result.set(task.id, {
              ...task,
              code: name.match(/^AT-([A-Za-z]+\d{5})-/)?.[1],
              events,
              stage,
              path,
            });
          } catch (err) {
            warnings.push(path + " · " + err.message);
          }
        }
      }
    }
    for (const id of duplicates) result.delete(id);
    return result;
  }

  async function optionalList(src, path) {
    try { return await src.list(path); }
    catch (err) { if (err.name === "NotFoundError") return []; throw err; }
  }

  function checkMessages(group, row, limit) {
    if (group.group_id !== row.group_id || group.format !== "agent-team/chat-group-v1"
      || group.kind !== row.group_id.split(":")[0] || typeof group.title !== "string" ||
      group.task_id !== (group.kind === "task" ? row.group_id.slice(5) : null) || !Array.isArray(group.messages))
      throw Error("群组信息无效");
    let previous = 0;
    for (const m of group.messages) {
      const recipients = Object.keys(m.recipients);
      if (!Number.isSafeInteger(m.seq) || m.seq <= previous || m.seq >= limit ||
          m.id !== "MSG-" + String(m.seq).padStart(6,"0") || m.group_id !== row.group_id ||
          !Object.hasOwn(priority, m.kind) || !Array.isArray(m.to) || !m.to.length ||
          new Set(m.to).size !== recipients.length || m.to.some(r => !recipients.includes(r)) ||
          !["sender","sender_model","created_at","model_family","idempotency_key","body"].every(k => typeof m[k] === "string") ||
          !Object.hasOwn(m, "reply_to") || !Array.isArray(m.refs) || !m.refs.every(ref => typeof ref.path === "string"))
        throw Error("群消息结构或序号异常");
      previous = m.seq;
      const states = new Set(recipients.map(r => m.recipients[r].status));
      if ([...states].some(s => !["pending", "handled"].includes(s)) ||
          m.overall_status !== (states.size === 1 ? [...states][0] : "partial")) throw Error("群消息状态不一致");
    }
  }

  async function load(src) {
    const data = await read(src, "AT.json"),
      warnings = [];
    if (data.format !== "agent-team/v3") throw Error("请选择含 AgentTeam v3 项目的目录");
    const base = "public/" + (data.team_repo.split("/").pop().toLowerCase() === "chat" ? "at-chat" : "chat");
    const currentTasks = await tasks(src, data, warnings);
    for (let attempt = 0; attempt < 4; attempt++) {
      const journal = await read(src, ".at-state/chat-transaction.json", true);
      const meta = journal ? journal.meta : await read(src, base + "/meta.json", true);
      const project = {...data, roles: [...data.members.map(r => r.name), "用户"]};
      if (!meta && !journal) {
        if ((await optionalList(src, base)).length || (await optionalList(src, base + "/groups")).length)
          throw Error(base + "/meta.json 缺失，通讯目录已有数据");
        if (await read(src, ".at-state/chat-transaction.json", true) || await read(src, base + "/meta.json", true)) continue;
        return {project, initialized: false, groups: [], pending_items: [], pending_total: 0, warnings};
      }
      if (!meta || meta.project_id !== data.id || meta.format !== "agent-team/chat-v1" ||
          !Number.isSafeInteger(meta.next_seq) || meta.next_seq < 1 || !Array.isArray(meta.groups))
        throw Error("通讯索引无效或与项目不符");
      const groups = [], faults = [], pendingByGroup = new Map(), sequences = new Map(), conflicts = new Set();
      const ids = new Set();
      for (const row of meta.groups) {
        if (!/^(topic:[a-z0-9][a-z0-9-]{0,47}|task:AT-[a-f0-9]{32})$/.test(row.group_id) ||
          row.file !== row.group_id.replace(":", "__") + ".json" || ids.has(row.group_id)) throw Error("通讯群索引无效");
        ids.add(row.group_id);
      }
      if (journal && (!journal.groups || Array.isArray(journal.groups) ||
        typeof journal.groups !== "object" || Object.keys(journal.groups).some(id => !ids.has(id)))) throw Error("通讯事务索引损坏");
      for (const row of meta.groups) {
        try {
          const g = journal && Object.hasOwn(journal.groups, row.group_id) ? journal.groups[row.group_id] :
            await read(src, base + "/groups/" + row.file);
          for (const m of Array.isArray(g?.messages) ? g.messages : []) {
            if (!Number.isSafeInteger(m?.seq) || m.seq < 1) continue;
            const other = sequences.get(m.seq);
            if (other && other !== row.group_id) { conflicts.add(other); conflicts.add(row.group_id); }
            sequences.set(m.seq, row.group_id);
          }
          checkMessages(g, row, meta.next_seq);
          const task = currentTasks.get(g.task_id),
            pending = [];
          for (const m of g.messages)
            for (const [recipient, r] of Object.entries(m.recipients)) {
              if (r.status === "pending")
                pending.push({
                  message_id: m.id,
                  group_id: g.group_id,
                  recipient,
                  kind: m.kind,
                  sender: m.sender,
                  sender_model: m.sender_model,
                  preview: [...m.body].slice(0, 160).join(""),
                  priority: priority[m.kind],
                  created_at: m.created_at,
                });
            }
          pendingByGroup.set(g.group_id, pending);
          groups.push({
            ...g,
            task,
            pending_count: pending.length,
            archived: g.archived || task?.stage === stages[3],
            message_count: g.messages.length,
            last_preview: [...(g.messages.at(-1)?.body || "")].slice(0,160).join(""),
            last_message_at: g.messages.at(-1)?.created_at,
          });
        } catch (err) {
          if (journal && Object.hasOwn(journal.groups, row.group_id)) throw Error("通讯事务群记录损坏 · " + row.file);
          faults.push(base + "/groups/" + row.file + " · " + err.message);
        }
      }
      const end = await read(src, ".at-state/chat-transaction.json", true);
      const finalMeta = end?.meta || (await read(src, base + "/meta.json"));
      if (finalMeta.revision !== meta.revision || finalMeta.updated_at !== meta.updated_at) continue;
      const valid = groups.filter(g => !conflicts.has(g.group_id));
      for (const id of conflicts) faults.push(base + "/groups/" + id.replace(":", "__") + ".json · 跨群消息序号重复");
      const pending_items = valid.flatMap(g => pendingByGroup.get(g.group_id));
      pending_items.sort((a, b) => a.priority - b.priority || a.created_at.localeCompare(b.created_at));
      return {
        project, initialized: true,
        groups: valid,
        pending_items,
        pending_total: pending_items.length,
        warnings: [...warnings, ...faults],
      };
    }
    throw Error("项目正在更新，请刷新重试");
  }
  async function preview(src, path) {
    if (!allowed.test(path)) throw Error("仅支持项目内文本");
    const file = await src.file(path),
      limit = 256 * 1024;
    const content = new TextDecoder("utf-8", { fatal: true }).decode(
      await file.slice(0, limit).arrayBuffer(),
      { stream: file.size > limit },
    );
    if (content.includes("\0")) throw Error("仅支持 UTF-8 文本");
    return { path, content, truncated: file.size > limit };
  }
  return { pick, load, preview, source };
})();
