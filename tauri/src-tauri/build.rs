fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "desktop_status",
            "desktop_start",
            "desktop_stop",
            "desktop_restart",
            "bootstrap_token",
            "pick_workspace",
        ]),
    ))
    .expect("desktop build configuration invalid");
}
