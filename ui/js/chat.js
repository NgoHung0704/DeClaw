// Chat page (DCL-125/127): streaming bubbles over /ws/chat, per-turn cancel,
// and the approval modal showing the tool name plus the CANONICAL VALIDATED
// arguments (spec section 7/13). Model output is UNTRUSTED: every insertion
// goes through el()/textContent, never innerHTML; no Markdown rendering.

import { el, registerRoute, t } from "./core.js";
import { wsBase } from "./api.js";

let socket = null;
let activeTurn = null;
let retainedView = null;

window.addEventListener("declaw:unauthenticated", () => {
  if (socket) {
    socket.onmessage = null;
    socket.onclose = null;
    socket.close();
  }
  socket = null;
  activeTurn = null;
  retainedView = null;
  closeModal();
});

const closeModal = () => {
  const modal = document.querySelector(".modal");
  if (modal) modal.remove();
};

const showApproval = (frame, send) => {
  closeModal();
  const overlay = el("div", { cls: "modal" });
  const article = el("article");
  article.appendChild(el("h2", { text: t("approval.title") }));
  article.appendChild(
    el("p", { text: `${t("approval.tool")}: ${frame.tool}` })
  );
  const argsLabel = el("h3", { text: t("approval.args") });
  const pre = el("pre");
  pre.textContent = JSON.stringify(frame.args, null, 2);
  if (frame.preview) {
    const previewLabel = el("h3", { text: t("approval.preview") });
    const previewPre = el("pre");
    previewPre.textContent = String(frame.preview);
    article.appendChild(argsLabel);
    article.appendChild(pre);
    article.appendChild(previewLabel);
    article.appendChild(previewPre);
  } else {
    article.appendChild(argsLabel);
    article.appendChild(pre);
  }
  const actions = el("div", { cls: "chat-composer" });
  const approve = el("button", { text: t("approval.approve") });
  const deny = el("button", { attrs: { "data-variant": "danger" }, text: t("approval.deny") });
  approve.addEventListener("click", () => {
    send(JSON.stringify({ type: "approval.response", id: frame.id, approved: true }));
    closeModal();
  });
  deny.addEventListener("click", () => {
    send(JSON.stringify({ type: "approval.response", id: frame.id, approved: false }));
    closeModal();
  });
  actions.replaceChildren(approve, deny);
  article.appendChild(actions);
  overlay.appendChild(article);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) {
      // Closing the modal never releases the tool: an unanswered request
      // times out and DENIES (spec section 7).
      closeModal();
    }
  });
  document.body.appendChild(overlay);
};

const renderSources = (final, sources) => {
  if (Array.isArray(sources) && sources.length > 0) {
    const heading = el("h3", { text: t("chat.sources") });
    const list = el("ul");
    for (const source of sources) {
      const text = typeof source === "string" ? source : JSON.stringify(source);
      list.appendChild(el("li", { text }));
    }
    final.appendChild(heading);
    final.appendChild(list);
  }
};

const onFrame = (frame, ui) => {
  switch (frame.type) {
    case "turn.started": {
      activeTurn = frame.turn_id;
      ui.entry("assistant", "");
      ui.setBusy(true);
      break;
    }
    case "chat.delta": {
      if (ui.lastAssistant) {
        ui.lastAssistant.textContent += frame.text;
      }
      break;
    }
    case "tool.start": {
      ui.startTool(frame.name);
      break;
    }
    case "tool.end": {
      ui.endTool(frame.name, frame.result_preview);
      break;
    }
    case "approval.request": {
      showApproval(frame, (data) => socket && socket.send(data));
      break;
    }
    case "chat.final": {
      ui.finishTools("chat.tool_incomplete");
      if (ui.lastAssistant) {
        ui.lastAssistant.textContent = frame.text;
        renderSources(ui.lastAssistant, frame.sources);
      }
      ui.endAssistant();
      activeTurn = null;
      ui.setBusy(false);
      break;
    }
    case "turn.cancelled": {
      ui.finishTools("chat.cancelled");
      ui.entry("tool", t("chat.cancelled"));
      ui.endAssistant();
      activeTurn = null;
      ui.setBusy(false);
      break;
    }
    case "error": {
      ui.entry("tool", t(`error.${frame.code}`));
      if ((frame.code === "busy" || frame.code === "rate_limited") && activeTurn) {
        // A rejected control message must not unlock a running turn.
      } else {
        ui.finishTools("chat.tool_incomplete");
        activeTurn = null;
        ui.endAssistant();
        ui.setBusy(false);
      }
      break;
    }
    default:
      break;
  }
};

const mount = async (main) => {
  // Route changes detach the view, not the live conversation or pending turn.
  if (retainedView) {
    main.replaceChildren(...retainedView.nodes);
    retainedView.refresh();
    return;
  }
  // Only one live chat connection per page instance; drop any previous one.
  if (socket) {
    socket.onclose = null;
    socket.onmessage = null;
    socket.close();
    socket = null;
  }
  activeTurn = null;
  const h1 = el("h1", { text: t("page.chat.title") });
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  banner.textContent = t("chat.disconnected");
  const log = el("div", { cls: "chat-log", attrs: { role: "log", "aria-label": t("chat.conversation"), "aria-live": "polite" } });
  const empty = el("div", { cls: "chat-empty" });
  empty.appendChild(el("span", { cls: "empty-mark", text: "d.", attrs: { "aria-hidden": "true" } }));
  empty.appendChild(el("h2", { text: t("chat.empty_title") }));
  empty.appendChild(el("p", { text: t("chat.empty_help") }));
  log.appendChild(empty);
  const composer = el("div", { cls: "chat-composer chat-input-bar" });
  const input = el("textarea", { attrs: { rows: "2", placeholder: t("chat.placeholder"), "aria-label": t("chat.placeholder") } });
  const send = el("button", { cls: "button-primary", text: t("chat.send") });
  const cancel = el("button", { attrs: { "data-variant": "danger" }, text: t("chat.cancel") });
  composer.replaceChildren(input, send, cancel);
  const status = el("p", { cls: "chat-status", text: t("chat.connecting"), attrs: { role: "status" } });
  const hint = el("p", { cls: "composer-hint", text: t("chat.keyboard_hint") });
  const newSession = el("button", { text: t("chat.new_session"), attrs: { type: "button" } });
  const heading = el("div", { cls: "page-heading" });
  heading.replaceChildren(h1, newSession);
  main.replaceChildren(heading, banner, log, composer, status, hint);
  let busy = false;
  send.disabled = true;
  cancel.disabled = true;
  newSession.addEventListener("click", async () => {
    if (busy) return;
    closeModal();
    retainedView = null;
    await mount(main);
  });

  let lastBubble = null;
  let assistantBubble = null;
  const tools = [];
  const ui = {
    startTool(name) {
      tools.push({ name, node: ui.entry("tool", `${name} …`) });
    },
    endTool(name, result) {
      const index = tools.findIndex(tool => tool.name === name);
      const node = index < 0 ? ui.entry("tool", "") : tools.splice(index, 1)[0].node;
      const preview = result ? ` ${String(result).slice(0, 120)}` : "";
      node.textContent = `${name} — ${t("chat.tool_finished")}${preview}`;
    },
    finishTools(label) {
      for (const tool of tools.splice(0)) tool.node.textContent = `${tool.name} — ${t(label)}`;
    },
    entry(role, text) {
      if (log.children[0] === empty) log.replaceChildren();
      lastBubble = el("div", { cls: "chat-entry", attrs: { "data-role": role, "data-label": role === "user" ? t("chat.you") : role === "tool" ? t("chat.activity") : "DeClaw" }, text });
      if (role === "assistant") assistantBubble = lastBubble;
      log.appendChild(lastBubble);
      log.scrollTop = log.scrollHeight;
      return lastBubble;
    },
    get lastAssistant() {
      return assistantBubble;
    },
    endAssistant() {
      if (assistantBubble) assistantBubble.dataset.role = "final";
      assistantBubble = null;
    },
    setBusy(value) {
      busy = value;
      newSession.disabled = value;
      send.disabled = value || socket?.readyState !== WebSocket.OPEN;
      cancel.disabled = !value || !activeTurn;
      log.setAttribute("aria-busy", String(value));
      status.textContent = t(value ? "chat.thinking" : "chat.ready");
    },
  };

  retainedView = {
    nodes: Array.from(main.childNodes),
    refresh() {
      h1.textContent = t("page.chat.title");
      empty.children[1].textContent = t("chat.empty_title");
      empty.children[2].textContent = t("chat.empty_help");
      newSession.textContent = t("chat.new_session");
      for (const bubble of log.children) {
        if (bubble.dataset.role === "user") bubble.setAttribute("data-label", t("chat.you"));
        else if (bubble.dataset.role === "tool") bubble.setAttribute("data-label", t("chat.activity"));
      }
      banner.textContent = t("chat.disconnected");
      input.setAttribute("placeholder", t("chat.placeholder"));
      input.setAttribute("aria-label", t("chat.placeholder"));
      send.textContent = t("chat.send");
      cancel.textContent = t("chat.cancel");
      hint.textContent = t("chat.keyboard_hint");
      log.setAttribute("aria-label", t("chat.conversation"));
      status.textContent = t(socket?.readyState === WebSocket.OPEN ? (busy ? "chat.thinking" : "chat.ready") : "chat.offline");
    },
  };

  const connect = () => new Promise((resolve) => {
    socket = new WebSocket(`${wsBase()}/ws/chat`);
    socket.onopen = () => resolve(true);
    socket.onclose = () => resolve(false);
    socket.onmessage = (event) => {
      try {
        onFrame(JSON.parse(event.data), ui);
      } catch (_) {
        // malformed frames are dropped (server never sends them)
      }
    };
  });

  const alive = await connect();
  if (!alive) {
    banner.removeAttribute("hidden");
    status.textContent = t("chat.offline");
    return;
  }
  ui.setBusy(false);
  let openBanner = false;
  socket.onclose = () => {
    if (!openBanner) {
      openBanner = true;
      banner.removeAttribute("hidden");
      ui.finishTools("chat.tool_incomplete");
      activeTurn = null;
      ui.endAssistant();
      ui.setBusy(false);
      status.textContent = t("chat.offline");
      closeModal();
    }
  };

  const sendTurn = () => {
    const text = input.value.trim();
    if (!text || busy || !socket || socket.readyState !== WebSocket.OPEN) return;
    ui.entry("user", text);
    socket.send(JSON.stringify({ type: "message", text }));
    input.value = "";
    ui.setBusy(true);
  };
  send.addEventListener("click", sendTurn);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendTurn();
    }
  });
  cancel.addEventListener("click", () => {
    if (socket && activeTurn && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "cancel", turn_id: activeTurn }));
    }
  });
};

registerRoute("chat", mount);
