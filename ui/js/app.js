// Hash routing + i18n loader for the DeClaw local UI (spec sections 13-14).
//
// SECURITY RULE (spec section 13): model output, document chunks, audit
// payloads and plugin strings are UNTRUSTED. They are only ever inserted
// into the DOM via textContent/createTextNode — never innerHTML. There is
// no Markdown rendering in v0.1.

import { getJson } from "./api.js";

import "./connect.js";
import "./chat.js";
import "./documents.js";
import "./audit.js";
import "./plugins.js";
import "./settings.js";
import "./status.js";

const routes = new Map();
let locales = { en: {}, fr: {} };
let activeLanguage = "en";

// --- untrusted text rendering (the ONLY sanctioned DOM insertion) ----------- //

export const el = (tag, options = {}) => {
  const node = document.createElement(tag);
  if (options.cls) node.className = options.cls;
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      node.setAttribute(name, value);
    }
  }
  if (options.text !== undefined) {
    node.textContent = String(options.text); // untrusted-safe
  }
  return node;
};

export const t = (key, params = {}) => {
  const table = locales[activeLanguage] || {};
  let value = key.split(".").reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), table);
  if (value === undefined) {
    value = key.split(".").reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), locales.en) ?? key;
  }
  if (typeof value !== "string") return key;
  for (const [name, replacement] of Object.entries(params)) {
    value = value.split(`{${name}}`).join(String(replacement));
  }
  return value;
};

export const setLanguage = (language) => {
  activeLanguage = language === "fr" ? "fr" : "en";
};

export const breadcrumb = (pageId) => t(`nav.${pageId}`);

// --- routing ----------------------------------------------------------------- //

export const registerRoute = (pageId, mount) => {
  routes.set(pageId, mount);
};

const currentPage = () => {
  const hash = window.location.hash || "#/connect";
  const pageId = hash.replace(/^#\//, "").split("?")[0] || "connect";
  return routes.has(pageId) ? pageId : "connect";
};

const render = async () => {
  const pageId = currentPage();
  const mount = routes.get(pageId);
  const main = document.getElementById("page");
  main.replaceChildren();
  for (const link of document.querySelectorAll("nav a")) {
    link.setAttribute("data-active", String(link.dataset.route === pageId));
  }
  if (mount) {
    await mount(main);
  }
  window.document.title = `DeClaw — ${breadcrumb(pageId)}`;
};

export const navigate = (pageId) => {
  window.location.hash = `#/${pageId}`;
};

// --- bootstrap ----------------------------------------------------------------- //

const loadLocales = async () => {
  const [en, fr] = await Promise.all([
    fetch("locales/en.json").then((response) => response.json()),
    fetch("locales/fr.json").then((response) => response.json()),
  ]);
  locales = { en, fr };
};

const bootstrap = async () => {
  try {
    await loadLocales();
    const settings = await getJson("/api/settings").catch(() => null);
    if (settings && (settings.language === "fr" || settings.language === "en")) {
      setLanguage(settings.language);
    }
  } catch (_) {
    // locales stay at their empty defaults; t() falls back to keys
  }
  for (const link of document.querySelectorAll("nav a")) {
    // labels flow through the locale table (spec section 14)
    link.textContent = t(`nav.${link.dataset.route}`);
  }
  window.addEventListener("hashchange", () => {
    render();
  });
  window.addEventListener("declaw:unauthenticated", () => navigate("connect"));
  await render();
};

bootstrap();
