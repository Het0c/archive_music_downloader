#!/usr/bin/env python3
"""PyQt interface for precise archive.org album searches."""

from __future__ import annotations

import sys
import traceback
import webbrowser
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from archive_album_search import (
    AlbumSearch,
    ArchiveResult,
    NetworkLookupError,
    collect_magnet,
    load_internetarchive,
    musicbrainz_album_info,
    search_album_metadata,
    summarize_archive_results,
)


COLLECTIONS = [
    ("opensource_audio", "Open Source Audio"),
    ("etree", "Live Music Archive"),
    ("78rpm", "78 RPMs and Cylinder Recordings"),
    ("audio_music", "Music, Arts & Culture"),
    ("", "Todo archive.org/audio"),
]


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.fn())
        except Exception:
            self.signals.failed.emit(traceback.format_exc())


class ArchiveAlbumWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.client = load_internetarchive()
        self.thread_pool = QThreadPool.globalInstance()
        self.current_search = AlbumSearch()
        self.rows: list[ArchiveResult] = []

        self.setWindowTitle("Archive Music Magnet Finder")
        self.resize(1180, 760)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Archive Music Magnet Finder")
        title.setObjectName("Title")
        root.addWidget(title)

        panels = QHBoxLayout()
        panels.addWidget(self.build_search_panel(), 2)
        panels.addWidget(self.build_metadata_panel(), 1)
        root.addLayout(panels)

        root.addWidget(self.build_result_table(), 1)
        root.addWidget(self.build_detail_panel())
        root.addWidget(self.build_status_bar())

        self.setCentralWidget(central)
        self.apply_styles()
        self.set_status("Listo.")

    def build_search_panel(self) -> QGroupBox:
        group = QGroupBox("Busqueda")
        layout = QGridLayout(group)

        self.title_input = QLineEdit()
        self.artist_input = QLineEdit()
        self.album_input = QLineEdit()
        self.year_input = QLineEdit()
        self.term_input = QLineEdit()
        self.creator_filter_input = QLineEdit()
        self.year_filter_input = QLineEdit()
        self.use_musicbrainz = QCheckBox("Completar ambiguedades con MusicBrainz")
        self.use_musicbrainz.setChecked(True)

        self.collection_select = QComboBox()
        for value, label in COLLECTIONS:
            self.collection_select.addItem(label, value)

        self.limit_input = QSpinBox()
        self.limit_input.setRange(1, 50)
        self.limit_input.setValue(10)

        layout.addWidget(QLabel("Cancion"), 0, 0)
        layout.addWidget(self.title_input, 0, 1)
        layout.addWidget(QLabel("Artista"), 0, 2)
        layout.addWidget(self.artist_input, 0, 3)
        layout.addWidget(QLabel("Album"), 1, 0)
        layout.addWidget(self.album_input, 1, 1)
        layout.addWidget(QLabel("Anio album"), 1, 2)
        layout.addWidget(self.year_input, 1, 3)
        layout.addWidget(QLabel("Busqueda libre"), 2, 0)
        layout.addWidget(self.term_input, 2, 1, 1, 3)
        layout.addWidget(self.use_musicbrainz, 3, 0, 1, 4)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator, 4, 0, 1, 4)

        layout.addWidget(QLabel("Filtro creador"), 5, 0)
        layout.addWidget(self.creator_filter_input, 5, 1)
        layout.addWidget(QLabel("Filtro anio"), 5, 2)
        layout.addWidget(self.year_filter_input, 5, 3)
        layout.addWidget(QLabel("Coleccion"), 6, 0)
        layout.addWidget(self.collection_select, 6, 1)
        layout.addWidget(QLabel("Limite"), 6, 2)
        layout.addWidget(self.limit_input, 6, 3)

        actions = QHBoxLayout()
        self.enrich_button = QPushButton("Resolver metadata")
        self.search_button = QPushButton("Buscar en archive.org")
        self.clear_button = QPushButton("Limpiar")
        self.enrich_button.clicked.connect(self.enrich_metadata)
        self.search_button.clicked.connect(self.search_archive)
        self.clear_button.clicked.connect(self.clear_form)
        actions.addWidget(self.enrich_button)
        actions.addWidget(self.search_button)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions, 7, 0, 1, 4)

        return group

    def build_metadata_panel(self) -> QGroupBox:
        group = QGroupBox("Metadata antes de buscar")
        layout = QFormLayout(group)
        self.meta_title = QLabel("-")
        self.meta_artist = QLabel("-")
        self.meta_album = QLabel("-")
        self.meta_year = QLabel("-")
        for label in [self.meta_title, self.meta_artist, self.meta_album, self.meta_year]:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addRow("title", self.meta_title)
        layout.addRow("artist", self.meta_artist)
        layout.addRow("album", self.meta_album)
        layout.addRow("year_album", self.meta_year)
        return group

    def build_result_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Album/item", "Creador", "Fecha", "Pistas", "Concordancias", "Identificador"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.update_detail)
        return self.table

    def build_detail_panel(self) -> QGroupBox:
        group = QGroupBox("Seleccion")
        layout = QVBoxLayout(group)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(110)
        actions = QHBoxLayout()
        self.show_magnet_button = QPushButton("Mostrar magnet")
        self.save_magnet_button = QPushButton("Guardar magnet")
        self.open_button = QPushButton("Abrir archive.org")
        self.copy_button = QPushButton("Copiar magnet")
        self.show_magnet_button.clicked.connect(self.show_magnet)
        self.save_magnet_button.clicked.connect(self.save_magnet)
        self.open_button.clicked.connect(self.open_selected)
        self.copy_button.clicked.connect(self.copy_magnet)
        actions.addWidget(self.show_magnet_button)
        actions.addWidget(self.save_magnet_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.open_button)
        layout.addWidget(self.detail)
        layout.addLayout(actions)
        return group

    def build_status_bar(self) -> QLabel:
        self.status = QLabel()
        self.status.setObjectName("Status")
        return self.status

    def apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #17202a;
                font-size: 13px;
            }
            QMainWindow {
                background: #f6f7f9;
            }
            #Title {
                font-size: 20px;
                font-weight: 700;
            }
            QGroupBox {
                color: #17202a;
                border: 1px solid #d5d9e0;
                border-radius: 6px;
                margin-top: 8px;
                padding: 10px;
                background: #ffffff;
            }
            QGroupBox::title {
                color: #17202a;
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                background: #ffffff;
            }
            QLabel {
                color: #17202a;
                background: transparent;
            }
            QCheckBox {
                color: #17202a;
                background: transparent;
            }
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget {
                color: #17202a;
                border: 1px solid #c9ced6;
                border-radius: 4px;
                padding: 5px;
                background: #ffffff;
                selection-color: #ffffff;
                selection-background-color: #2563eb;
            }
            QLineEdit::placeholder {
                color: #6b7280;
            }
            QHeaderView::section {
                color: #17202a;
                background: #e9edf2;
                border: 1px solid #c9ced6;
                padding: 5px;
            }
            QTableWidget::item {
                color: #17202a;
                background: #ffffff;
            }
            QTableWidget::item:selected {
                color: #ffffff;
                background: #2563eb;
            }
            QComboBox QAbstractItemView {
                color: #17202a;
                background: #ffffff;
                selection-color: #ffffff;
                selection-background-color: #2563eb;
            }
            QPushButton {
                color: #17202a;
                border: 1px solid #9ba7b4;
                border-radius: 4px;
                padding: 7px 12px;
                background: #edf1f5;
            }
            QPushButton:hover {
                background: #e3eaf0;
            }
            QPushButton:disabled {
                color: #6b7280;
                background: #e5e7eb;
            }
            #Status {
                color: #384250;
                padding: 4px;
            }
            """
        )

    def form_search(self) -> AlbumSearch:
        return AlbumSearch(
            title=self.title_input.text().strip(),
            artist=self.artist_input.text().strip(),
            album=self.album_input.text().strip(),
            year_album=self.year_input.text().strip(),
            term=self.term_input.text().strip(),
        )

    def filtered_search(self) -> AlbumSearch:
        search = self.current_search if self.current_search.display_name() else self.form_search()
        creator = self.creator_filter_input.text().strip() or search.artist
        year = self.year_filter_input.text().strip() or search.year_album
        return AlbumSearch(
            title=search.title,
            artist=creator,
            album=search.album,
            year_album=year,
            term=search.term,
        )

    def set_metadata(self, search: AlbumSearch) -> None:
        self.current_search = search
        self.meta_title.setText(search.title or "-")
        self.meta_artist.setText(search.artist or "-")
        self.meta_album.setText(search.album or "-")
        self.meta_year.setText(search.year_album or "-")
        if search.artist and not self.creator_filter_input.text().strip():
            self.creator_filter_input.setText(search.artist)
        if search.year_album and not self.year_filter_input.text().strip():
            self.year_filter_input.setText(search.year_album)

    def set_busy(self, busy: bool) -> None:
        for button in [
            self.enrich_button,
            self.search_button,
            self.clear_button,
            self.show_magnet_button,
            self.save_magnet_button,
            self.copy_button,
            self.open_button,
        ]:
            button.setDisabled(busy)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def run_worker(self, message: str, fn: Callable[[], object], done: Callable[[object], None]) -> None:
        self.set_busy(True)
        self.set_status(message)
        worker = Worker(fn)
        worker.signals.finished.connect(lambda result: self.finish_worker(result, done))
        worker.signals.failed.connect(self.fail_worker)
        self.thread_pool.start(worker)

    def finish_worker(self, result: object, done: Callable[[object], None]) -> None:
        self.set_busy(False)
        done(result)

    def fail_worker(self, error: str) -> None:
        self.set_busy(False)
        message = self.readable_error(error)
        self.set_status(message)
        QMessageBox.warning(self, "Aviso", message)

    def readable_error(self, error: str) -> str:
        if "No address associated with hostname" in error or "Temporary failure in name resolution" in error:
            return "No se pudo resolver el servidor. Revisa tu conexion, DNS o intenta de nuevo."
        if "No se pudo resolver" in error or "Failed to resolve" in error or "NameResolutionError" in error:
            return "No se pudo resolver el servidor. Revisa tu conexion, DNS o intenta de nuevo."
        if "HTTP Error 403" in error:
            return "El servidor rechazo la consulta. Puedes continuar con metadata manual."
        if "CERTIFICATE_VERIFY_FAILED" in error:
            return "No se pudo validar el certificado del servidor."
        return error.splitlines()[-1] if error else "Error desconocido."

    def enrich_metadata(self) -> None:
        search = self.form_search()
        if not search.display_name():
            QMessageBox.information(self, "Aviso", "Ingresa cancion, artista, album o busqueda libre.")
            return
        if not self.use_musicbrainz.isChecked():
            self.set_metadata(search)
            self.set_status("Metadata tomada del formulario.")
            return

        def task() -> AlbumSearch:
            try:
                return musicbrainz_album_info(search)
            except (NetworkLookupError, OSError):
                return search

        def done(result: object) -> None:
            enriched = result if isinstance(result, AlbumSearch) else search
            self.set_metadata(enriched)
            if enriched == search:
                self.set_status("MusicBrainz no respondio. Revisa/ajusta metadata manual y busca.")
            else:
                self.set_status("Metadata resuelta. Revisa los filtros antes de buscar.")

        self.run_worker("Consultando MusicBrainz...", task, done)

    def search_archive(self) -> None:
        base = self.form_search()
        if self.use_musicbrainz.isChecked() and not self.current_search.display_name():
            self.set_status("Primero resuelve metadata o desactiva MusicBrainz.")
            QMessageBox.information(self, "Aviso", "Resuelve metadata antes de buscar en archive.org.")
            return
        if not base.display_name() and not self.current_search.display_name():
            QMessageBox.information(self, "Aviso", "Ingresa al menos un dato de busqueda.")
            return

        search = self.filtered_search()
        collection = self.collection_select.currentData()
        limit = self.limit_input.value()

        def task() -> list[ArchiveResult]:
            results = search_album_metadata(self.client, search, collection, limit)
            return summarize_archive_results(results, search)

        def done(result: object) -> None:
            self.rows = result if isinstance(result, list) else []
            self.populate_table()
            if self.rows:
                self.set_status(f"{len(self.rows)} resultado(s). Selecciona una fila para ver acciones.")
            else:
                self.set_status("Sin resultados.")
                QMessageBox.information(self, "Aviso", "No se encontraron resultados.")

        self.run_worker("Buscando en archive.org y leyendo XML...", task, done)

    def populate_table(self) -> None:
        self.table.setRowCount(0)
        for row_index, row in enumerate(self.rows):
            self.table.insertRow(row_index)
            values = [
                str(row.index),
                row.title,
                row.creator,
                row.date[:10],
                str(row.match_score),
                ", ".join(row.track_matches) if row.track_matches else "-",
                row.identifier,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row_index)
                self.table.setItem(row_index, column, item)
        self.table.resizeRowsToContents()

    def selected_result(self) -> ArchiveResult | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row_index = selected[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(row_index, int) and 0 <= row_index < len(self.rows):
            return self.rows[row_index]
        return None

    def update_detail(self) -> None:
        result = self.selected_result()
        if result is None:
            self.detail.clear()
            return
        matches = "\n".join(f"- {track}" for track in result.track_matches) or "-"
        self.detail.setPlainText(
            f"{result.title}\n"
            f"Creador: {result.creator} | Fecha: {result.date}\n"
            f"ID: {result.identifier}\n"
            f"Concordancias:\n{matches}"
        )

    def selected_or_warn(self) -> ArchiveResult | None:
        result = self.selected_result()
        if result is None:
            QMessageBox.information(self, "Aviso", "Selecciona un resultado de la tabla.")
        return result

    def show_magnet(self) -> None:
        result = self.selected_or_warn()
        if result is None:
            return

        def task() -> str:
            return collect_magnet(result.identifier, result.title)

        def done(value: object) -> None:
            magnet = str(value)
            self.detail.setPlainText(magnet)
            self.set_status("Magnet generado.")

        self.run_worker("Generando magnet...", task, done)

    def save_magnet(self) -> None:
        result = self.selected_or_warn()
        if result is None:
            return

        def task() -> str:
            return collect_magnet(result.identifier, result.title, Path("magnets"))

        def done(value: object) -> None:
            self.detail.setPlainText(str(value))
            self.set_status("Magnet guardado en la carpeta magnets.")

        self.run_worker("Guardando magnet...", task, done)

    def copy_magnet(self) -> None:
        text = self.detail.toPlainText().strip()
        if not text.startswith("magnet:?"):
            QMessageBox.information(self, "Aviso", "Primero genera o muestra un magnet.")
            return
        QGuiApplication.clipboard().setText(text)
        self.set_status("Magnet copiado al portapapeles.")

    def open_selected(self) -> None:
        result = self.selected_or_warn()
        if result is not None:
            webbrowser.open(f"https://archive.org/details/{result.identifier}")

    def clear_form(self) -> None:
        for field in [
            self.title_input,
            self.artist_input,
            self.album_input,
            self.year_input,
            self.term_input,
            self.creator_filter_input,
            self.year_filter_input,
        ]:
            field.clear()
        self.current_search = AlbumSearch()
        self.rows = []
        self.set_metadata(AlbumSearch())
        self.populate_table()
        self.detail.clear()
        self.set_status("Formulario limpio.")


def main() -> int:
    app = QApplication(sys.argv)
    window = ArchiveAlbumWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
