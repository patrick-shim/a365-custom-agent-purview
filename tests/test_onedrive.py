import asyncio
from types import SimpleNamespace

import httpx
import pytest

from extractors import DocumentError
from onedrive import OneDriveClient, normalize_path


TEXT = "First line\nOneDrive document\nsynthetic sensitive text at the very end"
DATA = TEXT.encode("utf-8")
TOKEN = "secret-delegated-graph-token"


def metadata(**changes):
    return dict(id="file-id", name="test.txt", size=len(DATA), eTag='"v1"',
                file={"mimeType": "text/plain"}, **changes)


def config(max_bytes=1024):
    return SimpleNamespace(graph_base_url="https://graph.microsoft.com/v1.0",
                           max_file_bytes=max_bytes, max_text_bytes=max_bytes)


def run(responses, *, path="test.txt", settings=None, default_auth=False):
    requests = []

    def handler(request):
        requests.append(request)
        response = responses[len(requests) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    async def fetch():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer inherited-token", "Cookie": "private-cookie"} if default_auth else None,
            auth=httpx.BasicAuth("private", "password") if default_auth else None,
        ) as client:
            result = await OneDriveClient(settings or config(), client).read_text(path, TOKEN)
            return result, requests

    return asyncio.run(fetch())


def initial(**changes):
    return httpx.Response(200, json=metadata() | changes)


def unchanged():
    return httpx.Response(200, json={"id": "file-id", "eTag": '"v1"'})


def test_complete_direct_graph_download_is_bound_to_file_version():
    document, requests = run([initial(), httpx.Response(200, content=DATA), unchanged()])
    assert document.text == TEXT
    assert len(requests) == 3
    assert requests[0].url.path == "/v1.0/me/drive/root:/test.txt"
    assert requests[2].url.path == "/v1.0/me/drive/root:/test.txt"
    assert all(request.headers["Authorization"] == f"Bearer {TOKEN}" for request in requests)
    assert requests[1].headers["If-Match"] == '"v1"'
    assert document.metadata["eTag"] == '"v1"'
    assert TEXT not in repr(document)


def test_preauthenticated_download_never_receives_graph_credentials():
    document, requests = run([
        initial(), httpx.Response(302, headers={"Location": "https://tenant-my.sharepoint.com/download?ticket=signed"}),
        httpx.Response(200, content=DATA), unchanged(),
    ])
    assert document.text == TEXT
    assert requests[2].url.host == "tenant-my.sharepoint.com"
    assert "authorization" not in requests[2].headers
    assert "cookie" not in requests[2].headers
    assert requests[3].headers["authorization"] == f"Bearer {TOKEN}"


def test_download_strips_inherited_headers_and_client_auth():
    document, requests = run([
        initial(), httpx.Response(302, headers={"Location": "https://tenant-my.sharepoint.com/download"}),
        httpx.Response(200, content=DATA), unchanged(),
    ], default_auth=True)
    assert document.text == TEXT
    assert "authorization" not in requests[2].headers
    assert "cookie" not in requests[2].headers
    assert requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert requests[1].headers["authorization"] == f"Bearer {TOKEN}"
    assert requests[3].headers["authorization"] == f"Bearer {TOKEN}"


def test_oversized_metadata_prevents_content_download():
    with pytest.raises(DocumentError):
        run([initial(size=1000000)], settings=config(128))


@pytest.mark.parametrize("download_host", [
    "http://tenant.sharepoint.com/download", "https://attacker.example/download",
    "https://tenant.sharepoint.com.attacker.example/download", "https://127.0.0.1/download",
    "https://user:password@tenant.sharepoint.com/download", "https://tenant.sharepoint.com:8443/download",
])
def test_untrusted_download_host_is_not_requested(download_host):
    with pytest.raises(DocumentError):
        run([initial(), httpx.Response(302, headers={"Location": download_host})])


def test_redirect_chain_is_validated_each_time():
    with pytest.raises(DocumentError):
        run([initial(), httpx.Response(302, headers={"Location": "https://tenant.sharepoint.com/download"}),
             httpx.Response(302, headers={"Location": "https://attacker.example/steal"})])


@pytest.mark.parametrize("latest", [{"id": "file-id", "eTag": '"v2"'},
                                     {"id": "replacement-file", "eTag": '"v1"'}, [], {}])
def test_changed_or_invalid_metadata_never_releases_document(latest):
    with pytest.raises(DocumentError):
        run([initial(), httpx.Response(200, content=DATA), httpx.Response(200, json=latest)])


def test_partial_download_is_rejected():
    with pytest.raises(DocumentError):
        run([initial(), httpx.Response(200, content=DATA[:-5])])


def test_partial_http_response_is_not_accepted():
    with pytest.raises(DocumentError):
        run([initial(), httpx.Response(206, content=DATA)])


class LargeStream(httpx.AsyncByteStream):
    def __init__(self):
        self.read_chunks = 0

    async def __aiter__(self):
        for _ in range(100):
            self.read_chunks += 1
            yield b"x" * 16


def test_direct_graph_download_stops_reading_when_limit_exceeded():
    stream = LargeStream()
    with pytest.raises(DocumentError):
        run([initial(size=32), httpx.Response(200, stream=stream)], settings=config(64))
    assert stream.read_chunks < 100


def test_redirected_download_stops_reading_when_limit_exceeded():
    stream = LargeStream()
    with pytest.raises(DocumentError):
        run([initial(size=32), httpx.Response(302, headers={"Location": "https://tenant.sharepoint.com/download"}),
             httpx.Response(200, stream=stream)], settings=config(64))
    assert stream.read_chunks < 100


@pytest.mark.parametrize("changes", [{"remoteItem": {"id": "shared"}}, {"folder": {"childCount": 1}},
                                     {"file": None}, {"name": "different.pdf"}, {"eTag": ""}])
def test_unsupported_file_or_metadata_is_rejected(changes):
    with pytest.raises(DocumentError):
        run([initial(**changes)])


@pytest.mark.parametrize("path", ["../test.txt", "folder/../test.txt", "C:\\test.txt", "https://example.com/test.txt",
                                  "folder//test.txt", "folder/./test.txt", "test.pdf", "bad\x00.txt"])
def test_path_must_be_relative_txt_without_traversal(path):
    with pytest.raises(DocumentError):
        normalize_path(path)


def test_path_encoding_preserves_literal_percent_and_unicode():
    _, requests = run([initial(), httpx.Response(200, content=DATA), unchanged()], path="Folder/보고서%20.txt")
    assert "%25" in str(requests[0].url)
    assert "/Folder/" in str(requests[0].url)


def test_network_error_is_safe_to_show():
    with pytest.raises(DocumentError) as error:
        run([httpx.ReadTimeout(f"private {TOKEN} document")])
    assert TOKEN not in str(error.value)
