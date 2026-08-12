#!/usr/bin/env python3
"""Search music albums on archive.org and download their torrent files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import socket
import ssl
import sys
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "archive-music-downloader/1.0 (local script; https://musicbrainz.org/doc/MusicBrainz_API)"


@dataclass
class AlbumSearch:
    title: str = ""
    artist: str = ""
    album: str = ""
    year_album: str = ""
    term: str = ""

    def display_name(self) -> str:
        parts = [self.album, self.artist, self.title, self.year_album, self.term]
        return " - ".join(part for part in parts if part)

    def minimum_info(self) -> dict[str, str]:
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year_album": self.year_album,
        }


@dataclass
class ArchiveResult:
    index: int
    identifier: str
    title: str
    creator: str
    date: str
    track_matches: list[str]
    match_score: int


class NetworkLookupError(RuntimeError):
    """Raised when a remote hostname cannot be resolved."""


def is_network_lookup_error(exc: BaseException) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in [
            "NameResolutionError",
            "No address associated with hostname",
            "Temporary failure in name resolution",
            "Failed to resolve",
            "Name or service not known",
        ]
    )


def clean_name(value: str) -> str:
    value = re.sub(r"[^\w\s.-]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value.strip())
    return value or "archive_album"


def build_query(term: str, collection: str | None) -> str:
    parts = [f'({term})', 'mediatype:"audio"']
    if collection:
        parts.append(f'collection:"{collection}"')
    return " AND ".join(parts)


def quote_query(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def metadata_terms(search: AlbumSearch) -> list[str]:
    terms: list[str] = []
    if search.album:
        album = quote_query(search.album)
        terms.append(f"(title:{album} OR album:{album} OR description:{album})")
    if search.artist:
        artist = quote_query(search.artist)
        terms.append(f"(creator:{artist} OR artist:{artist} OR title:{artist} OR description:{artist})")
    if search.title:
        title = quote_query(search.title)
        terms.append(f"(title:{title} OR track:{title} OR description:{title})")
    if search.year_album:
        year = quote_query(search.year_album)
        terms.append(f"(date:{year} OR year:{year})")
    if search.term:
        terms.append(f"({search.term})")
    return terms


def build_metadata_query(search: AlbumSearch, collection: str | None) -> str:
    terms = metadata_terms(search)
    if not terms:
        raise ValueError("Agrega al menos album, artista, cancion o busqueda libre.")
    parts = [*terms, 'mediatype:"audio"']
    if collection:
        parts.append(f'collection:"{collection}"')
    return " AND ".join(parts)


def metadata_query_variants(search: AlbumSearch, collection: str | None) -> list[str]:
    variants = [build_metadata_query(search, collection)]
    if search.album or search.artist:
        variants.append(
            build_metadata_query(
                AlbumSearch(album=search.album, artist=search.artist, year_album=search.year_album),
                collection,
            )
        )
    if search.title or search.artist:
        variants.append(build_metadata_query(AlbumSearch(title=search.title, artist=search.artist), collection))
    if search.display_name():
        variants.append(build_query(search.display_name(), collection))
    return list(dict.fromkeys(variants))


def first_value(value: object, default: str = "") -> str:
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value) if value is not None else default


def walk_values(data: Any) -> Iterable[Any]:
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk_values(value)
    elif isinstance(data, list):
        for item in data:
            yield from walk_values(item)


def pick_field(data: Any, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for node in walk_values(data):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if key.lower() in wanted and value not in (None, "", []):
                return first_value(value)
    return ""


def request_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            raise NetworkLookupError(f"No se pudo resolver el host de {url}. Revisa DNS/conexion.") from exc
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as retry_exc:
            if isinstance(retry_exc.reason, socket.gaierror):
                raise NetworkLookupError(f"No se pudo resolver el host de {url}. Revisa DNS/conexion.") from retry_exc
            raise


def musicbrainz_query(search: AlbumSearch) -> str:
    parts: list[str] = []
    if search.title:
        parts.append(f'recording:"{search.title}"')
    if search.artist:
        parts.append(f'artist:"{search.artist}"')
    if search.album:
        parts.append(f'release:"{search.album}"')
    if search.year_album:
        parts.append(f'date:{search.year_album}')
    if not parts and search.term:
        parts.append(search.term)
    if not parts:
        raise ValueError("Para usar MusicBrainz agrega cancion, artista, album o busqueda libre.")
    return " AND ".join(parts)


def artist_credit_name(recording: dict[str, Any], fallback: str = "") -> str:
    credits = recording.get("artist-credit", [])
    names = [first_value(credit.get("name")) for credit in credits if isinstance(credit, dict)]
    return ", ".join(name for name in names if name) or fallback


def release_year(release: dict[str, Any]) -> str:
    date = first_value(release.get("date"))
    match = re.search(r"\b(19|20)\d{2}\b", date)
    return match.group(0) if match else ""


def best_musicbrainz_release(recording: dict[str, Any], fallback: AlbumSearch) -> dict[str, Any]:
    releases = recording.get("releases", [])
    if not isinstance(releases, list) or not releases:
        return {}

    def score(release: dict[str, Any]) -> tuple[int, str]:
        value = 0
        title = normalize_text(first_value(release.get("title")))
        if fallback.album and normalize_text(fallback.album) in title:
            value += 6
        if release_year(release):
            value += 2
        if first_value(release.get("status")).lower() == "official":
            value += 2
        if first_value(release.get("release-group", {}).get("primary-type")).lower() == "album":
            value += 4
        return value, release_year(release)

    return sorted((release for release in releases if isinstance(release, dict)), key=score, reverse=True)[0]


def normalize_musicbrainz_payload(payload: Any, fallback: AlbumSearch) -> AlbumSearch:
    recordings = payload.get("recordings", []) if isinstance(payload, dict) else []
    if not recordings:
        return fallback
    recording = recordings[0]
    if not isinstance(recording, dict):
        return fallback
    release = best_musicbrainz_release(recording, fallback)
    title = first_value(recording.get("title")) or fallback.title
    artist = artist_credit_name(recording, fallback.artist)
    album = first_value(release.get("title")) or fallback.album
    year_album = release_year(release) or fallback.year_album
    return AlbumSearch(title=title, artist=artist, album=album, year_album=year_album, term=fallback.term)


def musicbrainz_album_info(search: AlbumSearch) -> AlbumSearch:
    params = {
        "query": musicbrainz_query(search),
        "fmt": "json",
        "limit": "5",
    }
    url = f"{MUSICBRAINZ_API_BASE}/recording?{urllib.parse.urlencode(params)}"
    payload = request_json(url)
    return normalize_musicbrainz_payload(payload, search)


def enrich_with_musicbrainz(search: AlbumSearch) -> AlbumSearch:
    try:
        return musicbrainz_album_info(search)
    except Exception as exc:
        print(f"No se pudo usar MusicBrainz; sigo con tus datos: {exc}", file=sys.stderr)
        return search


def load_internetarchive() -> Any:
    try:
        import internetarchive
    except ImportError:
        print(
            "Falta la dependencia 'internetarchive'. Instala con:\n"
            "  python -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    return internetarchive


def search_albums(client: Any, term: str, collection: str | None, limit: int) -> list[dict]:
    query = build_query(term, collection)
    return search_archive(client, query, limit)


def search_album_metadata(client: Any, search: AlbumSearch, collection: str | None, limit: int) -> list[dict]:
    for query in metadata_query_variants(search, collection):
        results = search_archive(client, query, limit)
        if results:
            return results
    return []


def search_archive(client: Any, query: str, limit: int) -> list[dict]:
    fields = ["identifier", "title", "creator", "date", "downloads", "description"]
    try:
        results = client.search_items(query, fields=fields, sorts=["downloads desc"])
        return list(results)[:limit]
    except Exception as exc:
        if is_network_lookup_error(exc):
            raise NetworkLookupError("No se pudo resolver archive.org. Revisa DNS/conexion.") from exc
        raise


def print_results(results: Iterable[dict]) -> None:
    for index, result in enumerate(results, start=1):
        identifier = first_value(result.get("identifier"))
        title = first_value(result.get("title"), identifier)
        creator = first_value(result.get("creator"), "Desconocido")
        date = first_value(result.get("date"), "s/f")
        downloads = first_value(result.get("downloads"), "0")
        print(f"{index:>2}. {title}")
        print(f"    Artista: {creator} | Fecha: {date} | Descargas: {downloads}")
        print(f"    ID: {identifier}")
        print(f"    URL: https://archive.org/details/{identifier}")


def torrent_url(identifier: str) -> str:
    quoted_identifier = urllib.parse.quote(identifier, safe="")
    quoted_file = urllib.parse.quote(f"{identifier}_archive.torrent", safe="")
    return f"https://archive.org/download/{quoted_identifier}/{quoted_file}"


def fetch_torrent(identifier: str) -> bytes:
    url = torrent_url(identifier)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            torrent = response.read()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            raise NetworkLookupError(f"No se pudo resolver archive.org para {identifier}.") from exc
        raise
    if not torrent.startswith(b"d"):
        raise ValueError(f"Archive.org no devolvio un torrent valido para {identifier}.")
    return torrent


def save_torrent(identifier: str, torrent: bytes, output_dir: Path) -> Path:
    """Save the original Archive.org torrent without converting its contents."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{clean_name(identifier)}_archive.torrent"
    path.write_bytes(torrent)
    return path


def download_torrent(identifier: str, output_dir: Path | None = None) -> Path:
    """Download an item's Archive.org-generated torrent file."""
    destination = output_dir if output_dir is not None else Path("torrents")
    return save_torrent(identifier, fetch_torrent(identifier), destination)


def archive_download_url(identifier: str, filename: str) -> str:
    return (
        "https://archive.org/download/"
        f"{urllib.parse.quote(identifier)}/"
        f"{urllib.parse.quote(filename)}"
    )


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            raise NetworkLookupError(f"No se pudo resolver el host de {url}.") from exc
        raise


def item_files_xml(identifier: str) -> str:
    return fetch_text(archive_download_url(identifier, f"{identifier}_files.xml"))


def item_meta_xml(identifier: str) -> str:
    return fetch_text(archive_download_url(identifier, f"{identifier}_meta.xml"))


def normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_files_xml_tracks(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    tracks: list[str] = []
    audio_extensions = {".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac", ".opus"}
    for file_node in root.findall("file"):
        name = file_node.attrib.get("name", "")
        title = first_value(file_node.findtext("title"))
        original = first_value(file_node.findtext("original"))
        display = title or original or Path(name).stem
        suffix = Path(name).suffix.lower()
        file_format = first_value(file_node.findtext("format")).lower()
        if suffix in audio_extensions or any(token in file_format for token in ["mp3", "flac", "ogg", "wave", "audio"]):
            tracks.append(display)
    return list(dict.fromkeys(track for track in tracks if track))


def parse_meta_xml_subjects(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    subjects = [first_value(node.text) for node in root.findall("subject")]
    return list(dict.fromkeys(subject for subject in subjects if subject))


def track_match_score(tracks: list[str], search: AlbumSearch) -> tuple[int, list[str]]:
    wanted = [search.title, search.album]
    normalized_terms = [normalize_text(term) for term in wanted if normalize_text(term)]
    matches: list[str] = []
    for track in tracks:
        normalized_track = normalize_text(track)
        if any(term in normalized_track or normalized_track in term for term in normalized_terms):
            matches.append(track)
    return len(matches), matches[:5]


def summarize_archive_results(results: list[dict], search: AlbumSearch) -> list[ArchiveResult]:
    summaries: list[ArchiveResult] = []
    for index, result in enumerate(results, start=1):
        identifier = first_value(result.get("identifier"))
        title = first_value(result.get("title"), identifier)
        creator = first_value(result.get("creator"), "Desconocido")
        date = first_value(result.get("date"), "s/f")
        tracks: list[str] = []
        try:
            tracks = parse_files_xml_tracks(item_files_xml(identifier))
        except Exception:
            tracks = []
        try:
            subjects = parse_meta_xml_subjects(item_meta_xml(identifier))
        except Exception:
            subjects = []
        tracks = list(dict.fromkeys([*tracks, *subjects]))
        score, track_matches = track_match_score(tracks, search)
        summaries.append(
            ArchiveResult(
                index=index,
                identifier=identifier,
                title=title,
                creator=creator,
                date=date,
                track_matches=track_matches,
                match_score=score,
            )
        )
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Busca albumes musicales en archive.org y descarga sus archivos torrent."
    )
    parser.add_argument("busqueda", nargs="?", default="", help="Nombre del album, artista o palabras clave.")
    parser.add_argument("--title", default="", help="Titulo de una cancion del album.")
    parser.add_argument("--artist", default="", help="Artista.")
    parser.add_argument("--album", default="", help="Nombre del album.")
    parser.add_argument("--year-album", default="", help="Anio del album.")
    parser.add_argument(
        "--musicbrainz",
        action="store_true",
        help="Usa MusicBrainz para obtener title/artist/album/year_album antes de buscar en archive.org.",
    )
    parser.add_argument(
        "--bhariya",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("-n", "--limit", type=int, default=10, help="Cantidad de resultados. Default: 10.")
    parser.add_argument(
        "-c",
        "--collection",
        default="opensource_audio",
        help='Colección de archive.org. Usa "" para no filtrar. Default: opensource_audio.',
    )
    parser.add_argument(
        "-t",
        "--torrent",
        "-m",
        "--magnet",
        dest="torrent",
        type=int,
        metavar="NUM",
        help="Descarga el .torrent del resultado indicado por numero (--magnet se conserva como alias).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Carpeta donde guardar el .torrent. Default: torrents.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = load_internetarchive()
    collection = args.collection or None
    search = AlbumSearch(
        title=args.title,
        artist=args.artist,
        album=args.album,
        year_album=args.year_album,
        term=args.busqueda,
    )
    if args.musicbrainz or args.bhariya:
        search = enrich_with_musicbrainz(search)
        print("Metadata MusicBrainz:")
        print(json.dumps(search.minimum_info(), ensure_ascii=False, indent=2))
    try:
        results = search_album_metadata(client, search, collection, args.limit)
    except NetworkLookupError as exc:
        print(exc, file=sys.stderr)
        return 3
    if not results:
        print("No encontré resultados.")
        return 1

    print_results(results)
    if args.torrent is not None:
        if args.torrent < 1 or args.torrent > len(results):
            print(f"El numero de resultado debe estar entre 1 y {len(results)}.", file=sys.stderr)
            return 2
        result = results[args.torrent - 1]
        identifier = first_value(result.get("identifier"))
        output_dir = Path(args.output) if args.output else None
        try:
            path = download_torrent(identifier, output_dir)
        except NetworkLookupError as exc:
            print(exc, file=sys.stderr)
            return 3
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"No se pudo descargar el torrent: {exc}", file=sys.stderr)
            return 4
        print(f"Torrent descargado en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
