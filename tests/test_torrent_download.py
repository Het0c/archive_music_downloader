from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import archive_album_search as app


class TorrentDownloadTests(TestCase):
    def test_torrent_url_encodes_identifier_as_path_segments(self) -> None:
        self.assertEqual(
            app.torrent_url("album con/rareza"),
            "https://archive.org/download/album%20con%2Frareza/"
            "album%20con%2Frareza_archive.torrent",
        )

    def test_download_torrent_preserves_archive_bytes(self) -> None:
        torrent = b"d4:infod4:name5:testeee"
        with TemporaryDirectory() as directory:
            with patch.object(app, "fetch_torrent", return_value=torrent):
                path = app.download_torrent("album: prueba", Path(directory))

            self.assertEqual(path.name, "album_prueba_archive.torrent")
            self.assertEqual(path.read_bytes(), torrent)

    def test_fetch_torrent_rejects_non_torrent_response(self) -> None:
        response = _FakeResponse(b"<html>not found</html>")
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "no devolvio un torrent valido"):
                app.fetch_torrent("missing-item")


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data
