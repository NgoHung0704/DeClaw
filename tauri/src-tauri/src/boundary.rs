//! The ACL is supplemented by exact caller and owned-generation checks.

#[derive(Clone, Copy)]
pub struct Lease {
    pub generation: u64,
    pub ready: bool,
    pub alive: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Command {
    Status,
    Start,
    Stop,
    Restart,
    BootstrapToken,
    PickWorkspace,
}

pub fn bootstrap_url(url: &str) -> bool {
    matches!(
        url,
        "http://tauri.localhost/"
            | "http://tauri.localhost/index.html"
            | "tauri://localhost/"
            | "tauri://localhost/index.html"
    )
}

pub fn gateway_url(value: &str) -> bool {
    let Ok(url) = tauri::Url::parse(value) else {
        return false;
    };
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(7842)
        && url.username().is_empty()
        && url.password().is_none()
}

pub fn gateway_label(generation: u64) -> String {
    format!("gateway-{generation}")
}

pub fn authorize(label: &str, url: &str, generation: u64, lease: &Lease, command: Command) -> bool {
    if label == "bootstrap" {
        let local = bootstrap_url(url);
        return local
            && command != Command::PickWorkspace
            && (command != Command::BootstrapToken
                || (generation == lease.generation && lease.ready && lease.alive));
    }
    label == gateway_label(lease.generation)
        && lease.generation > 0
        && gateway_url(url)
        && command == Command::PickWorkspace
        && generation == lease.generation
        && lease.ready
        && lease.alive
}
