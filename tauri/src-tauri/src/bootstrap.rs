//! Windows are created only from bundled bootstrap or an owned ready core.

use crate::{
    boundary::{authorize_download, bootstrap_url, gateway_label, gateway_url},
    control::DesktopError,
    supervisor::{Snapshot, State, SupervisorHandle},
};
use std::sync::{mpsc::Sender, Arc, Mutex};
use tauri::{
    webview::{DownloadEvent, NewWindowResponse},
    Manager, WebviewUrl, WebviewWindowBuilder,
};

pub fn destroy_gateway(
    app: &tauri::AppHandle,
    generation: u64,
    reply: Sender<Result<(), DesktopError>>,
) {
    let Some(window) = app.get_webview_window(&gateway_label(generation)) else {
        let _ = reply.send(Ok(()));
        return;
    };
    let reply = Arc::new(Mutex::new(Some(reply)));
    let destroyed = reply.clone();
    window.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Destroyed) {
            if let Some(reply) = destroyed.lock().unwrap_or_else(|e| e.into_inner()).take() {
                let _ = reply.send(Ok(()));
            }
        }
    });
    if window.destroy().is_err() {
        if let Some(reply) = reply.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = reply.send(Err(DesktopError::Unavailable));
        }
    }
}

pub fn show_bootstrap(app: &tauri::AppHandle) -> tauri::Result<()> {
    if let Some(window) = app.get_webview_window("bootstrap") {
        window.show()?;
        window.unminimize()?;
        window.set_focus()?;
        return Ok(());
    }
    let window = WebviewWindowBuilder::new(app, "bootstrap", WebviewUrl::App("index.html".into()))
        .title("DeClaw — Status / État")
        .inner_size(720.0, 540.0)
        .devtools(false)
        .on_navigation(|url| bootstrap_url(url.as_str()))
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .build()?;
    let hidden = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = hidden.eval("document.dispatchEvent(new Event('declaw-hide'))");
            let _ = hidden.hide();
        }
    });
    Ok(())
}

pub fn apply_snapshot(app: &tauri::AppHandle, snapshot: Snapshot) {
    let current = app.state::<SupervisorHandle>().snapshot();
    if current.generation != snapshot.generation || current.state != snapshot.state {
        return;
    }
    if snapshot.state != State::Running {
        let _ = show_bootstrap(app);
        return;
    }
    if app
        .get_webview_window(&gateway_label(snapshot.generation))
        .is_some()
    {
        return;
    }
    let generation = snapshot.generation;
    let supervisor = app.state::<SupervisorHandle>().inner().clone();
    // A queued main-thread callback must recheck liveness/generation before opening.
    let lease = supervisor.lease();
    if lease.generation != generation || !lease.alive || !lease.ready {
        return;
    }
    let navigation = supervisor.clone();
    let downloads = supervisor.clone();
    let initialization = format!(
        "Object.defineProperty(window,'__DECLAW_DESKTOP_GENERATION__',{{value:{generation},writable:false,configurable:false}});Object.defineProperty(window,'__DECLAW_DESKTOP_ORIGIN__',{{value:'http://127.0.0.1:7842',writable:false,configurable:false}});"
    );
    let result = app.state::<crate::gateway_view::GatewayView>().create(generation, || WebviewWindowBuilder::new(
        app,
        gateway_label(generation),
        WebviewUrl::External("http://127.0.0.1:7842/".parse().unwrap()),
    )
    .title("DeClaw")
    .inner_size(1180.0, 800.0)
    .devtools(false)
    .initialization_script(&initialization)
    .on_navigation(move |url| {
        let lease = navigation.lease();
        gateway_url(url.as_str()) && lease.generation == generation && lease.ready && lease.alive
    })
    .on_download(move |view, event| {
        let lease = downloads.lease();
        let Ok(source) = view.url() else { return false; };
        match event {
            DownloadEvent::Requested { url, destination } => {
                authorize_download(view.label(), source.as_str(), url.as_str(), generation, &lease)
                    && destination.is_absolute()
                    && !destination.exists()
            }
            DownloadEvent::Finished { url, success, .. } => {
                if authorize_download(view.label(), source.as_str(), url.as_str(), generation, &lease) {
                    let script = if success {
                        "window.dispatchEvent(new CustomEvent('declaw:download-finished',{detail:true}));"
                    } else {
                        "window.dispatchEvent(new CustomEvent('declaw:download-finished',{detail:false}));"
                    };
                    let _ = view.eval(script);
                }
                true
            }
            _ => false,
        }
    })
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .build());
    if let Ok(window) = result {
        let hidden = window.clone();
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = hidden.hide();
            }
        });
    } else {
        // Only fixed localized diagnostics are exposed by desktop_status.
        let _ = show_bootstrap(app);
    }
}

pub fn open(app: &tauri::AppHandle) {
    let lease = app.state::<SupervisorHandle>().lease();
    if let Some(window) = app
        .get_webview_window(&gateway_label(lease.generation))
        .filter(|_| lease.ready && lease.alive)
    {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    } else if lease.ready && lease.alive {
        apply_snapshot(app, app.state::<SupervisorHandle>().snapshot());
    } else {
        let _ = show_bootstrap(app);
    }
}
