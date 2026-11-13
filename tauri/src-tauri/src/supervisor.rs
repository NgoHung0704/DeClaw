//! Serialized supervisor. GUI requests enqueue; process waits never hold GUI locks.

use crate::{
    boundary::Lease,
    control::{
        Credential, DesktopError, Event, FrameDecoder, ProtocolSession, MAX_CREDENTIAL_BYTES,
    },
    view_gate::ViewGate,
    windows_job::{OwnedCore, ProcessProbe},
};
use serde::Serialize;
use std::{
    io::{BufRead, BufReader, Read},
    path::PathBuf,
    sync::{
        mpsc::{self, Receiver, SyncSender},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use uuid::Uuid;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Stopped,
    Starting,
    Running,
    Stopping,
    Failed,
}

pub struct Lifecycle {
    pub state: State,
    pub generation: u64,
    cleaned: bool,
}
impl Default for Lifecycle {
    fn default() -> Self {
        Self {
            state: State::Stopped,
            generation: 0,
            cleaned: true,
        }
    }
}
impl Lifecycle {
    pub fn start(&mut self) -> bool {
        if !self.cleaned || !matches!(self.state, State::Stopped | State::Failed) {
            return false;
        }
        self.generation += 1;
        self.state = State::Starting;
        self.cleaned = false;
        true
    }
    pub fn ready(&mut self, generation: u64) -> bool {
        if generation != self.generation || self.state != State::Starting {
            return false;
        }
        self.state = State::Running;
        true
    }
    pub fn stop(&mut self) {
        if matches!(self.state, State::Starting | State::Running) {
            self.state = State::Stopping;
        }
    }
    pub fn fail(&mut self) {
        self.state = State::Failed;
        self.cleaned = false;
    }
    pub fn cleaned(&mut self) {
        self.cleaned = true;
        if self.state != State::Failed {
            self.state = State::Stopped;
        }
    }
}

#[derive(Clone, Serialize)]
pub struct Snapshot {
    pub state: State,
    pub generation: u64,
    pub error: Option<DesktopError>,
    pub clean_stop: Option<bool>,
}
struct Shared {
    snapshot: Snapshot,
    probe: Option<ProcessProbe>,
}
enum Action {
    Start,
    Stop,
    Restart,
    Quit,
    Token(u64, mpsc::Sender<Result<String, DesktopError>>),
}
enum Incoming {
    Event(Event),
    Credential(Credential),
    Invalid,
    EventsClosed,
}

pub type ViewTeardown = Arc<dyn Fn(u64, mpsc::Sender<Result<(), DesktopError>>) + Send + Sync>;

#[derive(Clone)]
pub struct SupervisorHandle {
    commands: SyncSender<Action>,
    shared: Arc<Mutex<Shared>>,
}

impl SupervisorHandle {
    pub fn new(
        root: PathBuf,
        changed: Arc<dyn Fn(Snapshot) + Send + Sync>,
        quit: Arc<dyn Fn() + Send + Sync>,
    ) -> Self {
        Self::spawn_actor(root, changed, None, quit)
    }

    pub fn with_view_teardown(
        root: PathBuf,
        changed: Arc<dyn Fn(Snapshot) + Send + Sync>,
        close_view: ViewTeardown,
        quit: Arc<dyn Fn() + Send + Sync>,
    ) -> Self {
        Self::spawn_actor(root, changed, Some(close_view), quit)
    }

    fn spawn_actor(
        root: PathBuf,
        changed: Arc<dyn Fn(Snapshot) + Send + Sync>,
        close_view: Option<ViewTeardown>,
        quit: Arc<dyn Fn() + Send + Sync>,
    ) -> Self {
        let (commands, requests) = mpsc::sync_channel(32);
        let shared = Arc::new(Mutex::new(Shared {
            snapshot: Snapshot {
                state: State::Stopped,
                generation: 0,
                error: None,
                clean_stop: None,
            },
            probe: None,
        }));
        let actor_shared = shared.clone();
        thread::spawn(move || actor(root, requests, actor_shared, changed, close_view, quit));
        Self { commands, shared }
    }
    fn enqueue(&self, action: Action) -> Result<(), DesktopError> {
        self.commands
            .try_send(action)
            .map_err(|_| DesktopError::Unavailable)
    }
    pub fn start(&self) -> Result<(), DesktopError> {
        self.enqueue(Action::Start)
    }
    pub fn stop(&self) -> Result<(), DesktopError> {
        self.enqueue(Action::Stop)
    }
    pub fn restart(&self) -> Result<(), DesktopError> {
        self.enqueue(Action::Restart)
    }
    pub fn quit(&self) -> Result<(), DesktopError> {
        self.enqueue(Action::Quit)
    }
    pub fn snapshot(&self) -> Snapshot {
        let shared = self.shared.lock().unwrap_or_else(|e| e.into_inner());
        let mut snapshot = shared.snapshot.clone();
        if matches!(snapshot.state, State::Running)
            && !shared.probe.as_ref().is_some_and(ProcessProbe::alive)
        {
            snapshot.state = State::Failed;
            snapshot.error = Some(DesktopError::Unavailable);
        }
        snapshot
    }
    pub fn lease(&self) -> Lease {
        let shared = self.shared.lock().unwrap_or_else(|e| e.into_inner());
        Lease {
            generation: shared.snapshot.generation,
            ready: shared.snapshot.state == State::Running,
            alive: shared.probe.as_ref().is_some_and(ProcessProbe::alive),
        }
    }
    pub fn token(&self, generation: u64) -> Result<String, DesktopError> {
        let (reply, receive) = mpsc::channel();
        self.enqueue(Action::Token(generation, reply))?;
        receive
            .recv_timeout(Duration::from_secs(3))
            .map_err(|_| DesktopError::Unavailable)?
    }
}

fn readers(core: &mut OwnedCore, critical: SyncSender<Incoming>, notices: SyncSender<Event>) {
    let mut events = core.events.take().expect("one event reader");
    let event_sender = critical.clone();
    thread::spawn(move || {
        let mut decoder = FrameDecoder::default();
        let mut bytes = [0_u8; 4096];
        loop {
            match events.read(&mut bytes) {
                Ok(0) => {
                    if decoder.finish().is_err() {
                        let _ = event_sender.send(Incoming::Invalid);
                    }
                    break;
                }
                Ok(count) => match decoder.feed(&bytes[..count]) {
                    Ok(frames) => {
                        for frame in frames {
                            if matches!(frame, Event::Notice { .. }) {
                                let _ = notices.try_send(frame);
                            } else if event_sender.send(Incoming::Event(frame)).is_err() {
                                return;
                            }
                        }
                    }
                    Err(_) => {
                        let _ = event_sender.send(Incoming::Invalid);
                        break;
                    }
                },
                Err(_) => break,
            }
            bytes.fill(0);
        }
        let _ = event_sender.send(Incoming::EventsClosed);
    });
    let credentials = core.credentials.take().expect("one credential reader");
    thread::spawn(move || {
        let mut stream = BufReader::new(credentials);
        loop {
            let mut bytes = Vec::new();
            let result = stream
                .by_ref()
                .take((MAX_CREDENTIAL_BYTES + 1) as u64)
                .read_until(b'\n', &mut bytes);
            if matches!(result, Ok(0)) {
                break;
            }
            let frame = if result.is_ok() {
                Credential::decode(&bytes).map(Incoming::Credential)
            } else {
                Err(DesktopError::ProtocolInvalid)
            };
            bytes.fill(0);
            let invalid = frame.is_err();
            if critical.send(frame.unwrap_or(Incoming::Invalid)).is_err() || invalid {
                break;
            }
        }
    });
}

fn send(core: &mut OwnedCore, launch: &str, request: Option<&str>) -> Result<(), DesktopError> {
    let frame = if let Some(id) = request {
        serde_json::json!({"type":"RequestBootstrapToken", "version":1,"launch_id":launch,"request_id":id})
    } else {
        serde_json::json!({"type":"Stop","version":1,"launch_id":launch})
    };
    let mut bytes = serde_json::to_vec(&frame).map_err(|_| DesktopError::ProtocolInvalid)?;
    bytes.push(b'\n');
    core.write_control(&bytes)
}

fn publish(
    lifecycle: &Lifecycle,
    error: Option<DesktopError>,
    clean_stop: Option<bool>,
    core: Option<&OwnedCore>,
    shared: &Arc<Mutex<Shared>>,
    changed: &Arc<dyn Fn(Snapshot) + Send + Sync>,
) {
    // Closed state/error vocabulary only; child output and payloads never enter diagnostics.
    eprintln!(
        "desktop_state={:?} desktop_error={:?}",
        lifecycle.state, error
    );
    let snapshot = Snapshot {
        state: lifecycle.state,
        generation: lifecycle.generation,
        error,
        clean_stop,
    };
    {
        let mut current = shared.lock().unwrap_or_else(|e| e.into_inner());
        current.snapshot = snapshot.clone();
        current.probe = core.map(OwnedCore::probe);
    }
    changed(snapshot);
}

fn actor(
    root: PathBuf,
    requests: Receiver<Action>,
    shared: Arc<Mutex<Shared>>,
    changed: Arc<dyn Fn(Snapshot) + Send + Sync>,
    close_view: Option<ViewTeardown>,
    quit: Arc<dyn Fn() + Send + Sync>,
) {
    let mut lifecycle = Lifecycle::default();
    let mut core: Option<OwnedCore> = None;
    let mut launch = String::new();
    let mut protocol: Option<ProtocolSession> = None;
    let mut critical: Option<Receiver<Incoming>> = None;
    let mut notices: Option<Receiver<Event>> = None;
    let mut deadline: Option<Instant> = None;
    let mut error = None;
    let mut clean_stop = None;
    let mut stop_ack = None;
    let mut stop_requested = false;
    let mut event_eof = false;
    let mut exit_seen: Option<Instant> = None;
    let mut views = ViewGate::default();
    let mut restart = false;
    let mut quitting = false;
    let mut pending_start = false;
    let mut notice_gate = crate::notifications::NoticeGate::default();
    let clock = Instant::now();
    let mut token: Option<(Instant, mpsc::Sender<Result<String, DesktopError>>)> = None;
    loop {
        let next = if pending_start {
            pending_start = false;
            Some(Action::Start)
        } else {
            requests.recv_timeout(Duration::from_millis(10)).ok()
        };
        if let Some(action) = next {
            match action {
                Action::Start => {
                    #[cfg(debug_assertions)]
                    eprintln!(
                        "desktop_start_request state={:?} core={} views_clear={}",
                        lifecycle.state,
                        core.is_some(),
                        views.clear()
                    );
                    if !quitting && core.is_none() && !views.clear() {
                        restart = true;
                        views.retry();
                    } else if !quitting && core.is_none() && lifecycle.start() {
                        launch = Uuid::new_v4().to_string();
                        error = None;
                        clean_stop = None;
                        stop_ack = None;
                        stop_requested = false;
                        event_eof = false;
                        exit_seen = None;
                        if close_view.is_some() {
                            views.launched(lifecycle.generation);
                        }
                        publish(&lifecycle, error, clean_stop, None, &shared, &changed);
                        match OwnedCore::spawn(&root, &launch) {
                            Ok(mut owned) => {
                                let (sender, receiver) = mpsc::sync_channel(8);
                                let (notice_sender, notice_receiver) = mpsc::sync_channel(64);
                                readers(&mut owned, sender, notice_sender);
                                critical = Some(receiver);
                                notices = Some(notice_receiver);
                                protocol = ProtocolSession::new(launch.clone()).ok();
                                core = Some(owned);
                                deadline = Some(Instant::now() + Duration::from_secs(30));
                            }
                            Err(failure) => {
                                lifecycle.fail();
                                lifecycle.cleaned();
                                error = Some(failure);
                            }
                        }
                        publish(
                            &lifecycle,
                            error,
                            clean_stop,
                            core.as_ref(),
                            &shared,
                            &changed,
                        );
                    }
                }
                Action::Stop | Action::Restart | Action::Quit => {
                    restart = matches!(action, Action::Restart);
                    quitting |= matches!(action, Action::Quit);
                    views.retry();
                    if matches!(lifecycle.state, State::Starting | State::Running) {
                        lifecycle.stop();
                        stop_requested = true;
                        // Publish invalid lease before sending/waiting for cooperative shutdown.
                        publish(
                            &lifecycle,
                            error,
                            clean_stop,
                            core.as_ref(),
                            &shared,
                            &changed,
                        );
                        if let Some(owned) = core.as_mut() {
                            let _ = send(owned, &launch, None);
                        }
                        deadline = Some(Instant::now() + Duration::from_secs(10));
                    }
                }
                Action::Token(generation, reply) => {
                    if generation != lifecycle.generation
                        || lifecycle.state != State::Running
                        || !core.as_ref().is_some_and(OwnedCore::alive)
                        || token.is_some()
                    {
                        let _ = reply.send(Err(DesktopError::Unavailable));
                    } else {
                        let request = Uuid::new_v4().to_string();
                        let result = protocol
                            .as_mut()
                            .ok_or(DesktopError::Unavailable)
                            .and_then(|session| session.request_token(request.clone()))
                            .and_then(|()| send(core.as_mut().unwrap(), &launch, Some(&request)));
                        if let Err(failure) = result {
                            let _ = reply.send(Err(failure));
                        } else {
                            token = Some((Instant::now() + Duration::from_secs(2), reply));
                        }
                    }
                }
            }
        }
        if let Some(receiver) = &critical {
            for incoming in receiver.try_iter().take(8) {
                match incoming {
                    Incoming::Event(frame) => {
                        if protocol
                            .as_mut()
                            .is_none_or(|session| session.accept(&frame).is_err())
                        {
                            lifecycle.fail();
                            error = Some(DesktopError::ProtocolInvalid);
                        } else {
                            match frame {
                                Event::Ready { .. } => {
                                    if lifecycle.ready(lifecycle.generation) {
                                        deadline = None;
                                    }
                                }
                                Event::Failure { code, .. } => {
                                    lifecycle.fail();
                                    error = Some(code);
                                }
                                Event::Stopped { clean, .. } => {
                                    stop_ack = Some(clean);
                                    if !clean || !stop_requested {
                                        clean_stop = Some(false);
                                        error = Some(DesktopError::Unavailable);
                                        lifecycle.fail();
                                    }
                                }
                                Event::Notice { .. } => (),
                            }
                        }
                        publish(
                            &lifecycle,
                            error,
                            clean_stop,
                            core.as_ref(),
                            &shared,
                            &changed,
                        );
                    }
                    Incoming::Credential(frame) => {
                        let valid = protocol
                            .as_mut()
                            .is_some_and(|session| session.accept_token(&frame).is_ok());
                        if valid {
                            if let Some((_, reply)) = token.take() {
                                let _ = reply.send(Ok(frame.token.clone()));
                            }
                        } else {
                            lifecycle.fail();
                            error = Some(DesktopError::ProtocolInvalid);
                        }
                    }
                    Incoming::Invalid => {
                        lifecycle.fail();
                        error = Some(DesktopError::ProtocolInvalid);
                    }
                    Incoming::EventsClosed => {
                        event_eof = true;
                    }
                }
            }
        }
        // Native delivery is deferred by decision 7. Drain bounded, typed notice
        // traffic independently; authoritative in-app approval/quarantine stays intact.
        if let Some(receiver) = &notices {
            for frame in receiver.try_iter().take(64) {
                if protocol
                    .as_mut()
                    .is_none_or(|session| session.accept(&frame).is_err())
                {
                    lifecycle.fail();
                    error = Some(DesktopError::ProtocolInvalid);
                } else if lifecycle.state == State::Running {
                    let _ = notice_gate.accept(&frame, clock.elapsed());
                }
            }
        }
        if token
            .as_ref()
            .is_some_and(|(limit, _)| Instant::now() >= *limit)
        {
            if let Some((_, reply)) = token.take() {
                let _ = reply.send(Err(DesktopError::Unavailable));
            }
            if let Some(session) = protocol.as_mut() {
                session.cancel_token();
            }
        }
        if deadline.is_some_and(|limit| Instant::now() >= limit) {
            error = Some(if lifecycle.state == State::Starting {
                DesktopError::StartupTimeout
            } else {
                DesktopError::ShutdownTimeout
            });
            lifecycle.fail();
        }
        let exited = core.as_ref().is_some_and(|owned| !owned.alive());
        if exited && exit_seen.is_none() {
            exit_seen = Some(Instant::now());
        }
        // Let the event reader drain the clean-stop frame before classifying exit.
        let settled = exit_seen.is_some_and(|seen| seen.elapsed() >= Duration::from_millis(250));
        let tree_empty = core
            .as_ref()
            .and_then(|owned| owned.active_processes().ok())
            == Some(0);
        let exit_drained = exited && (event_eof || settled) && (tree_empty || settled);
        if exit_drained {
            #[cfg(debug_assertions)]
            eprintln!(
                "desktop_exit ack={:?} code={:?} active={:?}",
                stop_ack,
                core.as_ref().and_then(OwnedCore::exit_code),
                core.as_ref()
                    .and_then(|owned| owned.active_processes().ok())
            );
            let clean = stop_requested
                && stop_ack == Some(true)
                && error.is_none()
                && core.as_ref().and_then(OwnedCore::exit_code) == Some(0)
                && core
                    .as_ref()
                    .and_then(|owned| owned.active_processes().ok())
                    == Some(0);
            if stop_requested {
                clean_stop = Some(clean);
            }
            if !clean {
                lifecycle.fail();
                error = error.or(Some(DesktopError::Unavailable));
            }
        }
        if views.needs_request() && !matches!(lifecycle.state, State::Starting | State::Running) {
            if let Some(close) = &close_view {
                #[cfg(debug_assertions)]
                eprintln!(
                    "desktop_view_close_requested generation={}",
                    views.generation()
                );
                let (reply, receive) = mpsc::channel();
                views.requested(receive, Instant::now());
                close(views.generation(), reply);
            }
        }
        match views.poll(Instant::now()) {
            Err(failure) => {
                lifecycle.fail();
                error = Some(failure);
                if stop_requested {
                    clean_stop = Some(false);
                }
                publish(
                    &lifecycle,
                    error,
                    clean_stop,
                    core.as_ref(),
                    &shared,
                    &changed,
                );
            }
            Ok(true) if core.is_none() => {
                let previous = lifecycle.state;
                lifecycle.cleaned();
                if previous != lifecycle.state {
                    publish(&lifecycle, error, clean_stop, None, &shared, &changed);
                }
            }
            _ => (),
        }
        let cleanup = core.is_some() && (exit_drained || lifecycle.state == State::Failed);
        if cleanup {
            if stop_requested && clean_stop != Some(true) {
                clean_stop = Some(false);
            }
            if let Some(session) = protocol.as_mut() {
                session.close();
            }
            publish(&lifecycle, error, clean_stop, None, &shared, &changed);
            if let Some((_, reply)) = token.take() {
                let _ = reply.send(Err(DesktopError::Unavailable));
            }
            if let Some(owned) = core.as_mut() {
                if let Err(failure) = owned.cleanup(Instant::now() + Duration::from_secs(5)) {
                    lifecycle.fail();
                    error = Some(failure);
                    publish(&lifecycle, error, clean_stop, None, &shared, &changed);
                    // Keep the Job owned; don't permit a replacement before cleanup.
                    continue;
                }
            }
            core = None;
            critical = None;
            notices = None;
            protocol = None;
            deadline = None;
            if views.clear() {
                lifecycle.cleaned();
            }
            publish(&lifecycle, error, clean_stop, None, &shared, &changed);
        }
        if core.is_none() && quitting && views.clear() {
            quit();
            break;
        }
        if core.is_none() && restart && views.clear() {
            restart = false;
            pending_start = true;
        }
    }
}
