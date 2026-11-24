use declaw_desktop::boundary::{authorize, Command, Lease};

#[test]
fn downloads_require_the_live_gateway_and_exact_audit_endpoint() {
    use declaw_desktop::boundary::authorize_download;
    let lease = Lease {
        generation: 7,
        ready: true,
        alive: true,
    };
    let source = "http://127.0.0.1:7842/";
    let export = "http://127.0.0.1:7842/api/audit/export?day=2026-11-14&format=json";
    assert!(authorize_download("gateway-7", source, export, 7, &lease));
    for url in [
        "http://localhost:7842/api/audit/export?day=2026-11-14&format=json",
        "http://127.0.0.1:7843/api/audit/export?day=2026-11-14&format=json",
        "http://127.0.0.1:7842/api/settings?day=2026-11-14&format=json",
        "http://127.0.0.1:7842/api/audit/export?day=../../evil&format=json",
        "http://127.0.0.1:7842/api/audit/export?day=2026-11-14&format=exe",
        "http://127.0.0.1:7842/api/audit/export?day=2026-11-14&format=md&format=json",
        "http://127.0.0.1:7842/api/audit/export?day=2026-11-14&format=json&extra=1",
        "blob:http://127.0.0.1:7842/export",
    ] {
        assert!(!authorize_download("gateway-7", source, url, 7, &lease));
    }
    assert!(!authorize_download("bootstrap", source, export, 7, &lease));
    assert!(!authorize_download("gateway-6", source, export, 7, &lease));
    assert!(!authorize_download("gateway-7", source, export, 6, &lease));
    assert!(!authorize_download(
        "gateway-7",
        "http://evil.invalid/",
        export,
        7,
        &lease
    ));
    for invalid in [
        Lease {
            ready: false,
            ..lease
        },
        Lease {
            alive: false,
            ..lease
        },
    ] {
        assert!(!authorize_download(
            "gateway-7",
            source,
            export,
            7,
            &invalid
        ));
    }
}

#[test]
fn gateway_gets_only_picker_on_live_owned_generation() {
    let lease = Lease {
        generation: 7,
        ready: true,
        alive: true,
    };
    assert!(authorize(
        "gateway-7",
        "http://127.0.0.1:7842/",
        7,
        &lease,
        Command::PickWorkspace
    ));
    for command in [
        Command::Status,
        Command::Start,
        Command::Stop,
        Command::Restart,
        Command::BootstrapToken,
    ] {
        assert!(!authorize(
            "gateway-7",
            "http://127.0.0.1:7842/",
            7,
            &lease,
            command
        ));
    }
    for url in [
        "http://localhost:7842/",
        "http://127.0.0.1:7843/",
        "http://127.0.0.1:7842.evil/",
        "https://127.0.0.1:7842/",
        "http://evil@127.0.0.1:7842/",
    ] {
        assert!(!authorize(
            "gateway-7",
            url,
            7,
            &lease,
            Command::PickWorkspace
        ));
    }
    assert!(!authorize(
        "gateway-7",
        "http://127.0.0.1:7842/",
        6,
        &lease,
        Command::PickWorkspace
    ));
    for lease in [
        Lease {
            alive: false,
            ..lease
        },
        Lease {
            ready: false,
            ..lease
        },
    ] {
        assert!(!authorize(
            "gateway-7",
            "http://127.0.0.1:7842/",
            7,
            &lease,
            Command::PickWorkspace
        ));
    }
}

#[test]
fn bootstrap_is_local_and_never_gets_picker() {
    let lease = Lease {
        generation: 1,
        ready: false,
        alive: false,
    };
    assert!(authorize(
        "bootstrap",
        "http://tauri.localhost/",
        1,
        &lease,
        Command::Start
    ));
    assert!(authorize(
        "bootstrap",
        "http://tauri.localhost/index.html",
        1,
        &lease,
        Command::Start
    ));
    assert!(!authorize(
        "bootstrap",
        "http://127.0.0.1:7842/",
        1,
        &lease,
        Command::Start
    ));
    assert!(!authorize(
        "other",
        "http://tauri.localhost/",
        1,
        &lease,
        Command::Start
    ));
    assert!(!authorize(
        "bootstrap",
        "http://tauri.localhost/",
        1,
        &lease,
        Command::PickWorkspace
    ));
    assert!(!authorize(
        "bootstrap",
        "http://tauri.localhost/",
        1,
        &lease,
        Command::BootstrapToken
    ));
}

#[test]
fn capability_grants_are_explicit_disjoint_and_narrow() {
    let config: serde_json::Value =
        serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
    assert_eq!(
        config["app"]["security"]["capabilities"],
        serde_json::json!(["bootstrap", "gateway"])
    );
    let gateway: serde_json::Value =
        serde_json::from_str(include_str!("../capabilities/gateway.json")).unwrap();
    assert_eq!(
        gateway["permissions"],
        serde_json::json!(["allow-pick-workspace"])
    );
    assert_eq!(gateway["local"], false);
    assert_eq!(gateway["windows"], serde_json::json!(["gateway-*"]));
    assert_eq!(
        gateway["remote"]["urls"],
        serde_json::json!(["http://127.0.0.1:7842/*"])
    );
    let bootstrap: serde_json::Value =
        serde_json::from_str(include_str!("../capabilities/bootstrap.json")).unwrap();
    assert!(bootstrap.get("remote").is_none());
    assert_eq!(bootstrap["windows"], serde_json::json!(["bootstrap"]));
}

#[test]
fn old_native_window_cannot_claim_the_current_generation() {
    let lease = Lease {
        generation: 7,
        ready: true,
        alive: true,
    };
    assert!(!authorize(
        "gateway",
        "http://127.0.0.1:7842/",
        7,
        &lease,
        Command::PickWorkspace
    ));
    assert!(!authorize(
        "gateway-6",
        "http://127.0.0.1:7842/",
        7,
        &lease,
        Command::PickWorkspace
    ));
    assert!(authorize(
        "gateway-7",
        "http://127.0.0.1:7842/",
        7,
        &lease,
        Command::PickWorkspace
    ));
}
