import pytest

from extractors import DocumentError, extract_text


def test_utf8_document_is_preserved_completely_including_last_line():
    text = "회의 요약\n" + "ordinary text\n" * 20 + "synthetic sensitive marker at the end"
    assert extract_text("test.TXT", text.encode("utf-8"), 2048) == text


def test_utf8_bom_is_removed_without_losing_document_content():
    assert extract_text("test.txt", b"\xef\xbb\xbfDocument\r\nlast line", 100) == "Document\r\nlast line"


@pytest.mark.parametrize("name,content", [
    ("test.pdf", b"%PDF-1.7"), ("test.docx", b"PK\x03\x04"),
    ("test.txt.exe", b"hello"), ("test.png", b"image"),
])
def test_unsupported_types_are_rejected(name, content):
    with pytest.raises(DocumentError):
        extract_text(name, content, 1024)


@pytest.mark.parametrize("content", [b"\xff\xfeinvalid", b"secret\x00binary", b"text\x1b[31m", b"", b"  \r\n\t"])
def test_invalid_binary_or_empty_content_is_not_inspected_as_clean(content):
    with pytest.raises(DocumentError):
        extract_text("test.txt", content, 1024)


def test_limit_counts_bytes_not_characters_and_never_truncates():
    with pytest.raises(DocumentError):
        extract_text("test.txt", "한".encode("utf-8") * 10, 20)


def test_error_message_does_not_contain_document_bytes():
    with pytest.raises(DocumentError) as error:
        extract_text("test.txt", b"PRIVATE_CONTENT\x00", 1024)
    assert "PRIVATE_CONTENT" not in str(error.value)
