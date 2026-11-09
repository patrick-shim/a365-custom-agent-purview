"""Conservative whole-file inspection: plain UTF-8 TXT only in this scaffold."""
from pathlib import PurePosixPath


class DocumentError(Exception):
    """Safe to show to the user; never includes document content."""


def extract_text(name: str, content: bytes, max_text_bytes: int) -> str:
    if PurePosixPath(name).suffix.lower() != ".txt":
        raise DocumentError("Only UTF-8 .txt files are supported. PDF, Office files, and images are not inspected by this version.")
    if len(content) > max_text_bytes:
        raise DocumentError("The complete file exceeds the inspection limit. It was not sent to the model.")
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise DocumentError("The file is not valid UTF-8 text. It was not sent to the model.") from None
    if any(ord(char) < 32 and char not in "\r\n\t" for char in text):
        raise DocumentError("The file contains unsupported binary or control data.")
    if not text.strip():
        raise DocumentError("The text file is empty.")
    return text
