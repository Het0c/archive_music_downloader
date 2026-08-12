# Archive Music Downloader

Script para buscar albumes musicales en archive.org y recopilar enlaces `magnet` de sus torrents.

## Instalación

Para usar el comando oficial `ia`, la documentación de Internet Archive recomienda instalarlo con `pipx`:

```bash
pipx install internetarchive
ia --version
```

Para ejecutar este script en Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

Buscar álbumes:

```bash
python archive_album_search.py "pink floyd"
```

Buscar más resultados:

```bash
python archive_album_search.py "jazz live" --limit 20
```

Buscar con datos minimos del album:

```bash
python archive_album_search.py \
  --title "MOONLIGHT ON THE RIVER" \
  --artist "MAC DEMARCO" \
  --album "This Old Dog" \
  --year-album "2017"
```

Buscar el album usando solo cancion y artista:

```bash
python archive_album_search.py --title "MOONLIGHT ON THE RIVER" --artist "MAC DEMARCO"
```

Usar MusicBrainz para completar datos desde una cancion y/o artista antes de buscar en archive.org:

```bash
python archive_album_search.py --title "MOONLIGHT ON THE RIVER" --artist "MAC DEMARCO" --musicbrainz
```

Generar el magnet torrent del resultado numero 3:

```bash
python archive_album_search.py "jazz live" --magnet 3
```

Generar el magnet buscando por cancion/artista:

```bash
python archive_album_search.py --title "MOONLIGHT ON THE RIVER" --artist "MAC DEMARCO" --magnet 1
```

Guardar el magnet en un archivo `.txt`:

```bash
python archive_album_search.py "jazz live" --magnet 3 --output magnets
```

Buscar desde cancion/artista, completar metadata con MusicBrainz y guardar el magnet del primer resultado:

```bash
python archive_album_search.py --title "MOONLIGHT ON THE RIVER" --artist "MAC DEMARCO" --musicbrainz --magnet 1 --output magnets
```

Por defecto se filtra por la colección `opensource_audio`. Para buscar en todo el contenido de audio:

```bash
python archive_album_search.py "nombre del album" --collection ""
```

## Interfaz por terminal

Tambien puedes usar una interfaz interactiva minimalista con selector, filtros y tabla:

```bash
python archive_album_tui.py
```

Flujo de la interfaz:

1. Escribes cancion, artista, album, anio o busqueda libre.
2. La interfaz intenta completar ambiguedades con MusicBrainz y muestra la metadata antes de buscar.
3. Puedes ajustar filtros opcionales de creador/artista y anio de lanzamiento.
4. Busca en archive.org y lee `*_files.xml` y `*_meta.xml` de cada item para calcular concordancias de pistas.
5. Muestra los resultados en tabla y permite seleccionar un album para mostrar o guardar su magnet torrent.

## Interfaz grafica PyQt

La GUI ofrece el mismo flujo con vistas de tabla, avisos y acciones por seleccion:

```bash
python archive_album_gui.py
```

Primero resuelve metadata con MusicBrainz, muestra los campos `title`, `artist`, `album` y `year_album`, permite ajustar filtros de creador/anio, busca en archive.org y presenta la concordancia de pistas en una tabla.
