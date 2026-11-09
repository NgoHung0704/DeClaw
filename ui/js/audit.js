// Audit page (DCL-129): filters, keyset pagination on (created_at, id) and
// the md/json export — all through the typed /api/audit routes. Payloads are
// untrusted JSON rendered as text only.

import { el, registerRoute, t } from "./app.js";
import { getJson } from "./api.js";

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.audit.title") });
  const form = el("form", { cls: "chat-composer" });
  const eventType = el("input", { attrs: { placeholder: t("audit.event_type") } });
  const taskId = el("input", { attrs: { placeholder: t("audit.task_id") } });
  const from = el("input", { attrs: { type: "date", title: t("audit.from") } });
  const to = el("input", { attrs: { type: "date", title: t("audit.to") } });
  const apply = el("button", { attrs: { type: "submit" }, text: t("audit.filter") });
  const clear = el("button", { attrs: { type: "button" }, text: t("audit.clear") });
  form.replaceChildren(eventType, taskId, from, to, apply, clear);

  // GET /api/audit/export requires day + format (typed Query): the export
  // row always carries both, else the route answers 422.
  const dayInput = el("input", { attrs: { type: "date", value: new Date().toISOString().slice(0, 10) } });
  const exportMd = el("button", { text: `${t("audit.export")} md` });
  const exportJson = el("button", { text: `${t("audit.export")} json` });
  const openExport = (format) => {
    const day = dayInput.value || new Date().toISOString().slice(0, 10);
    window.open(`/api/audit/export?day=${day}&format=${format}`, "_blank");
  };
  exportMd.addEventListener("click", () => openExport("md"));
  exportJson.addEventListener("click", () => openExport("json"));
  const exportLinks = el("div", { cls: "chat-composer" });
  exportLinks.replaceChildren(dayInput, exportMd, exportJson);

  const table = el("table");
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
  main.replaceChildren(h1, form, exportLinks, table, pager, banner);

  let cursor = null;
  const params = () => {
    const query = new URLSearchParams();
    if (eventType.value.trim()) query.set("event_type", eventType.value.trim());
    if (taskId.value.trim()) query.set("task_id", taskId.value.trim());
    if (from.value) query.set("date_from", from.value);
    if (to.value) query.set("date_to", to.value);
    if (cursor) query.set("cursor", cursor);
    return query;
  };

  const keyset = async (direction) => {
    try {
      const query = params();
      const body = await getJson(`/api/audit?${query.toString()}`);
      tbody.replaceChildren();
      for (const event of body.events) {
        const row = el("tr");
        row.appendChild(el("td", { text: `${event.created_at} ${event.id}` }));
        row.appendChild(el("td", { text: event.event_type }));
        const payload = el("td");
        payload.textContent = JSON.stringify(event.payload);
        row.appendChild(payload);
        tbody.appendChild(row);
      }
      older.setAttribute("disabled", "");
      newer.setAttribute("disabled", "");
      if (body.next_cursor) {
        cursor = body.next_cursor;
        older.removeAttribute("disabled");
      }
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.removeAttribute("hidden");
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    cursor = null;
    keyset();
  });
  clear.addEventListener("click", () => {
    eventType.value = "";
    taskId.value = "";
    from.value = "";
    to.value = "";
    cursor = null;
    keyset();
  });
  older.addEventListener("click", () => keyset("older"));
  newer.addEventListener("click", () => keyset("newer"));

  await keyset();
};

registerRoute("audit", mount);
