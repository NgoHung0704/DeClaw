//! Windows ownership: explicit inherited handles, suspended assignment, no breakaway.

use crate::control::DesktopError;
use std::{
    ffi::OsStr,
    fs::File,
    io::{Read, Write},
    mem::{size_of, zeroed},
    os::windows::{
        ffi::OsStrExt,
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
    },
    path::Path,
    ptr::{null, null_mut},
    sync::Arc,
    thread,
    time::{Duration, Instant},
};
use windows_sys::Win32::{
    Foundation::*,
    Security::SECURITY_ATTRIBUTES,
    System::{JobObjects::*, Pipes::CreatePipe, Threading::*},
};

fn handle(raw: HANDLE) -> Result<OwnedHandle, DesktopError> {
    if raw.is_null() || raw == INVALID_HANDLE_VALUE {
        return Err(DesktopError::SpawnFailed);
    }
    // All calls transfer a fresh, uniquely-owned Windows handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(raw) })
}

fn wide(value: &OsStr) -> Vec<u16> {
    value.encode_wide().chain(Some(0)).collect()
}

fn pipe(parent_reads: bool) -> Result<(File, OwnedHandle), DesktopError> {
    unsafe {
        let attributes = SECURITY_ATTRIBUTES {
            nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: null_mut(),
            bInheritHandle: 1,
        };
        let (mut read, mut write) = (null_mut(), null_mut());
        if CreatePipe(&mut read, &mut write, &attributes, 64 * 1024) == 0 {
            return Err(DesktopError::SpawnFailed);
        }
        let (read, write) = (handle(read)?, handle(write)?);
        let (parent, child) = if parent_reads {
            (read, write)
        } else {
            (write, read)
        };
        if SetHandleInformation(parent.as_raw_handle(), HANDLE_FLAG_INHERIT, 0) == 0 {
            return Err(DesktopError::SpawnFailed);
        }
        Ok((File::from(parent), child))
    }
}

struct Attributes {
    storage: Vec<usize>,
    initialized: bool,
}
impl Attributes {
    fn new(handles: &[HANDLE]) -> Result<Self, DesktopError> {
        unsafe {
            let mut bytes = 0;
            InitializeProcThreadAttributeList(null_mut(), 1, 0, &mut bytes);
            let mut result = Self {
                storage: vec![0; bytes.div_ceil(size_of::<usize>())],
                initialized: false,
            };
            let pointer = result.storage.as_mut_ptr().cast();
            if InitializeProcThreadAttributeList(pointer, 1, 0, &mut bytes) == 0 {
                return Err(DesktopError::SpawnFailed);
            }
            result.initialized = true;
            if UpdateProcThreadAttribute(
                pointer,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
                handles.as_ptr().cast(),
                std::mem::size_of_val(handles),
                null_mut(),
                null(),
            ) == 0
            {
                return Err(DesktopError::SpawnFailed);
            }
            Ok(result)
        }
    }
}
impl Drop for Attributes {
    fn drop(&mut self) {
        if self.initialized {
            unsafe {
                DeleteProcThreadAttributeList(self.storage.as_mut_ptr().cast());
            }
        }
    }
}

pub struct OwnedCore {
    job: OwnedHandle,
    process: Arc<OwnedHandle>,
    pub control: File,
    pub events: Option<File>,
    pub credentials: Option<File>,
}

impl OwnedCore {
    pub fn spawn(root: &Path, launch_id: &str) -> Result<Self, DesktopError> {
        let python = root
            .join(".venv/Scripts/python.exe")
            .canonicalize()
            .map_err(|_| DesktopError::InvalidSettings)?;
        if !root.join("declaw/desktop/__main__.py").is_file() {
            return Err(DesktopError::InvalidSettings);
        }
        Self::spawn_inner(root, &python, launch_id, None)
    }

    fn spawn_inner(
        root: &Path,
        python: &Path,
        launch_id: &str,
        helper: Option<&str>,
    ) -> Result<Self, DesktopError> {
        let (control, child_control) = pipe(false)?;
        let (events, child_events) = pipe(true)?;
        let (credentials, child_credentials) = pipe(true)?;
        let (stdout, child_stdout) = pipe(true)?;
        let (stderr, child_stderr) = pipe(true)?;
        let inherited = [
            child_control.as_raw_handle(),
            child_events.as_raw_handle(),
            child_credentials.as_raw_handle(),
            child_stdout.as_raw_handle(),
            child_stderr.as_raw_handle(),
        ];
        let mut attributes = Attributes::new(&inherited)?;
        let job = handle(unsafe { CreateJobObjectW(null(), null()) })?;
        unsafe {
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                job.as_raw_handle(),
                JobObjectExtendedLimitInformation,
                (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            ) == 0
            {
                return Err(DesktopError::SpawnFailed);
            }
        }
        // argv is fixed product syntax plus trusted canonical checkout/UUID/handles.
        // No shell is involved. Windows quote rules are needed only for the executable.
        let executable = python.to_string_lossy();
        if executable.contains(['"', '\0']) {
            return Err(DesktopError::InvalidSettings);
        }
        let arguments = if let Some(script) = helper {
            // Only internal Windows process tests call this private seam.
            format!("-c \"{script}\"")
        } else {
            format!("-m declaw.desktop --launch-id {launch_id} --control {} --events {} --credentials {}",
                inherited[0] as usize, inherited[1] as usize, inherited[2] as usize)
        };
        let mut command = wide(OsStr::new(&format!("\"{executable}\" {arguments}")));
        let application = wide(python.as_os_str());
        let directory = wide(root.as_os_str());
        unsafe {
            let mut startup: STARTUPINFOEXW = zeroed();
            startup.StartupInfo.cb = size_of::<STARTUPINFOEXW>() as u32;
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            startup.StartupInfo.hStdInput = inherited[0];
            startup.StartupInfo.hStdOutput = inherited[3];
            startup.StartupInfo.hStdError = inherited[4];
            startup.lpAttributeList = attributes.storage.as_mut_ptr().cast();
            let mut info: PROCESS_INFORMATION = zeroed();
            if CreateProcessW(
                application.as_ptr(),
                command.as_mut_ptr(),
                null(),
                null(),
                1,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
                null(),
                directory.as_ptr(),
                &startup.StartupInfo,
                &mut info,
            ) == 0
            {
                return Err(DesktopError::SpawnFailed);
            }
            let process = handle(info.hProcess)?;
            let main_thread = handle(info.hThread)?;
            if AssignProcessToJobObject(job.as_raw_handle(), process.as_raw_handle()) == 0 {
                TerminateProcess(process.as_raw_handle(), 1);
                WaitForSingleObject(process.as_raw_handle(), 5000);
                return Err(DesktopError::SpawnFailed);
            }
            if ResumeThread(main_thread.as_raw_handle()) == u32::MAX {
                TerminateJobObject(job.as_raw_handle(), 1);
                WaitForSingleObject(process.as_raw_handle(), 5000);
                return Err(DesktopError::SpawnFailed);
            }
            drop(main_thread);
            // The parent's copies of child endpoints close before readers start.
            drop((
                child_control,
                child_events,
                child_credentials,
                child_stdout,
                child_stderr,
            ));
            for mut output in [stdout, stderr] {
                thread::spawn(move || {
                    let mut scratch = [0_u8; 4096];
                    while let Ok(count) = output.read(&mut scratch) {
                        if count == 0 {
                            break;
                        }
                        // Unknown child text is never forwarded, persisted or matched.
                        scratch.fill(0);
                    }
                });
            }
            Ok(Self {
                job,
                process: Arc::new(process),
                control,
                events: Some(events),
                credentials: Some(credentials),
            })
        }
    }

    pub fn alive(&self) -> bool {
        unsafe { WaitForSingleObject(self.process.as_raw_handle(), 0) == WAIT_TIMEOUT }
    }

    pub fn probe(&self) -> ProcessProbe {
        ProcessProbe(self.process.clone())
    }

    pub fn exit_code(&self) -> Option<u32> {
        if self.alive() {
            return None;
        }
        let mut code = 0;
        if unsafe { GetExitCodeProcess(self.process.as_raw_handle(), &mut code) } == 0 {
            None
        } else {
            Some(code)
        }
    }

    pub fn write_control(&mut self, bytes: &[u8]) -> Result<(), DesktopError> {
        self.control
            .write_all(bytes)
            .map_err(|_| DesktopError::Unavailable)
    }

    pub fn active_processes(&self) -> Result<u32, DesktopError> {
        unsafe {
            let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = zeroed();
            if QueryInformationJobObject(
                self.job.as_raw_handle(),
                JobObjectBasicAccountingInformation,
                (&mut accounting as *mut JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                null_mut(),
            ) == 0
            {
                return Err(DesktopError::Unavailable);
            }
            Ok(accounting.ActiveProcesses)
        }
    }

    pub fn cleanup(&mut self, deadline: Instant) -> Result<(), DesktopError> {
        unsafe {
            TerminateJobObject(self.job.as_raw_handle(), 1);
        }
        loop {
            // Job accounting and process-handle signaling can settle separately.
            if self.active_processes()? == 0 && !self.alive() {
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err(DesktopError::ShutdownTimeout);
            }
            thread::sleep(Duration::from_millis(10));
        }
    }
}

#[derive(Clone)]
pub struct ProcessProbe(Arc<OwnedHandle>);
impl ProcessProbe {
    pub fn alive(&self) -> bool {
        unsafe { WaitForSingleObject(self.0.as_raw_handle(), 0) == WAIT_TIMEOUT }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_kills_descendants_and_preserves_unrelated_process() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let python = root.join(".venv/Scripts/python.exe");
        let mut unrelated = std::process::Command::new(&python)
            .args(["-c", "import time;time.sleep(60)"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .unwrap();
        let script = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);time.sleep(60)";
        let mut child = OwnedCore::spawn_inner(root, &python, "unused", Some(script)).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while child.active_processes().unwrap() < 2 && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        let count = child.active_processes().unwrap();
        let result = child.cleanup(Instant::now() + Duration::from_secs(5));
        let unrelated_alive = unrelated.try_wait().unwrap().is_none();
        let _ = unrelated.kill();
        let _ = unrelated.wait();
        assert!(count >= 2);
        assert!(result.is_ok());
        assert!(!child.alive());
        assert!(unrelated_alive);
    }

    use std::os::windows::process::CommandExt;
}
