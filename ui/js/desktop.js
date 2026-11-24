// Optional desktop bridge. Native validation and settings save remain authoritative.
export const isDesktopGateway = () =>
  `${window.location.protocol}//${window.location.host}` === window.__DECLAW_DESKTOP_ORIGIN__ &&
  Number.isSafeInteger(window.__DECLAW_DESKTOP_GENERATION__) &&
  typeof window.__TAURI__?.core?.invoke === "function";

export const hasWorkspacePicker = isDesktopGateway;

export const chooseWorkspace = async () => {
  if (!hasWorkspacePicker()) return null;
  const result = await window.__TAURI__.core.invoke("pick_workspace", {
    generation: window.__DECLAW_DESKTOP_GENERATION__,
  });
  if (result === null || typeof result === "string") return result;
  throw new Error("service_unavailable");
};
