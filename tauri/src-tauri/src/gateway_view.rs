//! Report gateway creation failures without restarting a healthy owned core.

use std::sync::Mutex;

#[derive(Default)]
pub struct GatewayView {
    failed_generation: Mutex<Option<u64>>,
}

impl GatewayView {
    pub fn create<T, E>(
        &self,
        generation: u64,
        build: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E> {
        let result = build();
        *self
            .failed_generation
            .lock()
            .unwrap_or_else(|e| e.into_inner()) = result.is_err().then_some(generation);
        result
    }

    pub fn failed(&self, generation: u64) -> bool {
        *self
            .failed_generation
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            == Some(generation)
    }
}
