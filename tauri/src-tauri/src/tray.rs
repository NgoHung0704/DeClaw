//! Tray is a native caller of the supervisor, never a webview event authority.

use crate::{
    bootstrap,
    supervisor::{State, SupervisorHandle},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

pub fn install(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open / Ouvrir", true, None::<&str>)?;
    let start = MenuItem::with_id(app, "start", "Start / Démarrer", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "Stop / Arrêter", false, None::<&str>)?;
    let restart = MenuItem::with_id(app, "restart", "Restart / Redémarrer", false, None::<&str>)?;
    let status = MenuItem::with_id(
        app,
        "status",
        "Status and login / État et connexion",
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, "quit", "Quit / Quitter", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &start, &stop, &restart, &status, &quit])?;
    let mut builder = TrayIconBuilder::with_id("declaw")
        .menu(&menu)
        .tooltip("DeClaw");
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder
        .on_menu_event(|app, event| {
            let supervisor = app.state::<SupervisorHandle>();
            match event.id.as_ref() {
                "open" => bootstrap::open(app),
                "status" => {
                    let _ = bootstrap::show_bootstrap(app);
                }
                "start" => {
                    let _ = supervisor.start();
                }
                "stop" => {
                    let _ = supervisor.stop();
                }
                "restart" => {
                    let _ = supervisor.restart();
                }
                "quit" => {
                    let _ = supervisor.quit();
                }
                _ => (),
            }
        })
        .build(app)?;
    // Poll only cheap snapshots; changes reflect actual supervisor/process state.
    let handle = app.handle().clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(std::time::Duration::from_millis(200));
        let state = handle.state::<SupervisorHandle>().snapshot().state;
        let _ = start.set_enabled(matches!(state, State::Stopped | State::Failed));
        let _ = stop.set_enabled(matches!(state, State::Starting | State::Running));
        let _ = restart.set_enabled(state == State::Running);
    });
    Ok(())
}
