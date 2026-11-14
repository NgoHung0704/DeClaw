use declaw_desktop::control::{Credential, Event, FrameDecoder, ProtocolSession};

const LAUNCH: &str = "4c204ff1-9a00-4210-9a10-c39d869a5673";

fn ready() -> Vec<u8> {
    format!("{{\"type\":\"Ready\",\"version\":1,\"launch_id\":\"{LAUNCH}\",\"authority\":\"127.0.0.1:7842\"}}\n").into_bytes()
}

#[test]
fn strict_frames_and_generations() {
    let bytes = ready();
    let frame = Event::decode(&bytes).unwrap();
    let mut session = ProtocolSession::new(LAUNCH.to_string()).unwrap();
    session.accept(&frame).unwrap();
    assert!(session.accept(&frame).is_err());
    for replacement in ["true", "1.0", "\"1\"", "2"] {
        let bad = String::from_utf8(bytes.clone())
            .unwrap()
            .replace("\"version\":1", &format!("\"version\":{replacement}"));
        assert!(Event::decode(bad.as_bytes()).is_err());
    }
    for bad in [b"\xff\n".as_slice(), b"{}\n", b"[]\n", b"{}", b"{}\n{}\n"] {
        assert!(Event::decode(bad).is_err());
    }
    assert!(Event::decode(&vec![b'x'; 16 * 1024 + 1]).is_err());
    let bad = String::from_utf8(bytes.clone())
        .unwrap()
        .replace("127.0.0.1", "localhost");
    assert!(Event::decode(bad.as_bytes()).is_err());
    let extra = String::from_utf8(bytes)
        .unwrap()
        .replace("\"authority\"", "\"secret\":\"fake-secret\",\"authority\"");
    assert_eq!(
        format!("{:?}", Event::decode(extra.as_bytes()).unwrap_err()),
        "ProtocolInvalid"
    );
}

#[test]
fn decoder_bounds_partial_frames_and_eof() {
    let mut decoder = FrameDecoder::default();
    let bytes = ready();
    assert!(decoder.feed(&bytes[..8]).unwrap().is_empty());
    assert_eq!(decoder.feed(&bytes[8..]).unwrap().len(), 1);
    decoder.finish().unwrap();
    let mut decoder = FrameDecoder::default();
    assert!(decoder.feed(&vec![b'x'; 16 * 1024]).is_err());
    assert!(decoder.feed(&ready()).is_err());
    let mut decoder = FrameDecoder::default();
    decoder.feed(b"{").unwrap();
    assert!(decoder.finish().is_err());
}

#[test]
fn credential_reply_is_separate_correlated_and_redacted() {
    let bytes = format!("{{\"type\":\"BootstrapToken\",\"version\":1,\"launch_id\":\"{LAUNCH}\",\"request_id\":\"{LAUNCH}\",\"token\":\"fake-secret\"}}\n").into_bytes();
    assert!(Event::decode(&bytes).is_err());
    let reply = Credential::decode(&bytes).unwrap();
    assert!(!format!("{reply:?}").contains("fake-secret"));
    let mut session = ProtocolSession::new(LAUNCH.to_string()).unwrap();
    assert!(session.accept_token(&reply).is_err());
    session.request_token(LAUNCH.to_string()).unwrap();
    session.accept_token(&reply).unwrap();
    assert!(session.accept_token(&reply).is_err());
    session.close();
    assert!(session.request_token(LAUNCH.to_string()).is_err());
}
