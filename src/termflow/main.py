"""TermFlow — focused, prompt-driven Windows workbench."""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from threading import Event
from time import monotonic

import httpx
from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.history import list_history, save_snapshot
from termflow.core.prompt_execution import (
    ensure_complete_finish,
    make_request,
    serialize_rows,
    snapshot_prompt,
    validate_v3_output,
)
from termflow.core.request_planner import estimate_tokens
from termflow.core.result_cache import ResultCache, cache_key
from termflow.storage.credentials import delete, get, store
from termflow.storage.paths import APPDATA, LOCAL, PROMPTS
from termflow.storage.settings import load_settings, save_settings
from termflow.updater.downloader import download
from termflow.updater.github_releases import latest_release
from termflow.updater.installer import launch_installer
from termflow.updater.version_check import is_newer
from termflow.version import __version__


def _validate_nonempty(raw: str) -> str:
    if not raw.strip():
        raise ValueError("Empty model response")
    return raw


class GenerateWorker(QObject):
    done = Signal(str, str, object)
    failed = Signal(str, object)

    def __init__(self, provider, request):
        super().__init__()
        self.provider, self.request = provider, request

    def run(self):
        try:
            result = self.provider.generate(self.request)
            self.done.emit(result, getattr(self.provider, "finish_reason", ""), getattr(self.provider, "normalized_usage", lambda: {})())
        except Exception as exc:
            self.failed.emit(str(exc), getattr(self.provider, "normalized_usage", lambda: {})())


class UpdateWorker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(latest_release())
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, asset, checksum_asset):
        super().__init__()
        self.asset, self.checksum_asset = asset, checksum_asset
        self.cancelled = Event()

    def run(self):
        try:
            expected = None
            if self.checksum_asset:
                url = self.checksum_asset["browser_download_url"]
                response = httpx.get(url, timeout=20, follow_redirects=True)
                response.raise_for_status()
                expected = response.text.strip().split()[0]
                if len(expected) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected):
                    raise ValueError("Invalid release checksum")
            path = Path(tempfile.gettempdir()) / "TermFlow" / "TermFlow-Setup-x64.exe"
            digest = download(self.asset["browser_download_url"], path, lambda a, b: self.progress.emit(a, b), expected, self.cancelled)
            self.done.emit(str(path) + "|" + digest)
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("ตั้งค่า TermFlow")
        self.resize(520, 400)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox()
        self.provider.addItems(["openai", "anthropic", "gemini", "compatible"])
        self.provider.setCurrentText(settings.provider)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("เว้นว่างเพื่อใช้ API key ที่บันทึกไว้")
        self.model = QLineEdit(settings.model)
        self.model.setPlaceholderText("Model ID")
        self.base = QLineEdit(settings.base_url)
        self.timeout = QLineEdit(str(settings.timeout))
        self.context = QLineEdit(str(settings.context_window))
        self.output = QLineEdit(str(getattr(settings, "max_output_tokens", 8192)))
        self.cache = QCheckBox("ใช้ผลเดิมเมื่อ Prompt, SOURCE และ Model ตรงกัน")
        self.cache.setChecked(settings.reuse_results)
        self.updates = QCheckBox("ตรวจอัปเดตเมื่อเปิดแอป")
        self.updates.setChecked(settings.check_updates_on_startup)
        for title, item in [
            ("Provider", self.provider), ("API Key", self.key), ("Model ID", self.model),
            ("Base URL", self.base), ("Timeout (วินาที)", self.timeout),
            ("Context window (tokens)", self.context), ("Max output tokens", self.output),
            ("", self.cache), ("", self.updates),
        ]:
            form.addRow(title, item)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save = QPushButton("บันทึก")
        save.clicked.connect(self.save)
        cancel = QPushButton("ยกเลิก")
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def save(self):
        try:
            s = self.settings
            s.provider = self.provider.currentText()
            s.model = self.model.text().strip()
            s.base_url = self.base.text().strip()
            s.timeout = int(self.timeout.text())
            s.context_window = int(self.context.text())
            s.max_output_tokens = int(self.output.text())
            s.reuse_results = self.cache.isChecked()
            s.check_updates_on_startup = self.updates.isChecked()
            # Force Pydantic constraints before writing credentials.
            s = type(s).model_validate(s.model_dump())
            if self.key.text().strip():
                store(s.provider, self.key.text().strip())
            save_settings(s)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Settings", str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TermFlow {__version__}")
        self.resize(1250, 840)
        self.settings = load_settings()
        self.prompt_path = ""
        self.source_path = ""
        self.raw = ""
        self.rows = []
        self.valid = False
        self.running = False
        self._thread = None
        self._provider = None
        self._update_thread = None
        self._download_thread = None
        self._prompt_snapshot = None
        self._run_source = ""
        self._run_mode = ""
        self._run_key = ""
        self._run_started = 0.0
        self._build_ui()
        self.builtin_prompt = PROMPTS / "search" / "vocab_extractor_v3.md"
        self._load_prompt(str(self.builtin_prompt))
        self._set_status("พร้อมทำงาน")
        if self.settings.check_updates_on_startup:
            self.check_updates(silent=True)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        head = QHBoxLayout()
        heading = QLabel("TermFlow")
        heading.setStyleSheet("font-size: 26px; font-weight: 700;")
        head.addWidget(heading)
        sub = QLabel("Prompt-driven terminology workspace")
        sub.setStyleSheet("color: #7e8793;")
        head.addWidget(sub)
        head.addStretch()
        self.settings_button = QPushButton("⚙ ตั้งค่า API")
        self.settings_button.clicked.connect(self.open_settings)
        self.updates_button = QPushButton("ตรวจอัปเดต")
        self.updates_button.clicked.connect(lambda: self.check_updates(silent=False))
        self.history_button = QPushButton("ประวัติ")
        self.history_button.clicked.connect(self.open_history)
        for b in (self.settings_button, self.history_button, self.updates_button):
            head.addWidget(b)
        layout.addLayout(head)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("การทำงาน"))
        self.mode = QComboBox()
        self.mode.addItem("หาศัพท์จาก SOURCE", "extract")
        self.mode.addItem("รันตามไฟล์ Prompt", "prompt")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt"))
        self.prompt_field = QLineEdit()
        self.prompt_field.setReadOnly(True)
        self.prompt_field.setPlaceholderText("เลือกไฟล์ .md หรือ .txt")
        prompt_row.addWidget(self.prompt_field, 1)
        choose_prompt = QPushButton("เลือก Prompt")
        choose_prompt.clicked.connect(self.open_prompt)
        self.view_prompt_button = QPushButton("ดู Prompt")
        self.view_prompt_button.clicked.connect(self.view_prompt)
        prompt_row.addWidget(choose_prompt)
        prompt_row.addWidget(self.view_prompt_button)
        layout.addLayout(prompt_row)

        self.prompt_info = QLabel("")
        self.prompt_info.setStyleSheet("color: #89929d; font-size: 11px;")
        layout.addWidget(self.prompt_info)
        splitter = QSplitter(Qt.Vertical)
        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_head = QHBoxLayout()
        source_head.addWidget(QLabel("ต้นฉบับ SOURCE"))
        source_head.addStretch()
        self.source_meta = QLabel("ยังไม่มีไฟล์")
        source_head.addWidget(self.source_meta)
        source_open = QPushButton("เปิดไฟล์นิยาย")
        source_open.clicked.connect(self.open_source)
        source_head.addWidget(source_open)
        clear_source = QPushButton("ล้าง")
        source_head.addWidget(clear_source)
        source_layout.addLayout(source_head)
        self.source_editor = QPlainTextEdit()
        clear_source.clicked.connect(self.source_editor.clear)
        self.source_editor.setPlaceholderText("เปิดไฟล์ .txt/.md หรือวางข้อความนิยายจีนที่นี่...")
        self.source_editor.textChanged.connect(self.invalidate_result)
        source_layout.addWidget(self.source_editor)
        splitter.addWidget(source_panel)

        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_head = QHBoxLayout()
        result_head.addWidget(QLabel("ผลลัพธ์"))
        result_head.addStretch()
        self.result_info = QLabel("ยังไม่มีผลลัพธ์")
        result_head.addWidget(self.result_info)
        result_layout.addLayout(result_head)
        self.result_tabs = QTabWidget()
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["CN", "TH", "SEX", "NOTE"])
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_tabs.addTab(self.result_table, "รายการศัพท์")
        self.raw_view = QPlainTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setPlaceholderText("ผลตอบกลับดิบของ AI จะอยู่ที่นี่")
        self.result_tabs.addTab(self.raw_view, "คำตอบจาก AI")
        result_layout.addWidget(self.result_tabs)
        actions = QHBoxLayout()
        copy = QPushButton("คัดลอกผล")
        copy.clicked.connect(self.copy_all)
        self.copy_selected_button = QPushButton("คัดลอกแถวที่เลือก")
        self.copy_selected_button.clicked.connect(self.copy_selected)
        save = QPushButton("บันทึกผล")
        save.clicked.connect(self.save_result)
        for b in (copy, self.copy_selected_button, save):
            actions.addWidget(b)
        actions.addStretch()
        result_layout.addLayout(actions)
        splitter.addWidget(result_panel)
        splitter.setSizes([310, 430])
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("พร้อมทำงาน")
        bottom.addWidget(self.status_label, 1)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.clicked.connect(self.cancel_run)
        self.cancel_button.setEnabled(False)
        self.run_button = QPushButton("▶ เริ่มทำงาน")
        self.run_button.setMinimumHeight(40)
        self.run_button.clicked.connect(self.run_prompt)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.run_button)
        layout.addLayout(bottom)
        self.setStyleSheet("""
            QMainWindow { background: palette(window); }
            QPushButton { padding: 7px 12px; }
            QPlainTextEdit { font-size: 13px; }
            QTableWidget { font-size: 13px; }
            QComboBox { padding: 6px; }
        """)

    def _set_status(self, message):
        self.status_label.setText(message)
        self.statusBar().showMessage(message)

    def _load_prompt(self, path):
        try:
            text = Path(path).read_bytes().decode("utf-8-sig")
            spec = snapshot_prompt(text)
            self.prompt_path = path
            self.prompt_field.setText(path)
            self.prompt_info.setText(f"Prompt: {spec.kind} · {len(text):,} อักษร · SHA-256: {spec.digest[:14]}…")
            self.invalidate_result()
        except Exception as exc:
            QMessageBox.warning(self, "เปิด Prompt ไม่สำเร็จ", str(exc))

    def open_prompt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "เลือกไฟล์ Prompt", str(Path(self.prompt_path).parent), "Prompt (*.md *.txt);;All files (*)"
        )
        if path:
            self._load_prompt(path)

    def view_prompt(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Prompt — อ่านอย่างเดียว")
        dialog.resize(900, 700)
        v = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        try:
            view.setPlainText(Path(self.prompt_path).read_bytes().decode("utf-8-sig"))
        except Exception as exc:
            QMessageBox.warning(self, "Prompt", str(exc))
            return
        v.addWidget(view)
        dialog.exec()

    def open_source(self):
        path, _ = QFileDialog.getOpenFileName(self, "เปิด SOURCE", "", "Novel text (*.txt *.md);;All files (*)")
        if not path:
            return
        try:
            data = Path(path).read_bytes().decode("utf-8-sig")
            self.source_path = path
            self.source_editor.setPlainText(data)
            self.source_meta.setText(f"{Path(path).name} · {len(data):,} อักษร")
        except Exception as exc:
            QMessageBox.warning(self, "เปิด SOURCE ไม่สำเร็จ", str(exc))

    def _mode_changed(self):
        raw_mode = self.mode.currentData() == "prompt"
        self.result_tabs.setCurrentIndex(1 if raw_mode else 0)
        self.invalidate_result()

    def invalidate_result(self):
        self.valid = False
        self.rows = []
        self.raw = ""
        if hasattr(self, "raw_view"):
            self.raw_view.clear()
            self.result_table.setRowCount(0)
            self.result_info.setText("ยังไม่มีผลลัพธ์")

    def open_settings(self):
        if self.running:
            return
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec():
            self.settings = load_settings()

    def run_prompt(self):
        if self.running:
            return
        try:
            prompt = snapshot_prompt(Path(self.prompt_path).read_bytes().decode("utf-8-sig"))
            source = self.source_editor.toPlainText()
            request = make_request(prompt, source)
            if not self.settings.model:
                raise ValueError("กรุณาตั้งค่า Model ID ก่อนเริ่มงาน")
            secret = get(self.settings.provider)
            if not secret:
                raise ValueError("กรุณาตั้งค่า API key ก่อนเริ่มงาน")
            input_tokens = estimate_tokens(prompt.text) + estimate_tokens(source) + 256
            reserve = self.settings.max_output_tokens
            if input_tokens + reserve > self.settings.context_window:
                raise ValueError(
                    f"Estimated input {input_tokens:,} tokens + output reserve {reserve:,} "
                    f"exceeds configured context window {self.settings.context_window:,}. "
                    "Reduce SOURCE or use a larger model context. The app will not silently split the prompt."
                )
            mode = self.mode.currentData()
            if mode == "extract" and prompt.kind != "source-only-v3":
                raise ValueError("โหมดหาศัพท์ต้องใช้ Prompt V3 SOURCE-ONLY ที่รองรับ; สำหรับ Prompt อื่นใช้โหมดรันตามไฟล์ Prompt")
            self._run_source = source
            self._prompt_snapshot = prompt
            self._run_mode = mode
            self._run_started = monotonic()
            self._run_key = cache_key(
                workflow="prompt-driven-" + mode, provider=self.settings.provider,
                base_url=self.settings.base_url, model=self.settings.model,
                prompt=prompt.text, source=source, validator_version="prompt-driven-v2-" + str(reserve),
            )
            if self.settings.reuse_results:
                validator = (
                    (lambda raw: validate_v3_output(raw, source))
                    if prompt.kind == "source-only-v3"
                    else _validate_nonempty
                )
                cached = ResultCache().get(self._run_key, validator)
                if cached is not None:
                    self.on_result(cached, "cache", {})
                    self._set_status("โหลดผลที่ตรวจผ่านจาก Cache")
                    return
            self._provider = create_provider(
                ProviderConfig(provider=self.settings.provider, model=self.settings.model,
                               base_url=self.settings.base_url, timeout=self.settings.timeout,
                               retries=self.settings.retries, max_output_tokens=reserve),
                secret,
            )
            self.running = True
            self.run_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self._set_status("กำลังส่ง Prompt และ SOURCE ไปยัง AI…")
            self._thread = QThread()
            self._worker = GenerateWorker(self._provider, request)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.done.connect(self.on_result)
            self._worker.failed.connect(self.on_error)
            self._worker.done.connect(self._thread.quit)
            self._worker.failed.connect(self._thread.quit)
            self._thread.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._thread.deleteLater)
            self._thread.start()
        except Exception as exc:
            QMessageBox.warning(self, "เริ่มงานไม่ได้", str(exc))

    def _finish_run(self):
        self.running = False
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def on_result(self, raw, finish_reason, usage):
        self._finish_run()
        self.raw = raw
        self.raw_view.setPlainText(raw)
        self.rows = []
        self.valid = False
        try:
            ensure_complete_finish(finish_reason)
            if self._prompt_snapshot.kind == "source-only-v3":
                self.rows = validate_v3_output(raw, self._run_source)
                self.result_table.setRowCount(len(self.rows))
                for index, row in enumerate(self.rows):
                    for column, value in enumerate(row):
                        self.result_table.setItem(index, column, QTableWidgetItem(value))
                self.result_tabs.setCurrentIndex(0 if self._run_mode == "extract" else 1)
                self.result_info.setText(f"ผ่านการตรวจรูปแบบ · {len(self.rows)} ศัพท์")
            else:
                if not raw.strip():
                    raise ValueError("AI returned empty output")
                self.result_table.setRowCount(0)
                self.result_tabs.setCurrentIndex(1)
                self.result_info.setText("คำตอบตามไฟล์ Prompt")
            self.valid = True
            self._set_status("เสร็จแล้ว · ส่งออกผลได้")
            if finish_reason != "cache" and self.settings.reuse_results:
                validator = (
                    (lambda text: validate_v3_output(text, self._run_source))
                    if self._prompt_snapshot.kind == "source-only-v3"
                    else _validate_nonempty
                )
                ResultCache().put(self._run_key, raw, validator)
        except Exception as exc:
            self.result_info.setText("ผลลัพธ์ไม่ผ่านการตรวจ")
            self.result_tabs.setCurrentIndex(1)
            self._set_status(f"ไม่ผ่านการตรวจ: {exc}")
            QMessageBox.warning(self, "ผลลัพธ์ยังไม่สมบูรณ์", str(exc))
        self._save_run(raw, finish_reason, usage)

    def _save_run(self, raw, finish_reason, usage):
        try:
            save_snapshot({
                "workflow": "prompt-driven",
                "mode": self._run_mode,
                "prompt_path": str(self.prompt_path),
                "exact_prompt_text": self._prompt_snapshot.text,
                "prompt_sha256": self._prompt_snapshot.digest,
                "source_filename": Path(self.source_path).name if self.source_path else "",
                "source_hash": hashlib.sha256(self._run_source.encode()).hexdigest(),
                "provider": self.settings.provider,
                "model": self.settings.model,
                "raw_response": raw,
                "parsed_result": self.rows if self._prompt_snapshot.kind == "source-only-v3" else raw,
                "validation_result": {"passed": self.valid, "finish_reason": finish_reason},
                "usage": usage, "duration_seconds": monotonic() - self._run_started,
            })
        except Exception as exc:
            self._set_status(f"บันทึก History ไม่สำเร็จ: {exc}")

    def on_error(self, message, usage):
        self._finish_run()
        self.valid = False
        self._set_status(f"คำขอไม่สำเร็จ: {message}")
        QMessageBox.warning(self, "AI Request Failed", message)

    def cancel_run(self):
        if self._provider:
            self._provider.cancel()
            self._set_status("กำลังยกเลิกคำขอ…")

    def _export_text(self):
        if not self.valid:
            raise ValueError("ยังไม่มีผลลัพธ์ที่สมบูรณ์")
        if self._prompt_snapshot.kind == "source-only-v3" and self._run_mode == "extract":
            return serialize_rows(self.rows)
        return self.raw

    def copy_all(self):
        try:
            QApplication.clipboard().setText(self._export_text())
            self._set_status("คัดลอกผลลัพธ์แล้ว")
        except ValueError as exc:
            QMessageBox.information(self, "Copy", str(exc))

    def copy_selected(self):
        if not self.valid or self._prompt_snapshot.kind != "source-only-v3":
            QMessageBox.information(self, "Copy", "ใช้กับผลศัพท์ V3 ที่ตรวจผ่านเท่านั้น")
            return
        selected = sorted({item.row() for item in self.result_table.selectedItems()})
        QApplication.clipboard().setText(serialize_rows([self.rows[index] for index in selected]))
        self._set_status(f"คัดลอก {len(selected)} แถวแล้ว")

    def save_result(self):
        try:
            value = self._export_text()
        except ValueError as exc:
            QMessageBox.information(self, "Save", str(exc))
            return
        extension = "tsv" if self._prompt_snapshot.kind == "source-only-v3" and self._run_mode == "extract" else "md"
        filename = "TermFlow-result." + extension
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกผล", filename, "Text files (*.txt *.md *.tsv);;All files (*)")
        if not path:
            return
        target = Path(path).resolve()
        protected = {Path(p).resolve() for p in (self.source_path, self.prompt_path) if p}
        if target in protected:
            QMessageBox.warning(self, "Save", "ไม่อนุญาตให้บันทึกทับ SOURCE หรือ Prompt")
            return
        temp = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=target.parent, delete=False) as stream:
                stream.write(value)
                temp = Path(stream.name)
            os.replace(temp, target)
            self._set_status(f"บันทึก: {target}")
        except Exception as exc:
            if temp:
                temp.unlink(missing_ok=True)
            QMessageBox.warning(self, "บันทึกไม่สำเร็จ", str(exc))

    def open_history(self):
        entries = list_history()
        if not entries:
            QMessageBox.information(self, "History", "ยังไม่มีประวัติ")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ประวัติคำขอ (อ่านอย่างเดียว)")
        dialog.resize(1000, 680)
        v = QVBoxLayout(dialog)
        chooser = QComboBox()
        for record in entries[:100]:
            label = (
                f"{record.get('timestamp', '')} · "
                f"{record.get('mode', record.get('workflow', 'legacy'))} · {record.get('model', '')}"
            )
            chooser.addItem(label, record)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        def display(index):
            record = chooser.itemData(index) or {}
            view.setPlainText(record.get("raw_response", "") or str(record.get("parsed_result", "")))
        chooser.currentIndexChanged.connect(display)
        v.addWidget(chooser)
        v.addWidget(view)
        display(0)
        dialog.exec()

    def check_updates(self, silent=False):
        if self._update_thread and self._update_thread.isRunning():
            return
        self._silent_update = silent
        self._update_thread = QThread()
        worker = UpdateWorker()
        self._update_worker = worker
        worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(worker.run)
        worker.done.connect(self.on_update_check)
        worker.failed.connect(self.on_update_failure)
        worker.done.connect(self._update_thread.quit)
        worker.failed.connect(self._update_thread.quit)
        self._update_thread.finished.connect(worker.deleteLater)
        self._update_thread.start()

    def on_update_failure(self, message):
        if not self._silent_update:
            QMessageBox.warning(self, "ตรวจอัปเดต", message)

    def on_update_check(self, release):
        tag = release.get("tag_name", "")
        if not is_newer(tag):
            if not self._silent_update:
                QMessageBox.information(self, "Update", "TermFlow เป็นเวอร์ชันล่าสุดแล้ว")
            return
        answer = QMessageBox.question(self, "อัปเดตใหม่", f"มี TermFlow {tag} (ติดตั้ง {__version__})\nดาวน์โหลดและติดตั้งหรือไม่?")
        if answer != QMessageBox.Yes:
            return
        assets = release.get("assets", [])
        installer = next((a for a in assets if a.get("name") == "TermFlow-Setup-x64.exe"), None)
        checksum = next((a for a in assets if a.get("name") == "TermFlow-Setup-x64.exe.sha256"), None)
        if installer is None:
            QMessageBox.warning(self, "Update", "Release นี้ยังไม่มี Windows installer")
            QDesktopServices.openUrl(QUrl(release.get("html_url", "")))
            return
        self._download_thread = QThread()
        worker = DownloadWorker(installer, checksum)
        self._download_worker = worker
        worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(worker.run)
        worker.done.connect(self.on_download_done)
        worker.failed.connect(self.on_download_failed)
        worker.done.connect(self._download_thread.quit)
        worker.failed.connect(self._download_thread.quit)
        self._download_thread.finished.connect(worker.deleteLater)
        self._download_thread.start()
        self._set_status("กำลังดาวน์โหลดอัปเดต…")

    def on_download_failed(self, error):
        QMessageBox.warning(self, "Download", error)
        self._set_status("อัปเดตไม่สำเร็จ")

    def on_download_done(self, data):
        path, digest = data.split("|", 1)
        question = f"ดาวน์โหลดและตรวจ SHA-256 แล้ว\n{digest}\n\nปิด TermFlow แล้วเปิดตัวติดตั้งหรือไม่?"
        if QMessageBox.question(self, "ติดตั้งอัปเดต", question) == QMessageBox.Yes:
            try:
                launch_installer(Path(path))
                QApplication.quit()
            except Exception as exc:
                QMessageBox.warning(self, "Update", str(exc))

    def closeEvent(self, event):
        if self.running:
            self.cancel_run()
            QMessageBox.information(self, "งานกำลังทำงาน", "กำลังยกเลิกคำขอ กรุณาปิดอีกครั้งหลังหยุดทำงาน")
            event.ignore()
        else:
            event.accept()


def main():
    if "--smoke-ui" in sys.argv:
        # Exercise the actual GUI startup, not only the bundled prompt parser.
        # Never contact the network or open dialogs during the packaging smoke.
        app = QApplication(sys.argv)
        app.setApplicationName("TermFlow")
        from unittest.mock import patch

        with patch("termflow.main.MainWindow.check_updates"):
            window = MainWindow()
        assert window.source_editor is not None
        assert window.result_table is not None
        window.source_editor.setPlainText("林雪")
        window.source_editor.clear()
        window.mode.setCurrentIndex(1)
        window.mode.setCurrentIndex(0)
        window.close()
        app.quit()
        return
    if "--check-prompts" in sys.argv:
        prompt = PROMPTS / "search" / "vocab_extractor_v3.md"
        try:
            p = snapshot_prompt(prompt.read_bytes().decode("utf-8-sig"))
            sys.exit(0 if p.kind == "source-only-v3" else 1)
        except Exception:
            sys.exit(1)
    if "--remove-user-data" in sys.argv:
        for provider in ("openai", "anthropic", "gemini", "compatible"):
            delete(provider)
        shutil.rmtree(APPDATA, ignore_errors=True)
        shutil.rmtree(LOCAL, ignore_errors=True)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("TermFlow")
    app.setFont(QFont("Segoe UI", 12))
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
