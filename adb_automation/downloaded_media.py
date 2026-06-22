import mimetypes
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

URL_MEDIA_TEMP_PREFIX = "adb_automation_url_media_"
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_MEDIA_DOWNLOAD_BYTES = 100 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024


def validate_media_url(media_url):
    media_url = str(media_url or "").strip()
    parsed = urllib.parse.urlparse(media_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("file.url must be an absolute http or https URL.")
    return media_url


def media_download_suffix(filename, media_url, content_type=None):
    for candidate in (filename, urllib.parse.unquote(urllib.parse.urlparse(media_url).path)):
        suffix = safe_suffix(candidate)
        if suffix:
            return suffix

    if content_type:
        mime_type = content_type.split(";", 1)[0].strip().lower()
        guessed = mimetypes.guess_extension(mime_type)
        suffix = safe_suffix(f"file{guessed or ''}")
        if suffix:
            return suffix

    return ".bin"


def safe_suffix(filename):
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix and 1 < len(suffix) <= 16:
        return suffix
    return None


def response_header(response, name):
    headers = getattr(response, "headers", None)
    if headers is not None:
        return headers.get(name)

    info = getattr(response, "info", None)
    if callable(info):
        return response.info().get(name)
    return None


def response_status(response):
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(response, "code", None)
    return status


def content_length_exceeds_limit(content_length, max_bytes):
    if not content_length:
        return False
    try:
        return int(content_length) > max_bytes
    except (TypeError, ValueError):
        return False


def download_media_url_to_temp(
    media_url,
    filename=None,
    timeout=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes=MAX_MEDIA_DOWNLOAD_BYTES,
    opener=urllib.request.urlopen,
):
    media_url = validate_media_url(media_url)
    request = urllib.request.Request(
        media_url,
        headers={"User-Agent": "adb-automation/1.0"},
    )
    output_path = None

    try:
        with opener(request, timeout=timeout) as response:
            status = response_status(response)
            if status is not None and int(status) >= 400:
                raise ValueError(f"file.url returned HTTP status {status}.")

            content_length = response_header(response, "Content-Length")
            if content_length_exceeds_limit(content_length, max_bytes):
                raise ValueError("file.url media is larger than the download limit.")

            suffix = media_download_suffix(
                filename,
                media_url,
                response_header(response, "Content-Type"),
            )
            output = tempfile.NamedTemporaryFile(
                delete=False,
                prefix=URL_MEDIA_TEMP_PREFIX,
                suffix=suffix,
            )
            output_path = output.name

            total = 0
            with output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("file.url media is larger than the download limit.")
                    output.write(chunk)

            if total == 0:
                raise ValueError("file.url downloaded an empty media file.")

            return output_path
    except ValueError:
        cleanup_downloaded_media_file(output_path)
        raise
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        cleanup_downloaded_media_file(output_path)
        raise ValueError(f"could not download file.url media: {exc}") from exc


def is_downloaded_media_file(path):
    if not path:
        return False

    try:
        temp_dir = os.path.realpath(tempfile.gettempdir())
        file_dir = os.path.realpath(os.path.dirname(path))
    except (TypeError, ValueError):
        return False

    return file_dir == temp_dir and os.path.basename(path).startswith(
        URL_MEDIA_TEMP_PREFIX
    )


def cleanup_downloaded_media_file(path):
    if not is_downloaded_media_file(path):
        return

    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        print(f"[WARN] Could not remove downloaded media file {path}: {exc}")
