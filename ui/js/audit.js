// Audit page (DCL-129): filters, keyset pagination on (created_at, id) and
// the md/json export — all through the typed /api/audit routes. Payloads are
// untrusted JSON rendered as text only.

import { el, registerRoute, t } from "./core.js";
import { prepareDownload, getJson } from "./api.js";

let downloadFeedback = null;

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.audit.title") });
  const form = el("form", { cls: "chat-composer" });
  const eventType = el("input", { attrs: { placeholder: t("audit.event_type"), "aria-label": t("audit.event_type") } });
  const taskId = el("input", { attrs: { placeholder: t("audit.task_id"), "aria-label": t("audit.task_id") } });
  const from = el("input", { attrs: { type: "date", title: t("audit.from") } });
  const to = el("input", { attrs: { type: "date", title: t("audit.to") } });
  const apply = el("button", { attrs: { type: "submit" }, text: t("audit.filter") });
  const clear = el("button", { attrs: { type: "button" }, text: t("audit.clear") });
  form.replaceChildren(eventType, taskId, from, to, apply, clear);

  // GET /api/audit/export requires day + format (typed Query): the export
  // row always carries both, else the route answers 422.
  const dayInput = el("input", { attrs: { type: "date", value: new Date().toISOString().slice(0, 10), "aria-label": t("audit.export_day"), title: t("audit.export_day") } });
  const exportMd = el("button", { text: `${t("audit.export")} md` });
  const exportJson = el("button", { text: `${t("audit.export")} json` });
  const openExport = async (format) => {
    const day = dayInput.value || new Date().toISOString().slice(0, 10);
    exportMd.disabled = exportJson.disabled = true;
    exportLinks.replaceChildren(dayInput, exportMd, exportJson);
    banner.setAttribute("hidden", "");
    try {
      const query = new URLSearchParams({ day, format });
      const url = await prepareDownload(`/api/audit/export?${query}`);
      const link = el("a", { text: t("audit.save_download", { format: format.toUpperCase() }) });
      link.href = url;
      link.download = `declaw-audit-${day}.${format}`;
      // A real follow-up click keeps the native download user-initiated.
      exportLinks.appendChild(link);
      banner.setAttribute("data-kind", "info");
      banner.textContent = t("audit.download_ready");
    } catch (error) {
      banner.setAttribute("data-kind", "error");
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
    } finally {
      banner.removeAttribute("hidden");
      exportMd.disabled = exportJson.disabled = false;
    }
  };
  exportMd.addEventListener("click", () => openExport("md"));
  exportJson.addEventListener("click", () => openExport("json"));
  const exportLinks = el("div", { cls: "chat-composer" });
  exportLinks.replaceChildren(dayInput, exportMd, exportJson);

  const table = el("table", { cls: "audit-table" });
  const thead = el("thead");
  const head = el("tr");
  head.appendChild(el("th", { text: t("audit.from") + " / id" }));
  head.appendChild(el("th", { text: t("audit.event_type") }));
  head.appendChild(el("th", { text: "payload" }));
  thead.appendChild(head);
  const tbody = el("tbody");
  table.replaceChildren(thead, tbody);

  const pager = el("div", { cls: "chat-composer" });
  const newer = el("button", { attrs: { disabled: "" }, text: t("audit.newer") });
  const older = el("button", { attrs: { disabled: "" }, text: t("audit.older") });
  pager.replaceChildren(newer, older);

  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  if (downloadFeedback) window.removeEventListener("declaw:download-finished", downloadFeedback);
  downloadFeedback = event => {
    banner.setAttribute("data-kind", event.detail === true ? "info" : "error");
    banner.textContent = t(event.detail === true ? "audit.download_complete" : "error.download_failed");
    banner.removeAttribute("hidden");
  };
  window.addEventListener("declaw:download-finished", downloadFeedback);
  main.replaceChildren(h1, form, exportLinks, table, pager, banner);

  let cursor = null;
  let nextCursor = null;
  let history = [];
  let filters = {};
  let loading = false;
  const params = (pageCursor, pageFilters) => {
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(pageFilters)) if (value) query.set(name, value);
    if (pageCursor) query.set("cursor", pageCursor);
    return query;
  };

  const keyset = async (direction, pageFilters = filters) => {
    if (loading || (direction === "older" && !nextCursor) || (direction === "newer" && !history.length)) return;
    const target = direction === "older" ? nextCursor : direction === "newer" ? history[history.length - 1] : null;
    loading = true;
    older.disabled = newer.disabled = true;
    try {
      const query = params(target, pageFilters);
      const body = await getJson(`/api/audit?${query.toString()}`);
      tbody.replaceChildren();
      for (const event of body.events) {
        const row = el("tr");
        const timestamp = el("td");
        const date = new Date(event.created_at);
        timestamp.appendChild(el("div", { text: Number.isNaN(date.getTime()) ? "" : date.toLocaleString(document.documentElement?.lang || "en") }));
        timestamp.appendChild(el("small", { text: String(event.id || "").slice(0, 8), attrs: { title: String(event.id || "") } }));
        row.appendChild(timestamp);
        row.appendChild(el("td", { text: event.event_type }));
        const payload = el("td");
        const details = el("details");
        details.appendChild(el("summary", { text: t("audit.details") }));
        details.appendChild(el("pre", { text: JSON.stringify(event, null, 2) }));
        payload.appendChild(details);
        row.appendChild(payload);
        tbody.appendChild(row);
      }
      if (direction === "older") history.push(cursor);
      else if (direction === "newer") history.pop();
      else history = [];
      cursor = target;
      filters = pageFilters;
      nextCursor = body.next_cursor || null;
      banner.setAttribute("hidden", "");
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.setAttribute("data-kind", "error");
      banner.removeAttribute("hidden");
    } finally {
      loading = false;
      older.disabled = !nextCursor;
      newer.disabled = history.length === 0;
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (loading) return;
    return keyset(undefined, { event_type: eventType.value.trim(), task_id: taskId.value.trim(), date_from: from.value, date_to: to.value });
  });
  clear.addEventListener("click", () => {
    if (loading) return;
    eventType.value = "";
    taskId.value = "";
    from.value = "";
    to.value = "";
    return keyset(undefined, {});
  });
  older.addEventListener("click", () => keyset("older"));
  newer.addEventListener("click", () => keyset("newer"));

  await keyset();
};

registerRoute("audit", mount);
