use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

pub(super) fn request_target<'a>(body: &'a Value, fallback: &'a str) -> &'a str {
    let field = if body.get("model").is_some() {
        "model"
    } else {
        "agent"
    };
    body.get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|target| !target.is_empty())
        .unwrap_or(fallback)
}

pub(super) fn is_interaction(body: &Value) -> bool {
    body.get("id")
        .and_then(Value::as_str)
        .is_some_and(|id| !id.trim().is_empty())
        && matches!(
            body.get("status").and_then(Value::as_str),
            Some(
                "completed"
                    | "incomplete"
                    | "requires_action"
                    | "requires_continuation"
                    | "failed"
                    | "cancelled"
                    | "in_progress"
            )
        )
}

pub(super) fn failure_message(body: &Value) -> Option<String> {
    if let Some(error) = body.get("error").filter(|error| !error.is_null()) {
        return Some(
            error
                .get("message")
                .and_then(Value::as_str)
                .or_else(|| error.as_str())
                .unwrap_or("Gemini Interactions returned an error")
                .to_string(),
        );
    }
    match body.get("status").and_then(Value::as_str) {
        Some(status @ ("failed" | "cancelled" | "in_progress")) => {
            Some(format!("Gemini Interactions returned status {status}"))
        }
        Some("requires_action" | "requires_continuation") if !has_output(body) => {
            Some("Gemini Interactions requires further input without model output".to_string())
        }
        _ => None,
    }
}

fn has_output(body: &Value) -> bool {
    body.get("output_text")
        .and_then(Value::as_str)
        .is_some_and(|text| !text.trim().is_empty())
        || body
            .get("outputs")
            .and_then(Value::as_array)
            .is_some_and(|outputs| outputs.iter().any(meaningful_content))
        || body
            .get("steps")
            .and_then(Value::as_array)
            .is_some_and(|steps| {
                steps.iter().any(|step| {
                    step.get("type").and_then(Value::as_str) == Some("model_output")
                        && step
                            .get("content")
                            .and_then(Value::as_array)
                            .is_some_and(|content| content.iter().any(meaningful_content))
                })
            })
}

fn meaningful_content(content: &Value) -> bool {
    match content.get("type").and_then(Value::as_str) {
        Some("text") => content
            .get("text")
            .and_then(Value::as_str)
            .is_some_and(|text| !text.trim().is_empty()),
        Some("thought" | "thought_summary") | None => false,
        Some(_) => content.as_object().is_some_and(|content| content.len() > 1),
    }
}

#[derive(Default)]
struct InteractionStream {
    metadata: Map<String, Value>,
    completed: Option<Map<String, Value>>,
    usage: Map<String, Value>,
    steps: BTreeMap<u64, Value>,
    step_text: BTreeMap<u64, String>,
    outputs: BTreeMap<u64, Value>,
    output_text: BTreeMap<u64, String>,
}

impl InteractionStream {
    fn observe(&mut self, event_name: Option<&str>, event: Value) -> Option<()> {
        let kind = event
            .get("event_type")
            .or_else(|| event.get("type"))
            .and_then(Value::as_str)
            .or(event_name)?;
        if kind == "error" || kind == "interaction.error" || kind == "interaction.failed" {
            return None;
        }
        if let Some(usage) = event.get("usage").and_then(Value::as_object) {
            self.usage.extend(usage.clone());
        }
        if let Some(interaction) = event.get("interaction").and_then(Value::as_object) {
            if let Some(usage) = interaction.get("usage").and_then(Value::as_object) {
                self.usage.extend(usage.clone());
            }
            if matches!(kind, "interaction.completed" | "interaction.complete") {
                if !is_interaction(&event["interaction"]) {
                    return None;
                }
                self.completed = Some(interaction.clone());
            } else if kind == "interaction.created" {
                self.metadata.extend(interaction.clone());
            }
        } else if matches!(kind, "interaction.completed" | "interaction.complete") {
            return None;
        }
        let index = event.get("index").and_then(Value::as_u64).unwrap_or(0);
        match kind {
            "step.start" => {
                self.steps.insert(
                    index,
                    event
                        .get("step")?
                        .as_object()
                        .map(|value| Value::Object(value.clone()))?,
                );
            }
            "step.delta" => {
                let delta = event.get("delta")?;
                if delta.get("type").and_then(Value::as_str) == Some("text") {
                    self.step_text
                        .entry(index)
                        .or_default()
                        .push_str(delta.get("text")?.as_str()?);
                }
            }
            "content.start" => {
                self.outputs.insert(index, event.get("content")?.clone());
            }
            "content.delta" => {
                let delta = event.get("delta")?;
                if delta.get("type").and_then(Value::as_str) == Some("text") {
                    self.output_text
                        .entry(index)
                        .or_default()
                        .push_str(delta.get("text")?.as_str()?);
                }
            }
            "interaction.status_update" => {
                if matches!(
                    event.get("status").and_then(Value::as_str),
                    Some("failed" | "cancelled")
                ) {
                    return None;
                }
            }
            _ => {}
        }
        Some(())
    }

    fn finish(self) -> Option<Value> {
        let mut interaction = self.completed?;
        for (key, value) in self.metadata {
            interaction.entry(key).or_insert(value);
        }
        if !self.usage.is_empty() {
            let usage = interaction
                .entry("usage".to_string())
                .or_insert_with(|| json!({}));
            if let Some(usage) = usage.as_object_mut() {
                for (key, value) in self.usage {
                    usage.entry(key).or_insert(value);
                }
            }
        }
        merge_stream_content(&mut interaction, "steps", self.steps, self.step_text, true);
        merge_stream_content(
            &mut interaction,
            "outputs",
            self.outputs,
            self.output_text,
            false,
        );
        Some(Value::Object(interaction))
    }
}

fn merge_stream_content(
    interaction: &mut Map<String, Value>,
    field: &str,
    mut items: BTreeMap<u64, Value>,
    texts: BTreeMap<u64, String>,
    steps: bool,
) {
    for (index, text) in texts {
        let item = items.entry(index).or_insert_with(|| {
            if steps {
                json!({"type": "model_output"})
            } else {
                json!({"type": "text"})
            }
        });
        fill_text(item, &text, steps);
    }
    if items.is_empty() {
        return;
    }
    let output = interaction
        .entry(field.to_string())
        .or_insert_with(|| json!([]));
    let Some(output) = output.as_array_mut() else {
        return;
    };
    for (index, item) in items {
        if let Some(existing) = usize::try_from(index)
            .ok()
            .and_then(|index| output.get_mut(index))
        {
            if let Some(text) = if steps {
                item.get("content")
                    .and_then(Value::as_array)
                    .and_then(|content| {
                        content.iter().find_map(|part| {
                            (part.get("type").and_then(Value::as_str) == Some("text"))
                                .then(|| part.get("text").and_then(Value::as_str))
                                .flatten()
                        })
                    })
            } else {
                item.get("text").and_then(Value::as_str)
            } {
                fill_text(existing, text, steps);
            }
            if let (Some(existing), Some(item)) = (existing.as_object_mut(), item.as_object()) {
                for (key, value) in item {
                    let missing = existing.get(key).is_none_or(|value| {
                        value.is_null()
                            || value.as_array().is_some_and(Vec::is_empty)
                            || value.as_str().is_some_and(str::is_empty)
                    });
                    if missing {
                        existing.insert(key.clone(), value.clone());
                    }
                }
            }
        } else {
            output.push(item);
        }
    }
}

fn fill_text(item: &mut Value, text: &str, steps: bool) {
    if text.is_empty() {
        return;
    }
    if steps {
        let Some(object) = item.as_object_mut() else {
            return;
        };
        let content = object
            .entry("content".to_string())
            .or_insert_with(|| json!([]));
        if let Some(content) = content.as_array_mut() {
            if let Some(part) = content
                .iter_mut()
                .find(|part| part.get("type").and_then(Value::as_str) == Some("text"))
            {
                fill_text(part, text, false);
            } else {
                content.push(json!({"type": "text", "text": text}));
            }
        }
    } else if let Some(object) = item.as_object_mut() {
        if !object
            .get("text")
            .and_then(Value::as_str)
            .is_some_and(|text| !text.is_empty())
        {
            object.insert("text".to_string(), Value::String(text.to_string()));
        }
    }
}

pub(super) fn aggregate_stream_response(body: &[u8]) -> Option<Value> {
    // The terminal Interaction is partial on the official wire. Rebuild model output
    // from step.delta (Api-Revision 2026-05-20) or legacy content.delta, not a chat conversion.
    let text = std::str::from_utf8(body).ok()?;
    let mut stream = InteractionStream::default();
    let mut event_name = None;
    let mut data = String::new();
    for line in text.split_inclusive('\n') {
        // Only a complete LF or CRLF line can delimit an SSE event.
        let line = if let Some(line) = line.strip_suffix('\n') {
            line.strip_suffix('\r').unwrap_or(line)
        } else {
            line
        };
        if line.is_empty() {
            if !data.is_empty() && data.trim() != "[DONE]" {
                stream.observe(event_name, serde_json::from_str(&data).ok()?)?;
            }
            event_name = None;
            data.clear();
        } else if let Some(value) = line.strip_prefix("event:") {
            event_name = Some(value.trim());
        } else if let Some(value) = line.strip_prefix("data:") {
            if !data.is_empty() {
                data.push('\n');
            }
            data.push_str(value.strip_prefix(' ').unwrap_or(value));
        }
    }
    // An undelimited last event is not delivered by SSE and may be a truncated record.
    if !data.is_empty() {
        return None;
    }
    stream.finish()
}

#[cfg(test)]
mod tests {
    use super::aggregate_stream_response;
    use serde_json::json;

    #[test]
    fn gemini_interactions_sse_reconstructs_steps_with_crlf_and_lf() {
        for newline in ["\r\n", "\n"] {
            let stream = format!(
                "event: step.delta{newline}\
                 data: {{\"index\":0,\"delta\":{{\"type\":\"text\",\"text\":\"Hello\"}}}}{newline}{newline}\
                 event: interaction.completed{newline}\
                 data: {{\"interaction\":{{\"id\":\"native-stream\",\"status\":\"completed\"}}}}{newline}{newline}"
            );
            assert_eq!(
                aggregate_stream_response(stream.as_bytes()),
                Some(json!({
                    "id": "native-stream",
                    "status": "completed",
                    "steps": [{
                        "type": "model_output",
                        "content": [{"type": "text", "text": "Hello"}]
                    }]
                })),
                "{newline:?}"
            );
        }
    }

    #[test]
    fn gemini_interactions_sse_rejects_undelimited_crlf_and_lf_completion() {
        for newline in ["\r\n", "\n"] {
            let stream = format!(
                "data: {{\"event_type\":\"step.delta\",\"index\":0,\"delta\":{{\"type\":\"text\",\"text\":\"partial\"}}}}{newline}{newline}\
                 data: {{\"event_type\":\"interaction.completed\",\"interaction\":{{\"id\":\"native-stream\",\"status\":\"completed\"}}}}"
            );
            for ending in ["", newline, "\r\n\r"] {
                let truncated = format!("{stream}{ending}");
                assert!(
                    aggregate_stream_response(truncated.as_bytes()).is_none(),
                    "{truncated:?}"
                );
            }
        }
    }
}
