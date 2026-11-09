// Connect page (DCL-127): the paste-once login flow (spec section 2). The
// gateway token lives only in the session cookie — never localStorage, never
// the URL.

import { el, navigate, registerRoute, t } from "./app.js";
import { postJson } from "./api.js";

const mount = async (main) => {
  const form = el("form", { cls: "field" });
  const label = el("label", { attrs: { for: "token" } });
  label.textContent = t("connect.token.label");
  const input = el("input", { attrs: { id: "token", type: "password", autocomplete: "off" } });
  const help = el("p", { cls: "muted", text: t("connect.token.help") });
  const submit = el("button", { attrs: { type: "submit" }, text: t("connect.submit") });
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  form.replaceChildren(label, input, submit, help, banner);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    banner.setAttribute("hidden", "");
    try {
      await postJson("/api/auth/login", { token: input.value });
      navigate("chat");
    } catch (error) {
      banner.textContent = error && error.code ? t(`error.${error.code}`) : String(error);
      banner.removeAttribute("hidden");
    }
  });
  main.appendChild(el("h1", { text: t("page.connect.title") }));
  main.appendChild(form);
};

registerRoute("connect", mount);
