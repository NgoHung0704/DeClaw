// Plugins page (DCL-130/134): the Settings-style permission panel (NOT a
// first-run consent — ratified decision 4) with honest semantics: disable is
// immediate, enable takes effect at the NEXT gateway start (decision 11).

import { el, registerRoute, t } from "./core.js";
import { getJson, postJson } from "./api.js";

const permissionPanel = async (main, name) => {
  main.appendChild(el("h2", { text: `${t("plugins.permissions")} — ${name}` }));
  const summary = el("div");
  let body;
  try {
    body = await getJson(`/api/plugins/${name}/permissions`);
  } catch (error) {
    summary.textContent = t(`error.${error.code || "service_unavailable"}`);
    main.appendChild(summary);
    return;
  }
  const groups = [
    ["requested", "plugins.requested"],
    ["denied_by_author", "plugins.denied_by_author"],
    ["granted", "plugins.granted"],
  ];
  const refresh = async () => {
    try {
      body = await getJson(`/api/plugins/${name}/permissions`);
    } catch (_) {
      return panel;
    }
    return panel();
  };
  const panel = () => {
    summary.replaceChildren();
    for (const [key, labelKey] of groups) {
      const row = el("div", { cls: "chat-composer" });
      row.appendChild(el("span", { text: t(labelKey), cls: "muted" }));
      const entries = key === "denied_by_author" ? Object.values(body.denied || {}) : body[key] || [];
      for (const permission of entries) {
        row.appendChild(el("span", { cls: "badge", text: String(permission) }));
      }
      if (key === "granted") {
        for (const permission of entries) {
          const revoke = el("button", { attrs: { "data-variant": "danger" }, text: `${t("plugins.revoke")} ${permission}` });
          revoke.addEventListener("click", async () => {
            await postJson(`/api/plugins/${name}/permissions/${permission}/revoke`);
            refresh();
          });
          row.appendChild(revoke);
        }
      }
      if (key === "requested") {
        for (const permission of entries) {
          if (!(body.granted || []).includes(permission) && !(body.denied || []).includes(permission)) {
            const grant = el("button", { text: `${t("plugins.grant")} ${permission}` });
            grant.addEventListener("click", async () => {
              await postJson(`/api/plugins/${name}/permissions/${permission}/grant`);
              refresh();
            });
            row.appendChild(grant);
          }
        }
      }
      summary.appendChild(row);
    }
    return summary;
  };
  panel();
  main.appendChild(summary);
};

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.plugins.title") });
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  main.replaceChildren(h1, banner);

  let plugins = [];
  try {
    plugins = (await getJson("/api/plugins")).plugins;
  } catch (error) {
    banner.textContent = t(`error.${error.code || "service_unavailable"}`);
    banner.removeAttribute("hidden");
    return;
  }

  const list = el("table");
  const thead = el("thead");
  const head = el("tr");
  head.appendChild(el("th", { text: "name" }));
  head.appendChild(el("th", { text: "version" }));
  head.appendChild(el("th", { text: "state" }));
  head.appendChild(el("th", { text: "" }));
  thead.appendChild(head);
  const tbody = el("tbody");
  list.replaceChildren(thead, tbody);

  const render = async () => {
    tbody.replaceChildren();
    for (const plugin of plugins) {
      const row = el("tr");
      row.appendChild(el("td", { text: plugin.name }));
      row.appendChild(el("td", { text: plugin.version }));
      const stateCell = el("td");
      stateCell.appendChild(el("span", { cls: "badge", text: plugin.state }));
      row.appendChild(stateCell);
      const actionCell = el("td");
      if (plugin.state === "enabled") {
        const disable = el("button", { attrs: { "data-variant": "danger" }, text: t("plugins.disable") });
        disable.addEventListener("click", async () => {
          const result = await postJson(`/api/plugins/${plugin.name}/disable`);
          plugin.state = result.state;
          await render();
        });
        actionCell.appendChild(disable);
      } else {
        const enable = el("button", { text: t("plugins.enable") });
        enable.addEventListener("click", async () => {
          const result = await postJson(`/api/plugins/${plugin.name}/enable`);
          plugin.state = result.state;
          await render();
        });
        actionCell.appendChild(enable);
        actionCell.appendChild(
          el("span", { cls: "badge", text: t("plugins.takes_effect.next_gateway_start") })
        );
      }
      row.appendChild(actionCell);
      tbody.appendChild(row);
    }
  };

  await render();
  main.appendChild(list);
  for (const plugin of plugins) {
    await permissionPanel(main, plugin.name);
  }
};

registerRoute("plugins", mount);
