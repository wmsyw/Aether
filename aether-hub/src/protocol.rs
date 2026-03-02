/// Tunnel binary frame protocol
///
/// Frame format (10-byte header + payload):
/// | stream_id (4B) | msg_type (1B) | flags (1B) | payload_len (4B) | payload (NB) |
use std::io::Read;

use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;

pub const HEADER_SIZE: usize = 10;

// Message types
pub const REQUEST_HEADERS: u8 = 0x01;
pub const REQUEST_BODY: u8 = 0x02;
pub const RESPONSE_HEADERS: u8 = 0x03;
pub const RESPONSE_BODY: u8 = 0x04;
pub const STREAM_END: u8 = 0x05;
pub const STREAM_ERROR: u8 = 0x06;
pub const PING: u8 = 0x10;
pub const PONG: u8 = 0x11;
pub const GOAWAY: u8 = 0x12;
pub const HEARTBEAT_DATA: u8 = 0x13;
pub const HEARTBEAT_ACK: u8 = 0x14;
pub const NODE_STATUS: u8 = 0x15;

// Flags
pub const FLAG_END_STREAM: u8 = 0x01;
pub const FLAG_GZIP_COMPRESSED: u8 = 0x02;

#[derive(Debug, Clone, Copy)]
pub struct FrameHeader {
    pub stream_id: u32,
    pub msg_type: u8,
    pub flags: u8,
    pub payload_len: u32,
}

impl FrameHeader {
    /// Parse frame header from raw bytes (must be >= HEADER_SIZE)
    #[inline]
    pub fn parse(data: &[u8]) -> Option<Self> {
        if data.len() < HEADER_SIZE {
            return None;
        }
        Some(Self {
            stream_id: u32::from_be_bytes([data[0], data[1], data[2], data[3]]),
            msg_type: data[4],
            flags: data[5],
            payload_len: u32::from_be_bytes([data[6], data[7], data[8], data[9]]),
        })
    }

    /// Check if this is a stream-terminating frame
    #[inline]
    pub fn is_stream_terminal(&self) -> bool {
        self.msg_type == STREAM_END || self.msg_type == STREAM_ERROR
    }
}

#[derive(Debug)]
pub struct RequestHeadersExtracted {
    pub node_id: String,
    pub rebuilt_frame: Vec<u8>,
}

/// Encode a STREAM_ERROR frame for a given stream_id with an error message
pub fn encode_stream_error(stream_id: u32, msg: &str) -> Vec<u8> {
    let payload = msg.as_bytes();
    let mut buf = Vec::with_capacity(HEADER_SIZE + payload.len());
    buf.extend_from_slice(&stream_id.to_be_bytes());
    buf.push(STREAM_ERROR);
    buf.push(0); // flags
    buf.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    buf.extend_from_slice(payload);
    buf
}

/// Encode a NODE_STATUS frame (stream_id=0, Hub-generated)
pub fn encode_node_status(node_id: &str, connected: bool, conn_count: usize) -> Vec<u8> {
    let payload = serde_json::json!({
        "node_id": node_id,
        "connected": connected,
        "conn_count": conn_count,
    });
    let payload_bytes = payload.to_string().into_bytes();
    let mut buf = Vec::with_capacity(HEADER_SIZE + payload_bytes.len());
    buf.extend_from_slice(&0u32.to_be_bytes()); // stream_id = 0
    buf.push(NODE_STATUS);
    buf.push(0); // flags
    buf.extend_from_slice(&(payload_bytes.len() as u32).to_be_bytes());
    buf.extend_from_slice(&payload_bytes);
    buf
}

/// Encode a PING frame (stream_id=0)
pub fn encode_ping() -> Vec<u8> {
    let mut buf = Vec::with_capacity(HEADER_SIZE);
    buf.extend_from_slice(&0u32.to_be_bytes());
    buf.push(PING);
    buf.push(0);
    buf.extend_from_slice(&0u32.to_be_bytes());
    buf
}

/// Encode a PONG frame (stream_id=0, echo payload)
pub fn encode_pong(payload: &[u8]) -> Vec<u8> {
    let mut buf = Vec::with_capacity(HEADER_SIZE + payload.len());
    buf.extend_from_slice(&0u32.to_be_bytes());
    buf.push(PONG);
    buf.push(0);
    buf.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    buf.extend_from_slice(payload);
    buf
}

/// Encode a GOAWAY frame (stream_id=0)
pub fn encode_goaway() -> Vec<u8> {
    let mut buf = Vec::with_capacity(HEADER_SIZE);
    buf.extend_from_slice(&0u32.to_be_bytes());
    buf.push(GOAWAY);
    buf.push(0);
    buf.extend_from_slice(&0u32.to_be_bytes());
    buf
}

/// Rewrite the stream_id in raw frame bytes (first 4 bytes) -- near zero-copy
#[inline]
pub fn rewrite_stream_id(data: &mut [u8], new_stream_id: u32) {
    let bytes = new_stream_id.to_be_bytes();
    data[0] = bytes[0];
    data[1] = bytes[1];
    data[2] = bytes[2];
    data[3] = bytes[3];
}

/// Get the payload portion of a raw frame (after the 10-byte header)
#[inline]
pub fn frame_payload(data: &[u8]) -> &[u8] {
    if data.len() > HEADER_SIZE {
        &data[HEADER_SIZE..]
    } else {
        &[]
    }
}

/// Parse REQUEST_HEADERS payload, extract `node_id`, strip it from JSON,
/// and rebuild a new REQUEST_HEADERS frame with `new_stream_id`.
///
/// If the source frame is gzip-compressed, this function will decode it first,
/// then try to re-encode with gzip (only keeps compression when payload shrinks).
pub fn rebuild_request_headers_without_node_id(
    data: &[u8],
    new_stream_id: u32,
) -> Result<RequestHeadersExtracted, String> {
    let header = FrameHeader::parse(data).ok_or_else(|| "invalid frame header".to_string())?;
    if header.msg_type != REQUEST_HEADERS {
        return Err("frame is not REQUEST_HEADERS".to_string());
    }

    let payload = frame_payload_by_header(data, &header)
        .ok_or_else(|| "incomplete REQUEST_HEADERS payload".to_string())?;

    let decoded_payload = if header.flags & FLAG_GZIP_COMPRESSED != 0 {
        let mut decoder = GzDecoder::new(payload);
        let mut decoded = Vec::new();
        decoder
            .read_to_end(&mut decoded)
            .map_err(|e| format!("failed to decompress REQUEST_HEADERS: {e}"))?;
        decoded
    } else {
        payload.to_vec()
    };

    let mut meta: serde_json::Value = serde_json::from_slice(&decoded_payload)
        .map_err(|e| format!("invalid REQUEST_HEADERS JSON: {e}"))?;
    let obj = meta
        .as_object_mut()
        .ok_or_else(|| "REQUEST_HEADERS payload must be a JSON object".to_string())?;

    let node_id = obj
        .remove("node_id")
        .and_then(|v| v.as_str().map(|s| s.to_string()))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "missing node_id in REQUEST_HEADERS".to_string())?;

    let stripped_payload = serde_json::to_vec(&meta)
        .map_err(|e| format!("failed to encode REQUEST_HEADERS payload: {e}"))?;
    let (final_payload, flags) =
        maybe_recompress_payload(&stripped_payload, header.flags & FLAG_GZIP_COMPRESSED != 0)
            .map_err(|e| format!("failed to recompress REQUEST_HEADERS payload: {e}"))?;

    let mut rebuilt = Vec::with_capacity(HEADER_SIZE + final_payload.len());
    rebuilt.extend_from_slice(&new_stream_id.to_be_bytes());
    rebuilt.push(REQUEST_HEADERS);
    rebuilt.push(flags);
    rebuilt.extend_from_slice(&(final_payload.len() as u32).to_be_bytes());
    rebuilt.extend_from_slice(&final_payload);

    Ok(RequestHeadersExtracted {
        node_id,
        rebuilt_frame: rebuilt,
    })
}

#[inline]
fn frame_payload_by_header<'a>(data: &'a [u8], header: &FrameHeader) -> Option<&'a [u8]> {
    let payload_len = header.payload_len as usize;
    let end = HEADER_SIZE.checked_add(payload_len)?;
    if data.len() < end {
        return None;
    }
    Some(&data[HEADER_SIZE..end])
}

fn maybe_recompress_payload(
    payload: &[u8],
    prefer_gzip: bool,
) -> Result<(Vec<u8>, u8), std::io::Error> {
    if !prefer_gzip {
        return Ok((payload.to_vec(), 0));
    }
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    std::io::Write::write_all(&mut encoder, payload)?;
    let compressed = encoder.finish()?;
    if compressed.len() < payload.len() {
        Ok((compressed, FLAG_GZIP_COMPRESSED))
    } else {
        Ok((payload.to_vec(), 0))
    }
}
