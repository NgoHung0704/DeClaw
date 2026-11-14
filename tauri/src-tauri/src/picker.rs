//! Directory-only, user-initiated selection. Settings remains the write authority.

use crate::{
    boundary::{authorize, Command},
    control::DesktopError,
    supervisor::SupervisorHandle,
};
use tauri_plugin_dialog::DialogExt;

#[tauri::command]
pub async fn pick_workspace(
    window: tauri::WebviewWindow,
    supervisor: tauri::State<'_, SupervisorHandle>,
    generation: u64,
) -> Result<Option<String>, DesktopError> {
    let url = window.url().map_err(|_| DesktopError::Unavailable)?;
    if !authorize(
        window.label(),
        url.as_str(),
        generation,
        &supervisor.lease(),
        Command::PickWorkspace,
    ) {
        return Err(DesktopError::Unavailable);
    }
    let (sender, receiver) = tauri::async_runtime::channel(1);
    window
        .dialog()
        .file()
        .set_parent(&window)
        .pick_folder(move |selection| {
            let _ = sender.blocking_send(selection);
        });
    let mut receiver = receiver;
    let selection = receiver.recv().await.ok_or(DesktopError::Unavailable)?;
    if !authorize(
        window.label(),
        window
            .url()
            .map_err(|_| DesktopError::Unavailable)?
            .as_str(),
        generation,
        &supervisor.lease(),
        Command::PickWorkspace,
    ) {
        return Err(DesktopError::Unavailable);
    }
    selection
        .map(|value| {
            value
                .into_path()
                .map_err(|_| DesktopError::Unavailable)
                .and_then(|path| {
                    if path.is_absolute() {
                        path.into_os_string()
                            .into_string()
                            .map_err(|_| DesktopError::Unavailable)
                    } else {
                        Err(DesktopError::Unavailable)
                    }
                })
        })
        .transpose()
}
