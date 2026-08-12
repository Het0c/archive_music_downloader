#!/usr/bin/env python3
"""Small terminal interface for the archive.org album searcher."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from archive_album_search import (
    AlbumSearch,
    ArchiveResult,
    download_torrent,
    first_value,
    load_internetarchive,
    musicbrainz_album_info,
    search_album_metadata,
    summarize_archive_results,
)


COLLECTIONS = {
    "1": ("opensource_audio", "Open Source Audio"),
    "2": ("etree", "Live Music Archive"),
    "3": ("78rpm", "78 RPMs and Cylinder Recordings"),
    "4": ("audio_music", "Music, Arts & Culture"),
    "5": ("", "Todo archive.org/audio"),
}


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_int(prompt: str, default: int, minimum: int = 1, maximum: int = 50) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("Escribe un numero valido.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Usa un numero entre {minimum} y {maximum}.")


def choose_collection() -> str | None:
    print("\nColeccion:")
    for key, (_, label) in COLLECTIONS.items():
        print(f"  {key}. {label}")
    choice = ask("Selecciona", "1")
    collection, _ = COLLECTIONS.get(choice, COLLECTIONS["1"])
    return collection or None


def print_header() -> None:
    print("=" * 62)
    print("Archive Music Downloader")
    print("=" * 62)


def ask_album_search() -> AlbumSearch | None:
    print("\nDatos de busqueda. Puedes llenar solo cancion y/o artista.")
    title = ask("Cancion")
    artist = ask("Artista")
    album = ask("Album")
    year_album = ask("Anio del album")
    term = ask("Busqueda libre")

    search = AlbumSearch(title=title, artist=artist, album=album, year_album=year_album, term=term)
    if not search.display_name():
        print("Agrega al menos un dato para buscar.")
        return None
    return search


def maybe_enrich_search(search: AlbumSearch) -> AlbumSearch:
    use_api = ask("Usar MusicBrainz para completar album/anio", "s")
    if use_api.lower() not in {"s", "si", "y", "yes"}:
        return search
    try:
        enriched = musicbrainz_album_info(search)
    except Exception as exc:
        print(f"No se pudo usar MusicBrainz; sigo con tus datos: {exc}")
        return search

    print("\nMetadata encontrada:")
    print(f"  title: {enriched.title or '-'}")
    print(f"  artist: {enriched.artist or '-'}")
    print(f"  album: {enriched.album or '-'}")
    print(f"  year_album: {enriched.year_album or '-'}")
    return enriched


def edit_filters(search: AlbumSearch) -> AlbumSearch:
    print("\nFiltros antes de archive.org")
    print("Deja el valor actual con Enter o borralo escribiendo -")
    artist = ask("Creador/artista", search.artist)
    year_album = ask("Anio lanzamiento", search.year_album)
    if artist == "-":
        artist = ""
    if year_album == "-":
        year_album = ""
    return AlbumSearch(
        title=search.title,
        artist=artist,
        album=search.album,
        year_album=year_album,
        term=search.term,
    )


def cut(value: str, width: int) -> str:
    if len(value) <= width:
        return value.ljust(width)
    return value[: width - 1] + "…"


def print_table(rows: list[ArchiveResult]) -> None:
    print("\nResultados archive.org")
    print("-" * 112)
    print(
        f"{'#':>2}  "
        f"{'Album/item':<32}  "
        f"{'Creador':<20}  "
        f"{'Fecha':<10}  "
        f"{'Pistas':>6}  "
        f"{'Concordancia'}"
    )
    print("-" * 112)
    for row in rows:
        matches = ", ".join(row.track_matches) if row.track_matches else "-"
        print(
            f"{row.index:>2}  "
            f"{cut(row.title, 32)}  "
            f"{cut(row.creator, 20)}  "
            f"{cut(row.date[:10], 10)}  "
            f"{row.match_score:>6}  "
            f"{cut(matches, 30)}"
        )
    print("-" * 112)


def choose_result(rows: list[ArchiveResult]) -> ArchiveResult | None:
    while True:
        raw = ask("\nNumero de album, b para nueva busqueda, q para salir")
        if raw.lower() == "q":
            raise KeyboardInterrupt
        if raw.lower() == "b":
            return None
        try:
            index = int(raw)
        except ValueError:
            print("Seleccion no valida.")
            continue
        if 1 <= index <= len(rows):
            return rows[index - 1]
        print(f"Elige un numero entre 1 y {len(rows)}.")


def result_menu(result: ArchiveResult) -> None:
    identifier = result.identifier
    title = result.title
    url = f"https://archive.org/details/{identifier}"

    while True:
        print(f"\nSeleccionado: {title}")
        print(f"Creador: {result.creator} | Fecha: {result.date}")
        if result.track_matches:
            print("Pistas coincidentes:")
            for track in result.track_matches:
                print(f"  - {track}")
        print(f"URL: {url}")
        print("  1. Descargar archivo .torrent")
        print("  2. Abrir en navegador")
        print("  3. Volver a resultados")
        action = ask("Accion", "1")

        if action == "1":
            try:
                path = download_torrent(identifier, Path("torrents"))
            except Exception as exc:
                print(f"No se pudo descargar el torrent: {exc}")
            else:
                print(f"\nTorrent descargado en {path}")
        elif action == "2":
            webbrowser.open(url)
        elif action == "3":
            return
        else:
            print("Accion no valida.")


def run() -> int:
    print_header()
    client = load_internetarchive()

    while True:
        action = ask("\nEnter para buscar, q para salir")
        if action.lower() == "q":
            return 0
        search = ask_album_search()
        if search is None:
            continue
        search = maybe_enrich_search(search)
        search = edit_filters(search)

        collection = choose_collection()
        limit = ask_int("Cantidad de resultados", 10)
        print(f"\nBuscando: {search.display_name()}...")

        try:
            results = search_album_metadata(client, search, collection, limit)
        except Exception as exc:
            print(f"No se pudo buscar: {exc}")
            continue

        if not results:
            print("No encontre resultados.")
            continue

        print("Leyendo *_files.xml para calcular concordancias de pistas...")
        rows = summarize_archive_results(results, search)

        while True:
            print_table(rows)
            try:
                selected = choose_result(rows)
            except KeyboardInterrupt:
                return 0
            if selected is None:
                break
            result_menu(selected)


if __name__ == "__main__":
    raise SystemExit(run())
