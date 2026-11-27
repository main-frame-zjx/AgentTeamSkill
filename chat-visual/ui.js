"use strict";
const ChatUI = (() => {
  const kinds = {review_request: "送验提醒", review_rejected: "验收打回", review_feedback: "审阅反馈",
    collab_request: "协作提醒", info_sync: "关键同步"};
  const models = {gpt: "GPT", gemini: "Gemini", claude: "Claude", deepseek: "DeepSeek", human: "用户", other: "Model"};

  function statusOf(message, role) {
    if (!role || role === message.sender && !message.recipients[role]) return message.overall_status;
    return message.recipients[role]?.status;
  }
  function attention(message, role) {
    if (statusOf(message, role) === "handled") return "";
    return role && message.sender === role && !message.recipients[role] ? "outgoing" : "unread";
  }
  function renderer(markdownit) {
    return markdownit?.({html: false, linkify: false}).disable(["image", "link", "autolink"]);
  }
  // Reuse message and list nodes so polling preserves selection, focus and opened details.
  function key(node) {
    return node.id || node.dataset?.key;
  }
  function patch(current, next) {
    if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) {
      current.replaceWith(next);
      return;
    }
    if (current.nodeType === Node.TEXT_NODE) {
      if (current.data !== next.data) current.data = next.data;
      return;
    }
    current.onclick = next.onclick;
    for (const name of new Set([...current.getAttributeNames(), ...next.getAttributeNames()])) {
      if (name === "open" && current.tagName === "DETAILS") continue;
      const value = next.getAttribute(name);
      if (value === null) current.removeAttribute(name);
      else if (current.getAttribute(name) !== value) current.setAttribute(name, value);
    }
    const old = new Map([...current.childNodes].filter(key).map(n => [key(n), n]));
    let child = current.firstChild;
    for (const incoming of [...next.childNodes]) {
      const match = key(incoming) ? old.get(key(incoming)) : child && !key(child) ? child : null;
      if (match) {
        if (match !== child) current.insertBefore(match, child);
        const after = match.nextSibling;
        patch(match, incoming);
        child = after;
      } else current.insertBefore(incoming, child);
    }
    while (child) {
      const after = child.nextSibling;
      child.remove();
      child = after;
    }
  }
  return {kinds, models, renderer, statusOf, attention, patch};
})();
if (typeof module !== "undefined") module.exports = ChatUI;
