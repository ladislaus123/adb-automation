import os
import unittest

from adb_automation import downloaded_media


class FakeDownloadResponse:
    def __init__(self, chunks, headers=None, status=200):
        self.chunks = list(chunks)
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class DownloadedMediaTests(unittest.TestCase):
    def test_download_media_url_to_temp_uses_content_type_suffix(self):
        response = FakeDownloadResponse(
            [b"image-", b"bytes"],
            headers={"Content-Type": "image/jpeg", "Content-Length": "11"},
        )

        path = downloaded_media.download_media_url_to_temp(
            "https://example.test/media?id=1",
            opener=lambda request, timeout: response,
        )
        try:
            self.assertTrue(os.path.exists(path))
            self.assertTrue(
                os.path.basename(path).startswith(
                    downloaded_media.URL_MEDIA_TEMP_PREFIX
                )
            )
            self.assertEqual(os.path.splitext(path)[1], ".jpg")
            with open(path, "rb") as media_file:
                self.assertEqual(media_file.read(), b"image-bytes")
        finally:
            downloaded_media.cleanup_downloaded_media_file(path)

    def test_download_media_url_rejects_non_http_urls(self):
        with self.assertRaises(ValueError):
            downloaded_media.download_media_url_to_temp("file:///tmp/media.jpg")

    def test_cleanup_downloaded_media_file_ignores_regular_files(self):
        self.assertFalse(downloaded_media.is_downloaded_media_file("/tmp/plain.jpg"))


if __name__ == "__main__":
    unittest.main()
