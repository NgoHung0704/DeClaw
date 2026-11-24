// Load shared state before registering pages, then start the UI.
import { bootstrap } from "./core.js";
import "./connect.js";
import "./chat.js";
import "./documents.js";
import "./audit.js";
import "./plugins.js";
import "./settings.js";
import "./status.js";

export const ready = bootstrap();
