// Documents page (DCL-128): catalog + honest workspace copy + reindex with
// live progress over /ws/events. Documents enter only through the workspace
// folder on disk — the browser cannot pick arbitrary server paths, and the
// copy says exactly that (spec section 10/13).

import { el, registerRoute, t } from "./core.js";
import { getJson, postJson, wsBase } from "./api.js";

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.documents.title") });
  const workspaceBlock = el("div", { cls: "field" });
  const info = el("div", { cls: "banner", attrs: { "data-kind": "info" } });
  const actions = el("div");
  const reindex = el("button", { text: t("documents.reindex") });
  const progress = el("div", { cls: "muted", attrs: { hidden: "" } });
  actions.appendChild(reindex);
  actions.appendChild(progress);
  const table = el("table");
  const head = el("tr");
  for (const key of ["path", "size", "status", "indexed"]) {
    head.appendChild(el("th", { text: t(`documents.columns.${key}`) }));
  }
  const thead = el("thead");
  thead.appendChild(head);
  const tbody = el("tbody");
  table.replaceChildren(thead, tbody);
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  main.replaceChildren(h1, workspaceBlock, info, actions, table, banner);

  workspaceBlock.appendChild(el("h2", { text: t("documents.workspace") }));

  // The workspace path is honest copy (never a server folder picker).
  try {
    const settings = await getJson("/api/settings");
    workspaceBlock.appendChild(el("p", { text: settings.workspace_dir, cls: "muted" }));
  } catch (_) {
    // settings unavailable: the catalog below still renders what it can
  }

  const refresh = async () => {
    try {
      const body = await getJson("/api/documents");
      tbody.replaceChildren();
      for (const doc of body.documents) {
        const row = el("tr");
        row.appendChild(el("td", { text: doc.path }));
        row.appendChild(el("td", { text: doc.size_bytes === null ? "" : String(doc.size_bytes) }));
        row.appendChild(el("td", { text: doc.status }));
        row.appendChild(el("td", { text: doc.indexed_at ? String(doc.indexed_at) : "" }));
        tbody.appendChild(row);
      }
      info.textContent = t("documents.count", { count: String(body.documents.length) });
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.removeAttribute("hidden");
    }
  };

  reindex.addEventListener("click", async () => {
    try {
      await postJson("/api/documents/reindex");
      reindex.setAttribute("disabled", "");
      progress.textContent = t("documents.reindexing");
      progress.removeAttribute("hidden");
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.removeAttribute("hidden");
    }
  });

  // Live progress via /ws/events (the same server that streams index.progress).
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
        progress.textContent = `${t("documents.reindexing")} ${frame.done}/${frame.total}`;
        progress.removeAttribute("hidden");
        if (frame.done >= frame.total) {
          reindex.removeAttribute("disabled");
          refresh();
        }
      }
    };
  } catch (_) {
    // no live progress; the catalog still refreshes on load
  }

  await refresh();
};

registerRoute("documents", mount);
