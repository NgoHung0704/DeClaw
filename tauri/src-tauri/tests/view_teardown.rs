use declaw_desktop::{control::DesktopError, view_gate::ViewGate};
use std::{
    sync::mpsc,
    time::{Duration, Instant},
};

#[test]
fn restart_waits_for_actual_matching_view_destruction() {
    let mut gate = ViewGate::default();
    let now = Instant::now();
    gate.launched(1);
    let (reply, receive) = mpsc::channel();
    gate.requested(receive, now);
    assert!(!gate.poll(now).unwrap());
    assert!(!gate.clear());
    reply.send(Ok(())).unwrap();
    assert!(gate.poll(now).unwrap());
    gate.launched(2);
    assert!(!gate.clear());
    // The consumed generation-1 acknowledgement cannot clear generation 2.
    assert!(!gate.poll(now).unwrap());
}

#[test]
fn failure_or_timeout_blocks_retry_until_destruction_is_confirmed() {
    let now = Instant::now();
    let mut gate = ViewGate::default();
    gate.launched(1);
    let (reply, receive) = mpsc::channel();
    gate.requested(receive, now);
    assert_eq!(
        gate.poll(now + Duration::from_secs(6)),
        Err(DesktopError::Unavailable)
    );
    assert!(!gate.clear());
    // Late confirmation is still useful; timeout itself never grants clearance.
    reply.send(Ok(())).unwrap();
    assert!(gate.poll(now + Duration::from_secs(7)).unwrap());
    gate.launched(2);
    let (reply, receive) = mpsc::channel();
    gate.requested(receive, now);
    reply.send(Err(DesktopError::Unavailable)).unwrap();
    assert!(gate.poll(now).is_err());
    assert!(!gate.clear());
}
