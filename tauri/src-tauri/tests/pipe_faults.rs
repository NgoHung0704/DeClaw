#![cfg(windows)]

use declaw_desktop::supervisor::{State, SupervisorHandle};
use std::{
    fs,
    os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::WAIT_OBJECT_0,
    System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE},
};

// Synthetic core only: no listener, Application, settings, vault or model access.
const CORE: &str = r#"
import argparse,ctypes,json,msvcrt,os,pathlib,time
p=argparse.ArgumentParser()
for n in ('launch-id','control','events','credentials'): p.add_argument('--'+n,required=True)
a=p.parse_args()
for value in (a.control,a.events,a.credentials): os.set_handle_inheritable(int(value),False)
control=os.fdopen(msvcrt.open_osfhandle(int(a.control),os.O_RDONLY|os.O_BINARY),'rb',buffering=0)
events=os.fdopen(msvcrt.open_osfhandle(int(a.events),os.O_WRONLY|os.O_BINARY),'wb',buffering=0)
credentials=os.fdopen(msvcrt.open_osfhandle(int(a.credentials),os.O_WRONLY|os.O_BINARY),'wb',buffering=0)
def send(stream,kind,**fields):
    stream.write((json.dumps(dict(type=kind,version=1,launch_id=a.launch_id,**fields))+'\n').encode())
pathlib.Path('pid').write_text(str(os.getpid()))
send(events,'Ready',authority='127.0.0.1:7842')
mode=pathlib.Path('mode').read_text()
if mode=='eof':
    while not pathlib.Path('trigger').exists(): time.sleep(.005)
    events.close()
    time.sleep(60)
elif mode=='peek':
    peek=ctypes.windll.kernel32.PeekNamedPipe
    peek.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong),ctypes.c_void_p,ctypes.c_void_p]
    buffer=ctypes.create_string_buffer(65536)
    count=ctypes.c_ulong()
    last=None
    while peek(int(a.control),buffer,len(buffer),ctypes.byref(count),None,None):
        if count.value==len(buffer) and not pathlib.Path('full').exists():
            pathlib.Path('full').touch()
        # Deliberately acknowledge requests without consuming any pipe bytes.
        for line in reversed(buffer.raw[:count.value].splitlines()):
            try: frame=json.loads(line)
            except (ValueError,UnicodeError): continue
            request=frame.get('request_id')
            if request and request!=last:
                send(credentials,'BootstrapToken',request_id=request,token='fixture-only')
                last=request
            break
        time.sleep(.001)
else:
    for raw in control:
        if json.loads(raw)['type']=='Stop':
            send(events,'Stopped',clean=True)
            events.close()
            # EOF can precede process exit during a fully acknowledged stop.
            time.sleep(.2)
            break
"#;

fn wait_until(timeout: Duration, predicate: impl Fn() -> bool) -> bool {
    let limit = Instant::now() + timeout;
    while !predicate() {
        if Instant::now() >= limit {
            return false;
        }
        thread::sleep(Duration::from_millis(5));
    }
    true
}

fn fixture(mode: &str) -> (PathBuf, SupervisorHandle, Arc<AtomicBool>) {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let root = repo
        .join(".cache")
        .join(format!("desktop-pipe-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(root.join(".venv/Scripts")).unwrap();
    fs::create_dir_all(root.join("declaw/desktop")).unwrap();
    // The venv's Windows redirector retains inherited handles in its launcher
    // process, masking event EOF. Run the real interpreter with its runtime DLLs.
    let base = std::process::Command::new(repo.join(".venv/Scripts/python.exe"))
        .args(["-I", "-c", "import sys;print(sys._base_executable)"])
        .output()
        .unwrap();
    assert!(base.status.success());
    let base = PathBuf::from(String::from_utf8(base.stdout).unwrap().trim());
    fs::copy(&base, root.join(".venv/Scripts/python.exe")).unwrap();
    for entry in fs::read_dir(base.parent().unwrap()).unwrap() {
        let path = entry.unwrap().path();
        if path
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("dll"))
        {
            fs::copy(
                &path,
                root.join(".venv/Scripts").join(path.file_name().unwrap()),
            )
            .unwrap();
        }
    }
    fs::copy(repo.join(".venv/pyvenv.cfg"), root.join(".venv/pyvenv.cfg")).unwrap();
    fs::write(root.join("declaw/__init__.py"), "").unwrap();
    fs::write(root.join("declaw/desktop/__init__.py"), "").unwrap();
    fs::write(root.join("declaw/desktop/__main__.py"), CORE).unwrap();
    fs::write(root.join("mode"), mode).unwrap();
    let done = Arc::new(AtomicBool::new(false));
    let flag = done.clone();
    let handle = SupervisorHandle::new(
        root.clone(),
        Arc::new(|_| ()),
        Arc::new(move || {
            flag.store(true, Ordering::SeqCst);
        }),
    );
    handle.start().unwrap();
    assert!(wait_until(Duration::from_secs(8), || handle
        .snapshot()
        .state
        == State::Running));
    (root, handle, done)
}

fn finish(root: PathBuf, handle: &SupervisorHandle, done: &AtomicBool) {
    if !done.load(Ordering::SeqCst) {
        let result = handle.quit();
        assert!(result.is_ok() || done.load(Ordering::SeqCst));
    }
    assert!(
        wait_until(Duration::from_secs(5), || done.load(Ordering::SeqCst)),
        "Quit blocked behind pipe I/O"
    );
    assert!(!handle.lease().alive);
    let root = root.canonicalize().unwrap();
    let cache = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../.cache")
        .canonicalize()
        .unwrap();
    assert!(root.starts_with(cache));
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn event_eof_while_child_alive_revokes_lease_and_cleans_owned_job() {
    let (root, handle, done) = fixture("eof");
    assert!(handle.lease().alive && handle.lease().ready);
    fs::write(root.join("trigger"), "").unwrap();
    assert!(
        wait_until(Duration::from_secs(2), || !handle.lease().ready),
        "event EOF retained a ready lease"
    );
    assert_eq!(handle.snapshot().state, State::Failed);
    assert!(wait_until(Duration::from_secs(5), || !handle.lease().alive));
    finish(root, &handle, &done);
}

#[test]
fn clean_stop_frame_then_eof_before_exit_stays_clean() {
    let (root, handle, done) = fixture("clean");
    handle.stop().unwrap();
    assert!(wait_until(Duration::from_secs(5), || handle
        .snapshot()
        .state
        == State::Stopped));
    assert_eq!(handle.snapshot().clean_stop, Some(true));
    assert!(handle.snapshot().error.is_none());
    finish(root, &handle, &done);
}

#[test]
fn full_control_pipe_cannot_block_failure_deadline_or_quit() {
    let (root, handle, done) = fixture("peek");
    let requester = handle.clone();
    let requests = thread::spawn(move || {
        let mut completed = 0;
        for _ in 0..1200 {
            if requester.token(1).is_err() {
                break;
            }
            completed += 1;
        }
        completed
    });
    assert!(
        wait_until(Duration::from_secs(20), || root.join("full").exists()),
        "fault did not fill the native pipe"
    );
    // Quit must be processed while the native write is still pending, before
    // either the actor's write deadline or the token caller's timeout expires.
    handle.quit().unwrap();
    assert!(
        wait_until(Duration::from_secs(1), || !handle.lease().ready),
        "actor blocked in the control write"
    );
    finish(root, &handle, &done);
    let completed = requests.join().unwrap();
    assert!(completed > 100, "fault must actually fill the OS pipe");
    assert!(completed < 1200, "fault did not produce backpressure");
    assert_eq!(handle.snapshot().state, State::Failed);
    assert!(!handle.lease().ready);
}

#[test]
fn full_control_pipe_write_deadline_fails_and_cleans_without_quit() {
    let (root, handle, done) = fixture("peek");
    let pid = fs::read_to_string(root.join("pid"))
        .unwrap()
        .parse()
        .unwrap();
    let raw_process = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, pid) };
    assert!(!raw_process.is_null());
    // Hold an identity-stable process handle: lease revocation alone does not
    // prove that the child has actually been terminated by owned cleanup.
    let process = unsafe { OwnedHandle::from_raw_handle(raw_process) };
    let requester = handle.clone();
    let requests = thread::spawn(move || {
        let mut completed = 0;
        for _ in 0..1200 {
            if requester.token(1).is_err() {
                break;
            }
            completed += 1;
        }
        completed
    });
    assert!(
        wait_until(Duration::from_secs(20), || root.join("full").exists()),
        "fault did not fill the native pipe"
    );
    // Send no lifecycle action: the actor must enforce the two-second write
    // deadline itself, including after the token request has timed out.
    assert!(
        wait_until(Duration::from_secs(3), || !handle.lease().ready),
        "write deadline retained a ready lease without Quit"
    );
    assert_eq!(handle.snapshot().state, State::Failed);
    assert!(wait_until(Duration::from_secs(5), || unsafe {
        WaitForSingleObject(process.as_raw_handle(), 0) == WAIT_OBJECT_0
    }));
    assert!(
        !done.load(Ordering::SeqCst),
        "cleanup unexpectedly requested Quit"
    );
    let completed = requests.join().unwrap();
    assert!(completed > 100, "fault must actually fill the OS pipe");
    assert!(completed < 1200, "fault did not produce backpressure");
    finish(root, &handle, &done);
}
