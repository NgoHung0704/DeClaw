// Chat page (DCL-125/127): streaming bubbles over /ws/chat, per-turn cancel,
// and the approval modal showing the tool name plus the CANONICAL VALIDATED
// arguments (spec section 7/13). Model output is UNTRUSTED: every insertion
// goes through el()/textContent, never innerHTML; no Markdown rendering.

import { el, registerRoute, t } from "./core.js";
import { wsBase } from "./api.js";

let socket = null;
let activeTurn = null;

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
      ui.entry("tool", `${frame.name} …`);
      break;
    }
    case "tool.end": {
      const preview = frame.result_preview ? ` ${String(frame.result_preview).slice(0, 120)}` : "";
      ui.entry("tool", `${frame.name}${preview}`);
      break;
    }
    case "approval.request": {
      showApproval(frame, (data) => socket && socket.send(data));
      break;
    }
    case "chat.final": {
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
  main.replaceChildren(h1, banner, log, composer, status, hint);
  let busy = false;
  send.disabled = true;
  cancel.disabled = true;

  let lastBubble = null;
  let assistantBubble = null;
  const ui = {
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
      send.disabled = value || socket?.readyState !== WebSocket.OPEN;
      cancel.disabled = !value || !activeTurn;
      log.setAttribute("aria-busy", String(value));
      status.textContent = t(value ? "chat.thinking" : "chat.ready");
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
