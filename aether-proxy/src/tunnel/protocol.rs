//! Binary frame protocol for WebSocket tunnel multiplexing.
//!
//! Frame layout (10-byte header + variable payload):
//! ```text
//! | stream_id (4B) | msg_type (1B) | flags (1B) | payload_len (4B) | payload (NB) |
//! ```

use bytes::{Buf, BufMut, Bytes, BytesMut};

pub const HEADER_SIZE: usize = 10;

/// Frame flags.
pub mod flags {
    pub const END_STREAM: u8 = 0x01;
    pub const GZIP_COMPRESSED: u8 = 0x02;
}

/// Message types for the tunnel protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum MsgType {
    RequestHeaders = 0x01,
    RequestBody = 0x02,
    ResponseHeaders = 0x03,
    ResponseBody = 0x04,
    StreamEnd = 0x05,
    StreamError = 0x06,
    Ping = 0x10,
    Pong = 0x11,
    GoAway = 0x12,
    HeartbeatData = 0x13,
    HeartbeatAck = 0x14,
}

impl MsgType {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0x01 => Some(Self::RequestHeaders),
            0x02 => Some(Self::RequestBody),
            0x03 => Some(Self::ResponseHeaders),
            0x04 => Some(Self::ResponseBody),
            0x05 => Some(Self::StreamEnd),
            0x06 => Some(Self::StreamError),
            0x10 => Some(Self::Ping),
            0x11 => Some(Self::Pong),
            0x12 => Some(Self::GoAway),
            0x13 => Some(Self::HeartbeatData),
            0x14 => Some(Self::HeartbeatAck),
            _ => None,
        }
    }
}

/// A single multiplexed frame.
#[derive(Debug, Clone)]
pub struct Frame {
    pub stream_id: u32,
    pub msg_type: MsgType,
    pub flags: u8,
    pub payload: Bytes,
}

impl Frame {
    pub fn new(stream_id: u32, msg_type: MsgType, flags: u8, payload: impl Into<Bytes>) -> Self {
        Self {
            stream_id,
            msg_type,
            flags,
            payload: payload.into(),
        }
    }

    /// Control frame (stream_id = 0).
    pub fn control(msg_type: MsgType, payload: impl Into<Bytes>) -> Self {
        Self::new(0, msg_type, 0, payload)
    }

    pub fn is_end_stream(&self) -> bool {
        self.flags & flags::END_STREAM != 0
    }

    pub fn is_gzip(&self) -> bool {
        self.flags & flags::GZIP_COMPRESSED != 0
    }

    /// Encode into a binary buffer.
    pub fn encode(&self) -> Bytes {
        let mut buf = BytesMut::with_capacity(HEADER_SIZE + self.payload.len());
        buf.put_u32(self.stream_id);
        buf.put_u8(self.msg_type as u8);
        buf.put_u8(self.flags);
        buf.put_u32(self.payload.len() as u32);
        buf.put(self.payload.clone());
        buf.freeze()
    }

    /// Decode from a binary buffer.
    pub fn decode(mut data: Bytes) -> Result<Self, ProtocolError> {
        if data.len() < HEADER_SIZE {
            return Err(ProtocolError::TooShort {
                expected: HEADER_SIZE,
                actual: data.len(),
            });
        }
        let stream_id = data.get_u32();
        let msg_type_raw = data.get_u8();
        let frame_flags = data.get_u8();
        let payload_len = data.get_u32() as usize;

        if data.remaining() < payload_len {
            return Err(ProtocolError::Incomplete {
                expected: HEADER_SIZE + payload_len,
                actual: HEADER_SIZE + data.remaining(),
            });
        }

        let msg_type =
            MsgType::from_u8(msg_type_raw).ok_or(ProtocolError::UnknownMsgType(msg_type_raw))?;
        let payload = data.split_to(payload_len);

        Ok(Self {
            stream_id,
            msg_type,
            flags: frame_flags,
            payload,
        })
    }
}

/// Protocol errors.
#[derive(Debug, thiserror::Error)]
pub enum ProtocolError {
    #[error("frame too short: expected {expected} bytes, got {actual}")]
    TooShort { expected: usize, actual: usize },
    #[error("frame incomplete: expected {expected} bytes, got {actual}")]
    Incomplete { expected: usize, actual: usize },
    #[error("unknown message type: 0x{0:02x}")]
    UnknownMsgType(u8),
}

/// JSON payload for REQUEST_HEADERS frames.
#[derive(Debug, serde::Deserialize)]
pub struct RequestMeta {
    pub method: String,
    pub url: String,
    pub headers: std::collections::HashMap<String, String>,
    #[serde(default = "default_timeout")]
    pub timeout: u64,
}

fn default_timeout() -> u64 {
    60
}

/// JSON payload for RESPONSE_HEADERS frames.
#[derive(Debug, serde::Serialize)]
pub struct ResponseMeta {
    pub status: u16,
    /// Header list preserving duplicates (e.g. multiple Set-Cookie).
    pub headers: Vec<(String, String)>,
}
