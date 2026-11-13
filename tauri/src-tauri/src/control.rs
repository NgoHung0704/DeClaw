//! Bounded direction-specific control frames. Parser errors never contain payloads.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_CONTROL_BYTES: usize = 16 * 1024;
pub const MAX_CREDENTIAL_BYTES: usize = 4 * 1024;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DesktopError {
    InvalidSettings,
    PortConflict,
    SpawnFailed,
    ProtocolInvalid,
    StartupTimeout,
    ShutdownTimeout,
    Unavailable,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum Event {
    Ready {
        version: u8,
        launch_id: String,
        authority: String,
    },
    Failure {
        version: u8,
        launch_id: String,
        code: DesktopError,
    },
    Stopped {
        version: u8,
        launch_id: String,
        clean: bool,
    },
    Notice {
        version: u8,
        launch_id: String,
        event_id: String,
        kind: NoticeKind,
        language: Language,
        task_id: Option<String>,
        request_id: Option<String>,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum NoticeKind {
    Quarantine,
    ApprovalPending,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    En,
    Fr,
}

fn canonical_uuid(value: &str) -> bool {
    Uuid::parse_str(value).is_ok_and(|id| id.hyphenated().to_string() == value)
}

fn line(data: &[u8], limit: usize) -> Result<&[u8], DesktopError> {
    if data.len() > limit
        || data.last() != Some(&b'\n')
        || data[..data.len().saturating_sub(1)].contains(&b'\n')
    {
        return Err(DesktopError::ProtocolInvalid);
    }
    Ok(&data[..data.len() - 1])
}

impl Event {
    pub fn decode(data: &[u8]) -> Result<Self, DesktopError> {
        let frame: Self = serde_json::from_slice(line(data, MAX_CONTROL_BYTES)?)
            .map_err(|_| DesktopError::ProtocolInvalid)?;
        let (version, launch_id) = match &frame {
            Self::Ready {
                version,
                launch_id,
                authority,
            } => {
                if authority != "127.0.0.1:7842" {
                    return Err(DesktopError::ProtocolInvalid);
                }
                (*version, launch_id)
            }
            Self::Failure {
                version, launch_id, ..
            }
            | Self::Stopped {
                version, launch_id, ..
            } => (*version, launch_id),
            Self::Notice {
                version,
                launch_id,
                event_id,
                task_id,
                request_id,
                ..
            } => {
                if !canonical_uuid(event_id)
                    || task_id.as_ref().is_some_and(|id| !canonical_uuid(id))
                    || request_id.as_ref().is_some_and(|id| !canonical_uuid(id))
                {
                    return Err(DesktopError::ProtocolInvalid);
                }
                (*version, launch_id)
            }
        };
        if version != 1 || !canonical_uuid(launch_id) {
            return Err(DesktopError::ProtocolInvalid);
        }
        Ok(frame)
    }

    pub fn launch_id(&self) -> &str {
        match self {
            Self::Ready { launch_id, .. }
            | Self::Failure { launch_id, .. }
            | Self::Stopped { launch_id, .. }
            | Self::Notice { launch_id, .. } => launch_id,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Credential {
    pub r#type: String,
    pub version: u8,
    pub launch_id: String,
    pub request_id: String,
    pub token: String,
}

impl std::fmt::Debug for Credential {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("BootstrapToken([redacted])")
    }
}

impl Drop for Credential {
    fn drop(&mut self) {
        // Best-effort transient buffer clearing; OS vault token stays persistent.
        // Volatile writes keep this clear from being optimized away.
        unsafe {
            for byte in self.token.as_bytes_mut() {
                std::ptr::write_volatile(byte, 0);
            }
        }
    }
}

impl Credential {
    pub fn decode(data: &[u8]) -> Result<Self, DesktopError> {
        let frame: Self = serde_json::from_slice(line(data, MAX_CREDENTIAL_BYTES)?)
            .map_err(|_| DesktopError::ProtocolInvalid)?;
        if frame.r#type != "BootstrapToken"
            || frame.version != 1
            || !canonical_uuid(&frame.launch_id)
            || !canonical_uuid(&frame.request_id)
            || frame.token.is_empty()
            || frame.token.chars().any(|c| c < ' ')
        {
            return Err(DesktopError::ProtocolInvalid);
        }
        Ok(frame)
    }
}

#[derive(Default)]
pub struct FrameDecoder {
    bytes: Vec<u8>,
    failed: bool,
}

impl FrameDecoder {
    pub fn feed(&mut self, chunk: &[u8]) -> Result<Vec<Event>, DesktopError> {
        if self.failed {
            return Err(DesktopError::ProtocolInvalid);
        }
        let mut frames = Vec::new();
        for &byte in chunk {
            if self.bytes.len() >= MAX_CONTROL_BYTES - 1 && byte != b'\n' {
                self.failed = true;
                self.bytes.clear();
                return Err(DesktopError::ProtocolInvalid);
            }
            self.bytes.push(byte);
            if byte == b'\n' {
                match Event::decode(&self.bytes) {
                    Ok(frame) => frames.push(frame),
                    Err(error) => {
                        self.failed = true;
                        self.bytes.clear();
                        return Err(error);
                    }
                }
                self.bytes.clear();
            }
        }
        Ok(frames)
    }

    pub fn finish(&mut self) -> Result<(), DesktopError> {
        if self.failed || !self.bytes.is_empty() {
            self.failed = true;
            self.bytes.clear();
            return Err(DesktopError::ProtocolInvalid);
        }
        Ok(())
    }
}

pub struct ProtocolSession {
    launch_id: String,
    ready: bool,
    closed: bool,
    request: Option<String>,
}

impl ProtocolSession {
    pub fn new(launch_id: String) -> Result<Self, DesktopError> {
        if !canonical_uuid(&launch_id) {
            return Err(DesktopError::ProtocolInvalid);
        }
        Ok(Self {
            launch_id,
            ready: false,
            closed: false,
            request: None,
        })
    }

    pub fn accept(&mut self, frame: &Event) -> Result<(), DesktopError> {
        if self.closed || frame.launch_id() != self.launch_id {
            return Err(DesktopError::ProtocolInvalid);
        }
        if matches!(frame, Event::Ready { .. }) {
            if self.ready {
                return Err(DesktopError::ProtocolInvalid);
            }
            self.ready = true;
        }
        Ok(())
    }

    pub fn request_token(&mut self, id: String) -> Result<(), DesktopError> {
        if self.closed || self.request.is_some() || !canonical_uuid(&id) {
            return Err(DesktopError::ProtocolInvalid);
        }
        self.request = Some(id);
        Ok(())
    }

    pub fn accept_token(&mut self, frame: &Credential) -> Result<(), DesktopError> {
        if self.closed
            || frame.launch_id != self.launch_id
            || self.request.as_deref() != Some(frame.request_id.as_str())
        {
            return Err(DesktopError::ProtocolInvalid);
        }
        self.request = None;
        Ok(())
    }

    pub fn cancel_token(&mut self) {
        self.request = None;
    }
    pub fn close(&mut self) {
        self.closed = true;
        self.request = None;
    }
}
