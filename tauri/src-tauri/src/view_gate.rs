//! A new launch cannot reuse the origin until GUI destruction is confirmed.

use crate::control::DesktopError;
use std::{
    sync::mpsc::{Receiver, TryRecvError},
    time::{Duration, Instant},
};

pub struct ViewGate {
    generation: u64,
    clear: bool,
    pending: Option<(Receiver<Result<(), DesktopError>>, Instant)>,
    failed: bool,
}

impl Default for ViewGate {
    fn default() -> Self {
        Self {
            generation: 0,
            clear: true,
            pending: None,
            failed: false,
        }
    }
}

impl ViewGate {
    pub fn launched(&mut self, generation: u64) {
        self.generation = generation;
        self.clear = false;
        self.pending = None;
        self.failed = false;
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn clear(&self) -> bool {
        self.clear
    }
    pub fn needs_request(&self) -> bool {
        !self.clear && self.pending.is_none() && !self.failed
    }
    pub fn requested(&mut self, receive: Receiver<Result<(), DesktopError>>, now: Instant) {
        self.pending = Some((receive, now));
        self.failed = false;
    }
    pub fn retry(&mut self) {
        if self.failed {
            self.pending = None;
            self.failed = false;
        }
    }
    pub fn poll(&mut self, now: Instant) -> Result<bool, DesktopError> {
        if let Some((receive, since)) = &self.pending {
            match receive.try_recv() {
                Ok(Ok(())) => {
                    self.clear = true;
                    self.pending = None;
                    self.failed = false;
                }
                Ok(Err(error)) => {
                    self.pending = None;
                    self.failed = true;
                    return Err(error);
                }
                Err(TryRecvError::Disconnected) if !self.failed => {
                    self.pending = None;
                    self.failed = true;
                    return Err(DesktopError::Unavailable);
                }
                Err(_) => {
                    if !self.failed
                        && now.saturating_duration_since(*since) >= Duration::from_secs(5)
                    {
                        self.failed = true;
                        return Err(DesktopError::Unavailable);
                    }
                }
            }
        }
        Ok(self.clear)
    }
}
