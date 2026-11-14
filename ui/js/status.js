// Status page (DCL-133): polls /api/status and subscribes to /ws/events for
// live plugin/indexing changes.

import { el, registerRoute, t } from "./core.js";
import { getJson, wsBase } from "./api.js";

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.status.title") });
  const refresh = el("button", { text: t("status.refresh") });
  const table = el("table");
  const tbody = el("tbody");
  table.appendChild(tbody);
  const live = el("div", { cls: "muted" });
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  main.replaceChildren(h1, refresh, table, live, banner);

  const row = (label, value) => {
    const tr = el("tr");
    tr.appendChild(el("td", { text: label }));
    tr.appendChild(el("td", { text: String(value) }));
    return tr;
  };

  const render = async () => {
    tbody.replaceChildren();
    try {
      const body = await getJson("/api/status");
      tbody.appendChild(row(t("status.version"), body.version));
      const ollama = body.ollama || {};
      const reach = ollama.reachable === null || ollama.reachable === undefined ? "null" : String(ollama.reachable);
      tbody.appendChild(row(t("status.ollama"), t(`status.reachable.${reach}`)));
      tbody.appendChild(row(t("status.model_present"), String(Boolean(ollama.model_present))));
      tbody.appendChild(row(t("status.watcher"), String(Boolean(body.watcher))));
      tbody.appendChild(row(t("status.egress"), String(Boolean(body.egress_monitor))));
      const states = (body.plugins || []).map((plugin) => `${plugin.name}=${plugin.state}`).join(", ");
      tbody.appendChild(row(t("status.plugins"), states));
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.removeAttribute("hidden");
    }
  };

  refresh.addEventListener("click", render);
  await render();

  try {
    const events = new WebSocket(`${wsBase()}/ws/events`);
    events.onmessage = (event) => {
      let frame = null;
      try {
        frame = JSON.parse(event.data);
      } catch (_) {
        return;
      }
      if (frame.type === "index.progress") {
        live.textContent = `${t("documents.reindexing")} ${frame.done}/${frame.total}`;
      }
      if (frame.type === "plugin.enabled" || frame.type === "plugin.disabled") {
        render();
      }
    };
  } catch (_) {
    // no live stream: the Refresh button keeps the page honest
  }
};

registerRoute("status", mount);
