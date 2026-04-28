use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use unicode_normalization::UnicodeNormalization;

const IMAGE_EXTENSIONS: &[&str] = &[".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"];
const VIDEO_EXTENSIONS: &[&str] = &[".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"];
const AUDIO_EXTENSIONS: &[&str] = &[".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"];
const TEXT_EXTENSIONS: &[&str] = &[
    ".txt", ".md", ".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv",
    ".log", ".sql", ".xml", ".html", ".css", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".go", ".rs", ".php", ".rb", ".sh", ".ps1", ".bat", ".env", ".properties", ".lua", ".kt", ".swift",
];
const ARCHIVE_EXTENSIONS: &[&str] = &[
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz",
];

fn classify_attachment_impl(filename: &str) -> &'static str {
    let normalized = filename.trim().rsplit(['/', '\\']).next().unwrap_or("").to_lowercase();

    if IMAGE_EXTENSIONS.iter().any(|ext| normalized.ends_with(ext)) {
        return "image";
    }
    if VIDEO_EXTENSIONS.iter().any(|ext| normalized.ends_with(ext)) {
        return "video";
    }
    if AUDIO_EXTENSIONS.iter().any(|ext| normalized.ends_with(ext)) {
        return "audio";
    }
    if TEXT_EXTENSIONS.iter().any(|ext| normalized.ends_with(ext)) {
        return "text";
    }
    if ARCHIVE_EXTENSIONS.iter().any(|ext| normalized.ends_with(ext)) {
        return "archive";
    }
    "unknown"
}

fn chunk_text_impl(text: &str, max_chars: usize) -> Vec<String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }

    let chars: Vec<char> = trimmed.chars().collect();
    let mut chunks: Vec<String> = Vec::new();
    let mut start = 0usize;

    while start < chars.len() {
        while start < chars.len() && chars[start].is_whitespace() {
            start += 1;
        }
        if start >= chars.len() {
            break;
        }

        let remaining = chars.len() - start;
        if remaining <= max_chars {
            let tail: String = chars[start..].iter().collect();
            let tail = tail.trim();
            if !tail.is_empty() {
                chunks.push(tail.to_string());
            }
            break;
        }

        let limit = start + max_chars;
        let mut split_at = limit;
        if limit < chars.len() && chars[limit].is_whitespace() {
            split_at = limit;
        } else {
            for idx in (start + 1..limit).rev() {
                if chars[idx].is_whitespace() {
                    split_at = idx;
                    break;
                }
            }
        }

        if split_at == limit {
            let chunk: String = chars[start..limit].iter().collect();
            chunks.push(chunk);
            start = limit;
            continue;
        }

        let chunk: String = chars[start..split_at].iter().collect();
        let chunk = chunk.trim();
        if !chunk.is_empty() {
            chunks.push(chunk.to_string());
        }
        start = split_at;
    }

    chunks
}

#[pyfunction]
fn normalize_message(text: &str) -> String {
    text.nfkc()
        .collect::<String>()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[pyfunction]
fn chunk_text(text: &str, max_chars: isize) -> PyResult<Vec<String>> {
    if max_chars <= 0 {
        return Err(PyValueError::new_err("max_chars must be greater than 0"));
    }
    Ok(chunk_text_impl(text, max_chars as usize))
}

#[pyfunction]
fn classify_attachment(filename: &str) -> &'static str {
    classify_attachment_impl(filename)
}

#[pymodule]
fn nightpaw_rs(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(normalize_message, module)?)?;
    module.add_function(wrap_pyfunction!(chunk_text, module)?)?;
    module.add_function(wrap_pyfunction!(classify_attachment, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{chunk_text_impl, classify_attachment_impl, normalize_message};

    #[test]
    fn normalize_message_collapses_whitespace_and_casefolds() {
        assert_eq!(normalize_message("  Hello\tWORLD  "), "hello world");
    }

    #[test]
    fn chunk_text_prefers_whitespace_breaks() {
        assert_eq!(
            chunk_text_impl("alpha beta gamma delta", 10),
            vec!["alpha beta".to_string(), "gamma".to_string(), "delta".to_string()]
        );
    }

    #[test]
    fn chunk_text_splits_long_tokens_when_needed() {
        assert_eq!(
            chunk_text_impl("supercalifragilistic", 5),
            vec![
                "super".to_string(),
                "calif".to_string(),
                "ragil".to_string(),
                "istic".to_string(),
            ]
        );
    }

    #[test]
    fn classify_attachment_detects_known_groups() {
        assert_eq!(classify_attachment_impl("photo.PNG"), "image");
        assert_eq!(classify_attachment_impl("clip.webm"), "video");
        assert_eq!(classify_attachment_impl("voice.ogg"), "audio");
        assert_eq!(classify_attachment_impl("notes.md"), "text");
        assert_eq!(classify_attachment_impl("backup.tar.gz"), "archive");
        assert_eq!(classify_attachment_impl("blob.bin"), "unknown");
    }
}
