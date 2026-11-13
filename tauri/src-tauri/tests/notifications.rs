use declaw_desktop::{
    control::{Event, Language, NoticeKind},
    notifications::NoticeGate,
};
use std::time::Duration;

fn notice(id: &str) -> Event {
    Event::Notice {
        version: 1,
        launch_id: "launch".into(),
        event_id: id.into(),
        kind: NoticeKind::Quarantine,
        language: Language::Fr,
        task_id: None,
        request_id: None,
    }
}

#[test]
fn native_notice_rate_dedup_and_fixed_localized_text() {
    let mut gate = NoticeGate::default();
    let first = gate.accept(&notice("1"), Duration::ZERO).unwrap();
    assert!(!first.body.contains("1"));
    assert!(first.body.contains("quarantaine"));
    assert!(gate.accept(&notice("1"), Duration::ZERO).is_none());
    for id in ["2", "3", "4", "5"] {
        assert!(gate.accept(&notice(id), Duration::ZERO).is_some());
    }
    assert!(gate.accept(&notice("6"), Duration::ZERO).is_none());
    assert!(gate.accept(&notice("7"), Duration::from_secs(60)).is_some());
}
