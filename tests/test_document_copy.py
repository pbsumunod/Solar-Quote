import pytest

from screens.report_screen import copy_document_stream


class DocumentStream:
    """Java InputStream semantics, including mutation of the supplied byte array."""
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read(self, buffer):
        chunk = next(self.chunks, None)
        if chunk is None:
            return -1
        buffer[:len(chunk)] = chunk
        return len(chunk)


def test_document_copy_keeps_binary_utf8_content(tmp_path):
    path = tmp_path / "backup.json"
    stream = DocumentStream([b'{"name":"', "王明".encode("utf-8"), b'"}'])
    assert copy_document_stream(stream, path) == str(path)
    assert path.read_text(encoding="utf-8") == '{"name":"王明"}'


def test_large_document_removes_partial_private_copy(tmp_path):
    path = tmp_path / "partial.json"
    stream = DocumentStream([b"12345", b"67890"])
    with pytest.raises(ValueError, match="20 MB"):
        copy_document_stream(stream, path, max_bytes=9)
    assert not path.exists()


def test_provider_read_failure_removes_partial_private_copy(tmp_path):
    path = tmp_path / "partial.json"
    stream = DocumentStream([b"first bytes", b""])
    with pytest.raises(OSError, match="no data"):
        copy_document_stream(stream, path)
    assert not path.exists()
