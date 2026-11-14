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

/// Browser downloads are a native event, not an additional remote IPC command.
pub fn authorize_download(
    label: &str,
    source: &str,
    destination: &str,
    generation: u64,
    lease: &Lease,
) -> bool {
    if !authorize(label, source, generation, lease, Command::PickWorkspace)
        || !gateway_url(destination)
    {
        return false;
    }
    let Ok(url) = tauri::Url::parse(destination) else {
        return false;
    };
    if url.path() != "/api/audit/export" || url.fragment().is_some() {
        return false;
    }
    let query: Vec<_> = url.query_pairs().collect();
    query.len() == 2
        && query.iter().any(|(key, value)| {
            key == "day"
                && value.len() == 10
                && value.bytes().enumerate().all(|(i, byte)| {
                    if i == 4 || i == 7 {
                        byte == b'-'
                    } else {
                        byte.is_ascii_digit()
                    }
                })
        })
        && query
            .iter()
            .any(|(key, value)| key == "format" && matches!(value.as_ref(), "json" | "md"))
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
