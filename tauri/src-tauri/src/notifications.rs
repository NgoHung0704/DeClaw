//! Safe native dispatch policy. Installed delivery is deferred to Phase 14.

use crate::control::{Event, Language, NoticeKind};
use std::{
    collections::{HashSet, VecDeque},
    time::Duration,
};

pub struct SafeNotice {
    pub title: &'static str,
    pub body: &'static str,
}
#[derive(Default)]
pub struct NoticeGate {
    recent: VecDeque<(String, NoticeKind, String)>,
    seen: HashSet<(String, NoticeKind, String)>,
    delivered: VecDeque<Duration>,
}

impl NoticeGate {
    pub fn accept(&mut self, event: &Event, now: Duration) -> Option<SafeNotice> {
        let Event::Notice {
            launch_id,
            event_id,
            kind,
            language,
            ..
        } = event
        else {
            return None;
        };
        let key = (launch_id.clone(), *kind, event_id.clone());
        if self.seen.contains(&key) {
            return None;
        }
        self.seen.insert(key.clone());
        self.recent.push_back(key);
        if self.recent.len() > 256 {
            if let Some(old) = self.recent.pop_front() {
                self.seen.remove(&old);
            }
        }
        while self
            .delivered
            .front()
            .is_some_and(|last| now.saturating_sub(*last) >= Duration::from_secs(60))
        {
            self.delivered.pop_front();
        }
        if self.delivered.len() >= 5 {
            return None;
        }
        self.delivered.push_back(now);
        let body = match (language, kind) {
            (Language::En, NoticeKind::Quarantine) => {
                "External content was quarantined. Review DeClaw."
            }
            (Language::Fr, NoticeKind::Quarantine) => {
                "Un contenu externe a été mis en quarantaine. Consultez DeClaw."
            }
            (Language::En, NoticeKind::ApprovalPending) => {
                "An action needs your approval in DeClaw."
            }
            (Language::Fr, NoticeKind::ApprovalPending) => {
                "Une action attend votre accord dans DeClaw."
            }
        };
        Some(SafeNotice {
            title: "DeClaw",
            body,
        })
    }
}
