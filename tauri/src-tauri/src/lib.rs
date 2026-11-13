mod bootstrap;
pub mod boundary;
pub mod control;
pub mod notifications;
mod picker;
pub mod supervisor;
mod tray;
pub mod view_gate;
#[cfg(windows)]
pub mod windows_job;

use boundary::{authorize, Command};
use control::DesktopError;
use std::{path::Path, sync::Arc};
use supervisor::{Snapshot, SupervisorHandle};
use tauri::Manager;

fn check(
    window: &tauri::WebviewWindow,
    supervisor: &SupervisorHandle,
    command: Command,
    generation: u64,
) -> Result<(), DesktopError> {
    if authorize(
        window.label(),
        window
            .url()
            .map_err(|_| DesktopError::Unavailable)?
            .as_str(),
        generation,
        &supervisor.lease(),
        command,
    ) {
        Ok(())
    } else {
        Err(DesktopError::Unavailable)
    }
}

#[tauri::command]
fn desktop_status(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
) -> Result<Snapshot, DesktopError> {
    check(&window, &supervisor, Command::Status, 0)?;
    Ok(supervisor.snapshot())
}

#[tauri::command]
fn desktop_start(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
) -> Result<(), DesktopError> {
    check(&window, &supervisor, Command::Start, 0)?;
    supervisor.start()
}

#[tauri::command]
fn desktop_stop(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
) -> Result<(), DesktopError> {
    check(&window, &supervisor, Command::Stop, 0)?;
    supervisor.stop()
}

#[tauri::command]
fn desktop_restart(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
) -> Result<(), DesktopError> {
    check(&window, &supervisor, Command::Restart, 0)?;
    supervisor.restart()
}

#[tauri::command]
async fn bootstrap_token(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
    generation: u64,
) -> Result<String, DesktopError> {
    check(&window, &supervisor, Command::BootstrapToken, generation)?;
    let handle = supervisor.inner().clone();
    let value = tauri::async_runtime::spawn_blocking(move || handle.token(generation))
        .await
        .map_err(|_| DesktopError::Unavailable)??;
    check(&window, &supervisor, Command::BootstrapToken, generation)?;
    Ok(value)
}

pub fn run() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            bootstrap::open(app)
        }))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            desktop_start,
            desktop_stop,
            desktop_restart,
            bootstrap_token,
            picker::pick_workspace
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let updates = handle.clone();
            let teardown = handle.clone();
            let exiting = handle.clone();
            let supervisor = SupervisorHandle::with_view_teardown(
                root.clone(),
                Arc::new(move |snapshot| {
                    let app = updates.clone();
                    let target = app.clone();
                    let _ = app
                        .run_on_main_thread(move || bootstrap::apply_snapshot(&target, snapshot));
                }),
                Arc::new(move |generation, reply| {
                    let target = teardown.clone();
                    let failed = reply.clone();
                    if teardown
                        .run_on_main_thread(move || {
                            bootstrap::destroy_gateway(&target, generation, reply)
                        })
                        .is_err()
                    {
                        let _ = failed.send(Err(DesktopError::Unavailable));
                    }
                }),
                Arc::new(move || exiting.exit(0)),
            );
            app.manage(supervisor.clone());
            bootstrap::show_bootstrap(&handle)?;
            tray::install(app)?;
            supervisor
                .start()
                .map_err(|_| "desktop supervisor unavailable")?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("desktop initialization failed");
    app.run(|app, event| {
        if let tauri::RunEvent::ExitRequested {
            code: None, api, ..
        } = event
        {
            api.prevent_exit();
            let _ = app.state::<SupervisorHandle>().quit();
        }
    });
}
