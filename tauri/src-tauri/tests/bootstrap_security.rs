use declaw_desktop::boundary::{authorize, Command, Lease};

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
