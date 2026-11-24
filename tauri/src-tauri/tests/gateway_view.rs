use declaw_desktop::{control::DesktopError, gateway_view::GatewayView};
use std::cell::Cell;

#[test]
fn failed_build_is_reported_and_open_can_retry_the_same_generation() {
    let view = GatewayView::default();
    let attempts = Cell::new(0);
    let failure: Result<(), DesktopError> = view.create(7, || {
        attempts.set(attempts.get() + 1);
        Err(DesktopError::Unavailable)
    });
    assert_eq!(failure, Err(DesktopError::Unavailable));
    assert!(view.failed(7));
    assert!(!view.failed(8));
    let success = view.create(7, || {
        attempts.set(attempts.get() + 1);
        Ok::<_, DesktopError>("gateway-7")
    });
    assert_eq!(success.unwrap(), "gateway-7");
    assert_eq!(attempts.get(), 2);
    assert!(!view.failed(7));
}
