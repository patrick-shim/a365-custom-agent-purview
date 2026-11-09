"""Read the signed-in human's OneDrive through a delegated Graph token."""
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import httpx

from extractors import DocumentError, extract_text


_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


@dataclass(frozen=True)
class Document:
    text: str = field(repr=False)
    metadata: dict


def normalize_path(path: str) -> str:
    path = path.strip().lstrip("/")
    if not path or len(path) > 1024 or any(ord(c) < 32 for c in path):
        raise DocumentError("Enter a OneDrive path such as test-summary.txt.")
    if "\\" in path or ":" in path or any(p in {"", ".", ".."} for p in path.split("/")):
        raise DocumentError("Use a path relative to your OneDrive root, not a URL or local disk path.")
    if not path.lower().endswith(".txt"):
        raise DocumentError("This version inspects UTF-8 .txt files only.")
    return path


class OneDriveClient:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def read_text(self, path: str, token: str) -> Document:
        path = normalize_path(path)
        base = self.settings.graph_base_url
        headers = {"Authorization": f"Bearer {token}"}
        metadata_url = f"{base}/me/drive/root:/{quote(path, safe='/')}"
        try:
            result = await self.client.get(metadata_url, headers=headers, params={
                "$select": "id,name,size,eTag,file,folder,remoteItem,parentReference,createdDateTime,lastModifiedDateTime"
            }, follow_redirects=False, timeout=_TIMEOUT, auth=None)
            self._require_ok(result)
            metadata = result.json()
            if not isinstance(metadata, dict) or not isinstance(metadata.get("file"), dict) or metadata.get("folder") or metadata.get("remoteItem"):
                raise DocumentError("Select a regular file in your own OneDrive. Shared shortcuts are not supported.")
            size = metadata.get("size")
            if not isinstance(size, int) or size < 0 or size > self.settings.max_file_bytes:
                raise DocumentError("The complete file exceeds the configured download limit or its size is unknown.")
            if not metadata.get("id") or not metadata.get("eTag") or not isinstance(metadata.get("name"), str):
                raise DocumentError("OneDrive did not return enough version information to inspect this file safely.")
            if not metadata["name"].lower().endswith(".txt"):
                raise DocumentError("This version inspects UTF-8 .txt files only.")
            content_url = f"{base}/me/drive/items/{quote(metadata['id'], safe='')}/content"
            # Never forward the Graph bearer token to a preauthenticated download host.
            async with self.client.stream("GET", content_url,
                                          headers={**headers, "If-Match": metadata["eTag"]},
                                          follow_redirects=False, timeout=_TIMEOUT, auth=None) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    self._validate_download_url(location)
                    data = await self._download(location)
                elif response.status_code == 200:
                    data = await self._read_complete(response)
                else:
                    self._require_ok(response)
                    raise DocumentError("OneDrive did not return a complete file.")
            if len(data) > self.settings.max_file_bytes or len(data) != size:
                raise DocumentError("The file was incomplete, changed, or exceeded the download limit.")
            # A second metadata read binds the verdict to this downloaded version.
            current = await self.client.get(metadata_url, headers=headers, params={"$select": "id,eTag"},
                                            follow_redirects=False, timeout=_TIMEOUT, auth=None)
            self._require_ok(current)
            latest = current.json()
            if not isinstance(latest, dict) or latest.get("id") != metadata["id"] or latest.get("eTag") != metadata["eTag"]:
                raise DocumentError("The file changed while being read. Try again.")
            text = extract_text(metadata["name"], data, self.settings.max_text_bytes)
            return Document(text, metadata)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DocumentError("OneDrive retrieval failed. No document content was sent to the model.") from None

    async def _download(self, url: str) -> bytes:
        for _ in range(4):
            self._validate_download_url(url)
            # build_request merges defaults and cookies; remove them explicitly
            # before sending to the signed download host, and disable client auth.
            request = self.client.build_request("GET", url, timeout=_TIMEOUT)
            request.headers.pop("Authorization", None)
            request.headers.pop("Cookie", None)
            response = await self.client.send(request, stream=True, auth=None, follow_redirects=False)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = response.headers.get("location", "")
                    continue
                self._require_ok(response)
                return await self._read_complete(response)
            finally:
                await response.aclose()
        raise DocumentError("OneDrive returned too many download redirects.")

    async def _read_complete(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("Content-Length")
        if declared_length is not None:
            try:
                if int(declared_length) < 0 or int(declared_length) > self.settings.max_file_bytes:
                    raise DocumentError("The file exceeds the configured download limit.")
            except ValueError:
                raise DocumentError("OneDrive returned an invalid content length.") from None
        chunks, length = [], 0
        async for chunk in response.aiter_bytes(chunk_size=min(65536, self.settings.max_file_bytes + 1)):
            length += len(chunk)
            if length > self.settings.max_file_bytes:
                raise DocumentError("The file exceeds the configured download limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_download_url(url: str) -> None:
        uri = urlparse(url)
        host = (uri.hostname or "").lower()
        # Business OneDrive Graph download URLs use SharePoint. Personal drives
        # and arbitrary external hosts are deliberately excluded from this demo.
        if uri.scheme != "https" or uri.username or uri.password or uri.port not in {None, 443} or not host.endswith(".sharepoint.com"):
            raise DocumentError("OneDrive returned an unsupported download host.")

    @staticmethod
    def _require_ok(response: httpx.Response) -> None:
        if response.status_code == 403:
            raise DocumentError("OneDrive denied access. Check delegated Files.Read consent and your file permissions.")
        if response.status_code == 404:
            raise DocumentError("The file was not found in the signed-in user's OneDrive.")
        if response.status_code != 200:
            raise DocumentError("OneDrive could not return the complete file. Try again after checking authentication.")
