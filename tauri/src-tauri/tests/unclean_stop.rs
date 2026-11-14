#![cfg(windows)]

use declaw_desktop::supervisor::{State, SupervisorHandle};
use std::{
    fs,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

#[test]
fn stopped_false_and_exit_without_acknowledgement_are_failed_stops() {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    for mode in ["unclean", "crash"] {
        let fixture = repo
            .join(".cache")
            .join(format!("desktop-stop-{}", uuid::Uuid::new_v4()));
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
        let script = r#"
import argparse,json,os,msvcrt
p=argparse.ArgumentParser()
for n in ('launch-id','control','events','credentials'): p.add_argument('--'+n,required=True)
a=p.parse_args()
control=os.fdopen(msvcrt.open_osfhandle(int(a.control),os.O_RDONLY|os.O_BINARY),'rb',buffering=0)
events=os.fdopen(msvcrt.open_osfhandle(int(a.events),os.O_WRONLY|os.O_BINARY),'wb',buffering=0)
def send(kind,**fields): events.write((json.dumps(dict(type=kind,version=1,launch_id=a.launch_id,**fields))+'\n').encode())
send('Ready',authority='127.0.0.1:7842')
for raw in control:
    if json.loads(raw)['type']=='Stop':
        if 'MODE'=='unclean': send('Stopped',clean=False)
        else: os._exit(7)
        break
"#.replace("MODE", mode);
        fs::write(fixture.join("declaw/desktop/__main__.py"), script).unwrap();
        let finished = Arc::new(AtomicBool::new(false));
        let flag = finished.clone();
        let handle = SupervisorHandle::new(
            fixture.clone(),
            Arc::new(|_| ()),
            Arc::new(move || {
                flag.store(true, Ordering::SeqCst);
            }),
        );
        handle.start().unwrap();
        let deadline = Instant::now() + Duration::from_secs(8);
        while handle.snapshot().state != State::Running && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(handle.snapshot().state, State::Running);
        handle.stop().unwrap();
        while !matches!(handle.snapshot().state, State::Stopped | State::Failed)
            && Instant::now() < deadline
        {
            thread::sleep(Duration::from_millis(10));
        }
        let final_state = handle.snapshot();
        handle.quit().unwrap();
        while !finished.load(Ordering::SeqCst) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        assert!(finished.load(Ordering::SeqCst));
        let fixture = fixture.canonicalize().unwrap();
        assert!(fixture.starts_with(repo.join(".cache").canonicalize().unwrap()));
        fs::remove_dir_all(fixture).unwrap();
        assert_eq!(
            final_state.state,
            State::Failed,
            "unclean {mode} reported as success"
        );
        assert!(final_state.error.is_some());
    }
}
