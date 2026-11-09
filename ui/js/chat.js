// chat page module (spec section 13). Functional wiring lands with the
// DCL-127..130/133/134 slice; this module owns the page's DOM surface.

import { el, registerRoute, t } from "./app.js";

const mount = async (main) => {
  main.appendChild(el("h1", { text: t("page.chat.title") }));
};

registerRoute("chat", mount);
