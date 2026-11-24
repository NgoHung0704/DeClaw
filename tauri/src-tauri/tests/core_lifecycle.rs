#![cfg(windows)]
//! Run the production native actor + Python child without real vault/user data.

use declaw_desktop::supervisor::{State, SupervisorHandle};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

fn repo() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
}

#[test]
fn production_actor_and_python_stop_restart_with_isolated_encrypted_vault() {
    let fixture = repo()
        .join(".cache")
        .join(format!("desktop-core-{}", uuid::Uuid::new_v4()));
    for name in ["data", "workspace", "empty-plugins"] {
        fs::create_dir_all(fixture.join(name)).unwrap();
    }
    let result = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "isolated_core_worker",
            "--ignored",
            "--nocapture",
        ])
        .env("DECLAW_DESKTOP_TEST_FIXTURE", &fixture)
        .env("DECLAW_DATA_DIR", fixture.join("data"))
        .env("DECLAW_WORKSPACE_DIR", fixture.join("workspace"))
        .env("DECLAW_BUILTIN_PLUGINS_DIR", fixture.join("empty-plugins"))
        .env("DECLAW_HOST", "127.0.0.1")
        .env("DECLAW_PORT", "7842")
        .env("DECLAW_SANITIZER_REQUIRED", "false")
        .env("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
        .current_dir(repo())
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "isolated core lifecycle failed: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    let fixture = fixture.canonicalize().unwrap();
    assert!(fixture.starts_with(repo().join(".cache").canonicalize().unwrap()));
    fs::remove_dir_all(fixture).unwrap();
}

#[test]
#[ignore = "invoked by driver with a deliberately isolated environment"]
fn isolated_core_worker() {
    let fixture =
        PathBuf::from(std::env::var("DECLAW_DESKTOP_TEST_FIXTURE").expect("driver-only test"));
    assert!(fixture
        .canonicalize()
        .unwrap()
        .starts_with(repo().join(".cache").canonicalize().unwrap()));
    assert_eq!(
        std::env::var("PYTHON_KEYRING_BACKEND").unwrap(),
        "keyring.backends.fail.Keyring"
    );
    let done = Arc::new(AtomicBool::new(false));
    let callback = done.clone();
    let handle = SupervisorHandle::new(
        repo().to_path_buf(),
        Arc::new(|_| ()),
        Arc::new(move || {
            callback.store(true, Ordering::SeqCst);
        }),
    );
    handle.start().unwrap();
    wait_for(
        || handle.snapshot().state == State::Running,
        Duration::from_secs(25),
    );
    let token = handle.token(handle.snapshot().generation).unwrap();
    assert!(token.len() >= 40);
    drop(token);
    handle.stop().unwrap();
    wait_for(
        || matches!(handle.snapshot().state, State::Stopped | State::Failed),
        Duration::from_secs(12),
    );
    let stopped = handle.snapshot();
    assert_eq!(
        stopped.state,
        State::Stopped,
        "stop failed: {:?}",
        stopped.error
    );
    assert_eq!(stopped.clean_stop, Some(true));
    assert!(!handle.lease().alive);
    handle.start().unwrap();
    wait_for(
        || handle.snapshot().state == State::Running,
        Duration::from_secs(25),
    );
    assert_eq!(handle.snapshot().generation, 2);
    handle.quit().unwrap();
    wait_for(|| done.load(Ordering::SeqCst), Duration::from_secs(12));
    assert!(!handle.lease().alive);
}

fn wait_for(predicate: impl Fn() -> bool, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    while !predicate() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(predicate(), "isolated lifecycle deadline exceeded");
}
