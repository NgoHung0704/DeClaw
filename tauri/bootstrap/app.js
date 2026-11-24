"use strict";
const strings = {
  en: {start: "Start", stop: "Stop", restart: "Restart", reveal: "Show login token", clear: "Hide token", help: "Closing this window keeps DeClaw in the tray. Use Quit to stop it.", stopped: "Core stopped", starting: "Starting core…", running: "Core running — log in with the token", stopping: "Stopping core…", failed: "Core unavailable", unavailable: "Desktop service unavailable"},
  fr: {start: "Démarrer", stop: "Arrêter", restart: "Redémarrer", reveal: "Afficher le jeton de connexion", clear: "Masquer le jeton", help: "Fermer cette fenêtre garde DeClaw dans la zone de notification. Quitter arrête le service.", stopped: "Service arrêté", starting: "Démarrage du service…", running: "Service actif — connectez-vous avec le jeton", stopping: "Arrêt du service…", failed: "Service indisponible", unavailable: "Service de bureau indisponible"},
};
const element = id => document.getElementById(id);
const errors = {
  en: {invalid_settings: "Check that the gateway uses 127.0.0.1:7842, then retry.", port_conflict: "Port 7842 is occupied. Stop the other gateway yourself, then retry.", spawn_failed: "Check the Python environment in this checkout, then retry.", protocol_invalid: "The private core connection failed. Retry after cleanup.", startup_timeout: "Startup timed out. Check the local configuration, then retry.", shutdown_timeout: "Graceful stop timed out. Retry when cleanup finishes.", unavailable: "The core is unavailable. Retry after cleanup."},
  fr: {invalid_settings: "Vérifiez que le service utilise 127.0.0.1:7842, puis réessayez.", port_conflict: "Le port 7842 est occupé. Arrêtez vous-même l’autre service, puis réessayez.", spawn_failed: "Vérifiez l’environnement Python de ce dépôt, puis réessayez.", protocol_invalid: "La connexion privée au service a échoué. Réessayez après le nettoyage.", startup_timeout: "Le démarrage a expiré. Vérifiez la configuration locale, puis réessayez.", shutdown_timeout: "L’arrêt normal a expiré. Réessayez après le nettoyage.", unavailable: "Le service est indisponible. Réessayez après le nettoyage."},
};
const language = () => element("language").value === "fr" ? "fr" : "en";
const viewErrors = {
  en: { message: "The main window could not open. Retry opening it; the core is still running.", retry: "Retry opening window" },
  fr: { message: "La fenêtre principale n’a pas pu s’ouvrir. Réessayez ; le service fonctionne toujours.", retry: "Réessayer d’ouvrir la fenêtre" },
};
const invoke = (name, args) => window.__TAURI__.core.invoke(name, args);
function clearToken() { element("token").textContent = ""; element("token").hidden = true; element("clear").hidden = true; }
let generation = 0;
let revealSequence = 0;
async function refresh() {
  try {
    const state = await invoke("desktop_status");
    if (generation !== state.generation || state.state !== "running") { revealSequence++; clearToken(); }
    generation = state.generation;
    element("status").textContent = strings[language()][state.state] || strings[language()].unavailable;
    if (state.state === "failed") element("status").textContent = errors[language()][state.error] || errors[language()].unavailable;
    const retryView = state.state === "running" && state.view_error === true;
    if (retryView) element("status").textContent = viewErrors[language()].message;
    element("start").textContent = retryView ? viewErrors[language()].retry : strings[language()].start;
    element("start").disabled = !retryView && !["stopped", "failed"].includes(state.state);
    element("stop").disabled = !["starting", "running"].includes(state.state);
    element("restart").disabled = state.state !== "running";
    element("reveal").disabled = state.state !== "running";
  } catch { clearToken(); element("status").textContent = strings[language()].unavailable; }
}
for (const action of ["start", "stop", "restart"]) element(action).addEventListener("click", async () => { revealSequence++; clearToken(); try { await invoke(`desktop_${action}`); } catch { element("status").textContent = strings[language()].unavailable; } await refresh(); });
element("reveal").addEventListener("click", async () => {
  const sequence = ++revealSequence;
  clearToken();
  try { const token = await invoke("bootstrap_token", { generation }); if (sequence !== revealSequence || document.hidden) return; element("token").textContent = token; element("token").hidden = false; element("clear").hidden = false; } catch { clearToken(); }
});
element("clear").addEventListener("click", () => { revealSequence++; clearToken(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) { revealSequence++; clearToken(); } });
document.addEventListener("declaw-hide", () => { revealSequence++; clearToken(); });
element("language").addEventListener("change", () => { document.documentElement.lang = language(); for (const id of ["start", "stop", "restart", "reveal", "clear", "help"]) element(id).textContent = strings[language()][id]; refresh(); });
setInterval(refresh, 1000);
refresh();
