// Settings page (DCL-131): the THREE mutable keys (model, language,
// workspace_dir) with honest applied feedback — model/language apply to new
// chat sessions, workspace changes require a gateway restart (spec section 12).

import { el, navigate, registerRoute, setLanguage, t } from "./core.js";
import { getJson, putJson } from "./api.js";
import { chooseWorkspace, hasWorkspacePicker } from "./desktop.js";

const mount = async (main) => {
  const h1 = el("h1", { text: t("page.settings.title") });
  const banner = el("div", { cls: "banner", attrs: { "data-kind": "error", hidden: "" } });
  const feedback = el("div", { cls: "banner", attrs: { "data-kind": "info", hidden: "" } });

  const modelField = el("div", { cls: "field" });
  const modelLabel = el("label", { attrs: { for: "model" }, text: t("settings.model") });
  const modelInput = el("input", { attrs: { id: "model", type: "text" } });
  modelField.replaceChildren(modelLabel, modelInput);

  const languageField = el("div", { cls: "field" });
  const languageLabel = el("label", { attrs: { for: "language" }, text: t("settings.language") });
  const languageSelect = el("select", { attrs: { id: "language" } });
  languageSelect.appendChild(el("option", { attrs: { value: "en" }, text: "English" }));
  languageSelect.appendChild(el("option", { attrs: { value: "fr" }, text: "Français" }));
  languageField.replaceChildren(languageLabel, languageSelect);

  const workspaceField = el("div", { cls: "field" });
  const workspaceLabel = el("label", { attrs: { for: "workspace" }, text: t("settings.workspace_dir") });
  const workspaceInput = el("input", { attrs: { id: "workspace", type: "text" } });
  const workspaceNote = el("p", {
    cls: "muted",
    text: t("settings.applied.restart_required"),
  });
  workspaceField.replaceChildren(workspaceLabel, workspaceInput, workspaceNote);
  if (hasWorkspacePicker()) {
    const choose = el("button", { text: t("settings.choose_workspace"), attrs: { type: "button" } });
    choose.addEventListener("click", async () => {
      choose.disabled = true;
      try {
        const path = await chooseWorkspace();
        if (path !== null) workspaceInput.value = path;
      } catch {
        banner.textContent = t("error.service_unavailable");
        banner.removeAttribute("hidden");
      } finally {
        choose.disabled = false;
      }
    });
    workspaceField.appendChild(choose);
  }

  const save = el("button", { text: t("settings.save") });
  main.replaceChildren(h1, banner, feedback, modelField, languageField, workspaceField, save);

  try {
    const settings = await getJson("/api/settings");
    modelInput.value = settings.model || "";
    languageSelect.value = settings.language === "fr" ? "fr" : "en";
    workspaceInput.value = settings.workspace_dir || "";
  } catch (error) {
    banner.textContent = t(`error.${error.code || "service_unavailable"}`);
    banner.removeAttribute("hidden");
    return;
  }

  save.addEventListener("click", async () => {
    banner.setAttribute("hidden", "");
    feedback.setAttribute("hidden", "");
    try {
      const body = {};
      if (modelInput.value.trim()) body.model = modelInput.value.trim();
      if (languageSelect.value) body.language = languageSelect.value;
      if (workspaceInput.value.trim()) body.workspace_dir = workspaceInput.value.trim();
      const result = await putJson("/api/settings", body);
      const messages = [];
      for (const [key, flag] of Object.entries(result.applied || {})) {
        messages.push(`${key}: ${t(`settings.applied.${flag}`)}`);
      }
      if (messages.length === 0) {
        messages.push(t("settings.saved"));
      }
      feedback.textContent = messages.join(" — ");
      feedback.removeAttribute("hidden");
      if (languageSelect.value === "en" || languageSelect.value === "fr") {
        setLanguage(languageSelect.value);
        for (const link of document.querySelectorAll("nav a")) {
          link.textContent = t(`nav.${link.dataset.route}`);
        }
        h1.textContent = t("page.settings.title");
      }
      navigate("settings");
    } catch (error) {
      banner.textContent = t(`error.${error.code || "service_unavailable"}`);
      banner.removeAttribute("hidden");
    }
  });
};

registerRoute("settings", mount);
