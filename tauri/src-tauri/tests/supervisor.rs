use declaw_desktop::supervisor::{Lifecycle, State};

#[test]
fn duplicate_start_and_failed_cleanup_cannot_spawn_another_child() {
    let mut lifecycle = Lifecycle::default();
    assert!(lifecycle.start());
    let generation = lifecycle.generation;
    assert!(!lifecycle.start());
    assert!(!lifecycle.ready(generation - 1));
    assert_eq!(lifecycle.state, State::Starting);
    assert!(lifecycle.ready(generation));
    assert!(!lifecycle.ready(generation));
    lifecycle.fail();
    assert!(!lifecycle.start());
    lifecycle.cleaned();
    assert!(lifecycle.start());
    assert_eq!(lifecycle.generation, generation + 1);
    assert!(!lifecycle.ready(generation));
}

#[test]
fn stop_is_serial_and_readiness_cannot_resurrect_stopping_launch() {
    let mut lifecycle = Lifecycle::default();
    lifecycle.start();
    lifecycle.stop();
    assert_eq!(lifecycle.state, State::Stopping);
    assert!(!lifecycle.ready(lifecycle.generation));
    assert!(!lifecycle.start());
    lifecycle.cleaned();
    assert_eq!(lifecycle.state, State::Stopped);
}

#[cfg(windows)]
#[test]
fn actor_serializes_duplicate_starts_token_restart_and_quit_without_gui_waits() {
    use declaw_desktop::supervisor::SupervisorHandle;
    use std::{
        fs,
        path::Path,
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc, Mutex,
        },
        thread,
        time::{Duration, Instant},
    };
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let fixture = repo
        .join(".cache")
        .join(format!("desktop-actor-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(fixture.join(".venv/Scripts")).unwrap();
    fs::create_dir_all(fixture.join("declaw/desktop")).unwrap();
    fs::copy(
        repo.join(".venv/Scripts/python.exe"),
        fixture.join(".venv/Scripts/python.exe"),
    )
    .unwrap();
    fs::copy(
        repo.join(".venv/pyvenv.cfg"),
        fixture.join(".venv/pyvenv.cfg"),
    )
    .unwrap();
    fs::write(fixture.join("declaw/__init__.py"), "").unwrap();
    fs::write(fixture.join("declaw/desktop/__init__.py"), "").unwrap();
    fs::write(fixture.join("declaw/desktop/__main__.py"), r#"
import argparse,json,os,msvcrt,sys
p=argparse.ArgumentParser()
for name in ('launch-id','control','events','credentials'): p.add_argument('--'+name,required=True)
a=p.parse_args()
for value in (a.control,a.events,a.credentials): os.set_handle_inheritable(int(value),False)
control=os.fdopen(msvcrt.open_osfhandle(int(a.control),os.O_RDONLY|os.O_BINARY),'rb',buffering=0)
events=os.fdopen(msvcrt.open_osfhandle(int(a.events),os.O_WRONLY|os.O_BINARY),'wb',buffering=0)
credentials=os.fdopen(msvcrt.open_osfhandle(int(a.credentials),os.O_WRONLY|os.O_BINARY),'wb',buffering=0)
def send(stream,kind,**fields):
    stream.write((json.dumps(dict(type=kind,version=1,launch_id=a.launch_id,**fields))+'\n').encode())
sys.stdout.write('fake-'*50000);sys.stdout.flush()
sys.stderr.write('secret-'*50000);sys.stderr.flush()
send(events,'Ready',authority='127.0.0.1:7842')
for raw in control:
    frame=json.loads(raw)
    if frame['type']=='Stop':
        send(events,'Stopped',clean=True)
        break
    if frame['type']=='RequestBootstrapToken':
        send(credentials,'BootstrapToken',request_id=frame['request_id'],token='fixture-token')
"#).unwrap();
    let quit = Arc::new(AtomicBool::new(false));
    let quit_flag = quit.clone();
    let pending = Arc::new(Mutex::new(Vec::new()));
    let teardown = pending.clone();
    let handle = SupervisorHandle::with_view_teardown(
        fixture.clone(),
        Arc::new(|_| ()),
        Arc::new(move |generation, reply| {
            teardown.lock().unwrap().push((generation, reply));
        }),
        Arc::new(move || {
            quit_flag.store(true, Ordering::SeqCst);
        }),
    );
    let start = Instant::now();
    for _ in 0..8 {
        handle.start().unwrap();
    }
    assert!(start.elapsed() < Duration::from_millis(100));
    let deadline = Instant::now() + Duration::from_secs(10);
    while handle.snapshot().state != State::Running && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(handle.snapshot().state, State::Running);
    assert_eq!(handle.snapshot().generation, 1);
    assert_eq!(handle.token(1).unwrap(), "fixture-token");
    handle.restart().unwrap();
    while pending.lock().unwrap().is_empty() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    thread::sleep(Duration::from_millis(100));
    assert_eq!(
        handle.snapshot().generation,
        1,
        "restart raced ahead of window destruction"
    );
    assert!(!handle.lease().ready);
    let (generation, first_reply) = pending.lock().unwrap().pop().unwrap();
    assert_eq!(generation, 1);
    first_reply
        .send(Err(declaw_desktop::control::DesktopError::Unavailable))
        .unwrap();
    while handle.snapshot().state != State::Failed && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(handle.snapshot().state, State::Failed);
    assert_eq!(handle.snapshot().generation, 1);
    // Wait until the failure is consumed, even if core failure was observed first.
    // The error is queued before these stale success responses and drops them.
    while first_reply.send(Ok(())).is_ok() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    handle.start().unwrap();
    while pending.lock().unwrap().is_empty() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(
        first_reply.send(Ok(())).is_err(),
        "stale destruction result retained an active receiver"
    );
    let (generation, retry_reply) = pending.lock().unwrap().pop().unwrap();
    assert_eq!(generation, 1);
    retry_reply.send(Ok(())).unwrap();
    while (handle.snapshot().generation != 2 || handle.snapshot().state != State::Running)
        && Instant::now() < deadline
    {
        thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(handle.snapshot().generation, 2);
    assert_eq!(handle.snapshot().state, State::Running);
    assert!(handle.token(1).is_err());
    handle.quit().unwrap();
    while pending.lock().unwrap().is_empty() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    let (generation, reply) = pending.lock().unwrap().pop().unwrap();
    assert_eq!(generation, 2);
    reply.send(Ok(())).unwrap();
    while !quit.load(Ordering::SeqCst) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(quit.load(Ordering::SeqCst));
    assert!(!handle.lease().alive);
    // Remove only this test-created, resolved fixture after its owned Job is empty.
    let fixture = fixture.canonicalize().unwrap();
    let cache = repo.join(".cache").canonicalize().unwrap();
    assert!(fixture.starts_with(cache));
    fs::remove_dir_all(fixture).unwrap();
}
