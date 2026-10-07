import hashlib
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic

import httpx
from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from termflow.ai.base import GenerateRequest
from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.history import list_history, save_snapshot
from termflow.core.local_repair import repair_formatting
from termflow.core.result_cache import ResultCache, cache_key
from termflow.core.logging_config import configure_logging
from termflow.core.prompts import list_prompts
from termflow.core.request_planner import estimate_tokens, plan_search
from termflow.core.search_batch import ChunkRun, ChunkStatus, SearchBatch, aggregate_batch, apply_conflict_choices
from termflow.core.search_chunks import SourceChunk, split_source
from termflow.core.search_coordinator import SearchCoordinator
from termflow.core.search_export import format_step_a_result
from termflow.core.state_machine import State
from termflow.core.workflow import Workflow
from termflow.validators.step_b_validator import validate_step_b
from termflow.storage.credentials import delete, get, store
from termflow.storage.paths import APPDATA, LOCAL
from termflow.storage.profiles import (
    FileSnapshot,
    create_profile,
    delete_profile,
    file_snapshot,
    load_profiles,
    save_profiles,
    set_active_profile,
    update_profile,
)
from termflow.storage.settings import load_settings, save_settings
from termflow.ui.copyable_table import CopyableTableWidget
from termflow.ui.prompt_manager import PromptManagerDialog
from termflow.ui.search_conflicts import ConflictResolutionDialog
from termflow.ui.search_progress import MultiSearchWorker, SearchProgressDialog
from termflow.updater.downloader import download
from termflow.updater.github_releases import latest_release
from termflow.updater.installer import launch_installer
from termflow.updater.version_check import is_newer
from termflow.version import __version__


class Worker(QObject):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, provider, request):
        super().__init__()
        self.provider, self.request = provider, request

    def run(self):
        try:
            self.done.emit(self.provider.generate(self.request))
        except Exception as e:
            self.failed.emit(str(e))


class UpdateWorker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(latest_release())
        except Exception as e:
            self.failed.emit(str(e))


class DownloadWorker(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, asset, checksum_asset):
        super().__init__()
        self.asset, self.checksum_asset = asset, checksum_asset
        self.cancelled = Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            checksum = None
            if self.checksum_asset:
                response = httpx.get(self.checksum_asset["browser_download_url"], timeout=20, follow_redirects=True)
                response.raise_for_status()
                checksum = response.text.strip().split()[0]
                if len(checksum) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in checksum):
                    raise ValueError("Checksum asset is malformed")
            destination = Path(tempfile.gettempdir()) / "TermFlow" / "TermFlow-Setup-x64.exe"
            digest = download(
                self.asset["browser_download_url"],
                destination,
                lambda done, total: self.progress.emit(done, total),
                checksum,
                self.cancelled,
            )
            self.done.emit(f"{destination}|{digest}")
        except InterruptedError:
            self.failed.emit("Download cancelled")
        except Exception as e:
            self.failed.emit(str(e))


class NovelProfileDialog(QDialog):
    def __init__(self, parent, active_profile_id):
        super().__init__(parent)
        self.setWindowTitle("โปรไฟล์นิยาย")
        self.setMinimumWidth(420)
        self.selected_profile_id = active_profile_id
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("เลือกโปรไฟล์เพื่อเปิดไฟล์และการตั้งค่าของแต่ละเรื่อง"))
        self.list = QListWidget()
        layout.addWidget(self.list)
        controls = QHBoxLayout()
        for label, callback in (
            ("โปรไฟล์ใหม่", self.create),
            ("เปลี่ยนชื่อ", self.rename),
            ("ลบ", self.delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.use_button = QPushButton("ใช้โปรไฟล์ที่เลือก")
        self.use_button.clicked.connect(self.accept)
        layout.addWidget(self.use_button)
        self.reload()

    def reload(self, select_id=None):
        collection = load_profiles()
        self.list.clear()
        for profile in collection.profiles:
            item = QListWidgetItem(profile.name)
            item.setData(Qt.UserRole, profile.id)
            self.list.addItem(item)
            if profile.id == (select_id or self.selected_profile_id):
                self.list.setCurrentItem(item)

    def current_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def create(self):
        name, accepted = QInputDialog.getText(self, "โปรไฟล์ใหม่", "ชื่อเรื่อง")
        if accepted and name.strip():
            profile = create_profile(name)
            self.selected_profile_id = profile.id
            self.reload(profile.id)

    def rename(self):
        profile_id = self.current_id()
        if not profile_id:
            return
        profile = next((item for item in load_profiles().profiles if item.id == profile_id), None)
        if profile:
            name, accepted = QInputDialog.getText(self, "เปลี่ยนชื่อโปรไฟล์", "ชื่อเรื่อง", text=profile.name)
            if accepted and name.strip():
                update_profile(profile_id, name=name)
                self.reload(profile_id)

    def delete(self):
        profile_id = self.current_id()
        collection = load_profiles()
        if not profile_id or len(collection.profiles) <= 1:
            return
        answer = QMessageBox.question(self, "ลบโปรไฟล์", "ลบโปรไฟล์นี้หรือไม่? ไฟล์ต้นฉบับจะไม่ถูกลบ")
        if answer == QMessageBox.Yes:
            delete_profile(profile_id)
            self.selected_profile_id = load_profiles().active_profile_id
            self.reload(self.selected_profile_id)

    def accept(self):
        self.selected_profile_id = self.current_id()
        if self.selected_profile_id:
            super().accept()


class SettingsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("TermFlow Settings")
        self.settings = settings
        form = QFormLayout(self)
        self.provider = QComboBox()
        self.provider.addItems(["openai", "anthropic", "gemini", "compatible"])
        self.provider.setCurrentText(settings.provider)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("API key (stored in Windows Credential Manager)")
        self.base = QLineEdit(settings.base_url)
        self.base.setPlaceholderText("ตัวอย่าง OpenAI-compatible: https://api.example.com/v1")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(settings.model)
        self.timeout = QLineEdit(f"{settings.timeout / 60:g}")
        self.retries = QLineEdit(str(settings.retries))
        self.search_model = QLineEdit(settings.search_model)
        self.polish_model = QLineEdit(settings.polish_model)
        self.reuse_results = QCheckBox("ใช้ผลเดิมเมื่อ SOURCE / VOCAB / Prompt / Model เหมือนเดิม")
        self.reuse_results.setChecked(settings.reuse_results)
        self.search_chunks = QComboBox()
        for count in range(1, 21):
            if count == 1:
                label = "1 ช่วง · เหมาะกับไม่เกิน 10,000 ตัวอักษร"
            else:
                lower = count * 5_000
                upper = count * 10_000
                label = f"{count} ช่วง · เหมาะกับประมาณ {lower:,}–{upper:,} ตัวอักษร"
            self.search_chunks.addItem(label, count)
            self.search_chunks.setItemData(
                self.search_chunks.count() - 1,
                f"แบ่ง SOURCE เป็น {count} คำขอ · โดยประมาณ {5_000:,}–{10_000:,} ตัวอักษรต่อช่วง",
                Qt.ToolTipRole,
            )
        selected = self.search_chunks.findData(settings.search_chunks)
        self.search_chunks.setCurrentIndex(selected if selected >= 0 else self.search_chunks.findData(3))
        self.theme = QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.setCurrentText(settings.theme)
        self.font_size = QComboBox()
        for size, label in ((12, "ปกติ · 12 pt"), (14, "ใหญ่ · 14 pt"), (16, "ใหญ่มาก · 16 pt")):
            self.font_size.addItem(label, size)
        selected_font_size = self.font_size.findData(settings.font_size)
        self.font_size.setCurrentIndex(selected_font_size if selected_font_size >= 0 else self.font_size.findData(12))
        self.startup = QCheckBox("Check for updates on startup")
        self.startup.setChecked(settings.check_updates_on_startup)
        self.remember = QPushButton("Save Settings")
        self.remember.clicked.connect(self.save)
        self.test = QPushButton("Test Connection")
        self.test.clicked.connect(self.test_connection)
        self.load_models = QPushButton("Load Models")
        self.load_models.clicked.connect(self.models)
        self.delete_key = QPushButton("Delete API Key")
        self.delete_key.clicked.connect(self.delete_api_key)
        self.updates = QPushButton("Check for Updates")
        self.updates.clicked.connect(parent.check_updates)
        form.addRow("Provider", self.provider)
        form.addRow("API Key", self.key)
        form.addRow("Base URL", self.base)
        form.addRow("Default Model", self.model)
        advanced = QGroupBox("Advanced")
        advanced_form = QFormLayout(advanced)
        advanced_form.addRow("AI response timeout (นาที)", self.timeout)
        advanced_form.addRow("Automatic retries", self.retries)
        advanced_form.addRow("Search model (ว่าง = Default)", self.search_model)
        advanced_form.addRow("Polish model (ว่าง = Default)", self.polish_model)
        advanced_form.addRow("SOURCE chunks (advanced)", self.search_chunks)
        advanced_form.addRow("", QLabel("การ retry อาจสร้างค่า API เพิ่ม · 1–20 chunks"))
        advanced_form.addRow("", self.reuse_results)
        form.addRow(advanced)
        form.addRow("Theme", self.theme)
        form.addRow("ขนาดตัวอักษร", self.font_size)
        form.addRow("", self.startup)
        row = QHBoxLayout()
        row.addWidget(self.test)
        row.addWidget(self.load_models)
        row.addWidget(self.delete_key)
        row.addWidget(self.updates)
        row.addWidget(self.remember)
        form.addRow(row)

    def save(self):
        try:
            timeout_minutes = float(self.timeout.text())
            retries = int(self.retries.text())
            if not 0.5 <= timeout_minutes <= 30:
                raise ValueError("AI response timeout ต้องอยู่ระหว่าง 0.5–30 นาที (30–1800 วินาที)")
            if not 0 <= retries <= 10:
                raise ValueError("Retries ต้องอยู่ระหว่าง 0–10")
        except ValueError as exc:
            QMessageBox.warning(self, "Settings ไม่ถูกต้อง", str(exc) or "กรอก timeout และ retries เป็นตัวเลขจำนวนเต็ม")
            return
        s = self.settings
        s.provider = self.provider.currentText()
        s.credential_name = s.provider
        s.base_url = self.base.text().strip()
        s.model = self.model.currentText().strip()
        s.timeout = round(timeout_minutes * 60)
        s.retries = retries
        s.search_chunks = int(self.search_chunks.currentData())
        s.search_model = self.search_model.text().strip()
        s.polish_model = self.polish_model.text().strip()
        s.reuse_results = self.reuse_results.isChecked()
        s.theme = self.theme.currentText()
        s.font_size = int(self.font_size.currentData())
        s.check_updates_on_startup = self.startup.isChecked()
        if self.key.text():
            store(s.provider, self.key.text())
            self.key.clear()
        save_settings(s)
        self.accept()

    def provider_obj(self):
        s = self.settings.model_copy(
            update={
                "provider": self.provider.currentText(),
                "model": self.model.currentText(),
                "base_url": self.base.text(),
                "timeout": round(float(self.timeout.text()) * 60),
            }
        )
        key = self.key.text() or get(s.provider) or ""
        return create_provider(
            ProviderConfig(provider=s.provider, model=s.model, base_url=s.base_url, timeout=s.timeout, retries=s.retries), key
        )

    def test_connection(self):
        try:
            self.provider_obj().test_connection()
            QMessageBox.information(self, "Connection", "Connection successful · Test Connection sent a billable API request")
        except Exception as e:
            QMessageBox.warning(self, "Connection failed", str(e))

    def models(self):
        try:
            values = self.provider_obj().list_models()
            current = self.model.currentText()
            self.model.clear()
            self.model.addItems(values)
            self.model.setEditText(current or (values[0] if values else ""))
            QMessageBox.information(self, "Models", "\n".join(values) if values else "Enter model ID manually for this provider.")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (403, 404, 405, 501):
                QMessageBox.information(
                    self,
                    "Models unavailable",
                    f"ผู้ให้บริการปฏิเสธการแสดงรายการ Models (HTTP {status})\n"
                    "กรอก Model ID ในช่อง Default Model ได้เอง แล้วกด Save Settings "
                    "การแสดงรายการ Models อาจถูกจำกัดแยกจากการเรียกใช้งาน Model",
                )
                return
            QMessageBox.warning(self, "Models", f"โหลด Models ไม่สำเร็จ (HTTP {status})")
        except Exception as e:
            QMessageBox.warning(self, "Models", str(e))

    def delete_api_key(self):
        if QMessageBox.question(self, "Delete API Key", "Delete this provider's key from Windows Credential Manager?") == QMessageBox.Yes:
            delete(self.provider.currentText())
            self.key.clear()
            QMessageBox.information(self, "API Key", "API key deleted.")


class HistoryDialog(QDialog):
    def __init__(self, parent, entries):
        super().__init__(parent)
        self.setWindowTitle("History")
        self.resize(760, 440)
        self.entries = entries
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        for item in entries:
            self.items.addItem(
                f"{item.get('timestamp', '')} · {item.get('prompt_name', '')} · "
                f"{item.get('provider', '')} / {item.get('model', '')} · "
                f"{'ผ่าน' if item.get('validation_result', {}).get('passed') else 'ไม่ผ่าน'}"
            )
        layout.addWidget(self.items)
        buttons = QHBoxLayout()
        reopen = QPushButton("Reopen Result")
        copy = QPushButton("Copy Result")
        close = QPushButton("Close")
        buttons.addWidget(reopen)
        buttons.addWidget(copy)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        reopen.clicked.connect(self.accept)
        copy.clicked.connect(self.copy_selected)
        close.clicked.connect(self.reject)

    def selected_entry(self):
        index = self.items.currentRow()
        return self.entries[index] if 0 <= index < len(self.entries) else None

    def copy_selected(self):
        entry = self.selected_entry()
        if entry:
            QApplication.clipboard().setText(self._result_text(entry))

    def _result_text(self, entry):
        parsed = entry.get("parsed_result", {})
        if isinstance(parsed, list):
            return "\n".join("\t".join(map(str, row)) for row in parsed if isinstance(row, (list, tuple)))
        rows = []
        if isinstance(parsed, dict):
            for key, header in (("new", "=== คำศัพท์ใหม่ ==="), ("update", "=== คำศัพท์อัปเดต ===")):
                rows.append(header)
                values = parsed.get(key, [])
                rows.extend("\t".join(map(str, row)) for row in values if isinstance(row, (list, tuple)))
        return "\n".join(rows) if rows else entry.get("raw_response", "")

    def result_text(self):
        entry = self.selected_entry()
        return self._result_text(entry) if entry else None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TermFlow")
        self.resize(1280, 900)
        help_menu = self.menuBar().addMenu("Help")
        update_action = help_menu.addAction("Check for Updates")
        update_action.triggered.connect(self.check_updates)
        self.settings = load_settings()
        self.profile_collection = load_profiles()
        if not self.profile_collection.profiles:
            default_profile = create_profile("นิยายเรื่องแรก")
            self.profile_collection = load_profiles()
            self.profile_collection.active_profile_id = default_profile.id
        active = next(
            (profile for profile in self.profile_collection.profiles if profile.id == self.profile_collection.active_profile_id),
            self.profile_collection.profiles[0],
        )
        if self.profile_collection.active_profile_id != active.id:
            self.profile_collection.active_profile_id = active.id
            save_profiles(self.profile_collection)
        self.profile = active
        self.settings.search_chunks = active.search_chunks
        self.settings.selected_search_prompt = active.selected_search_prompt
        self.settings.selected_polish_prompt = active.selected_polish_prompt
        self.apply_theme()
        self.workflow = Workflow()
        self.source_path = self.profile.source_path
        self.vocab_path = self.profile.vocab_path
        self._thread = None
        self._search_thread = None
        self._search_worker = None
        self._search_batch = None
        self._search_prompt = None
        self._search_selected_prompt = None
        self._search_config = None
        self._search_api_key = None
        self.search_progress = None
        self._close_after_worker = False
        self.update_thread = None
        self.download_thread = None
        root = QWidget()
        layout = QVBoxLayout(root)
        head = QHBoxLayout()
        title = QLabel(f"<h1>TermFlow</h1><p>Glossary Extraction &amp; Polish Workbench · Version {__version__}</p>")
        head.addWidget(title)
        head.addStretch()
        self.profile_button = QPushButton(f"เรื่อง: {self.profile.name}")
        self.profile_button.clicked.connect(self.manage_profiles)
        head.addWidget(self.profile_button)
        for label, fn in [
            ("New Session", self.new_session),
            ("Open SOURCE", self.open_source),
            ("Open VOCAB", self.open_vocab),
            ("Settings", self.open_settings),
            ("Prompt Manager", self.prompt_manager),
            ("History", self.history_dialog),
            ("Check for Updates", self.check_updates),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            head.addWidget(b)
        layout.addLayout(head)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.source_view = QPlainTextEdit()
        self.source_view.setPlaceholderText("Open SOURCE file or paste text here")
        self.tabs.addTab(self.source_view, "1. หาศัพท์")
        self.vocab_view = QPlainTextEdit()
        self.vocab_view.setReadOnly(True)
        self.vocab_view.setPlaceholderText("VOCAB is read only 🔒")
        self.tabs.addTab(self.vocab_view, "VOCAB · READ ONLY 🔒")
        review = QWidget()
        rv = QVBoxLayout(review)
        self.new_table = CopyableTableWidget()
        self.update_table = CopyableTableWidget()
        self.final_table = QTableWidget(0, 4)
        self.final_table.setHorizontalHeaderLabels(["CN", "TH", "SEX", "NOTE"])
        self.final_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.final_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        rv.addWidget(QLabel("ศัพท์ใหม่ · CN    TH    SEX    NOTE"))
        rv.addWidget(self.new_table)
        rv.addWidget(QLabel("ศัพท์อัปเดต · CN    TH    SEX    NOTE"))
        rv.addWidget(self.update_table)
        rv.addWidget(QLabel("ลากเลือกข้อความแล้วกด Ctrl+C แบบ VS Code · คลิกหรือกวาดแถบเลขบรรทัดเพื่อเลือกศัพท์สำหรับ Polish"))
        row = QHBoxLayout()
        self.search_action_buttons = {}
        for label, fn in [
            ("Select All", lambda: self.select_rows(True)),
            ("Select None", lambda: self.select_rows(False)),
            ("Run Search", self.run_search),
            ("Send Selected NEW to Polish", self.run_polish),
            ("Copy NEW", lambda: self.copy_table(self.new_table)),
            ("Copy UPDATE", lambda: self.copy_table(self.update_table)),
            ("Copy All", self.copy_all_a),
            ("บันทึกผลรวม", self.export_search_result),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
            if label in {"Run Search", "Send Selected NEW to Polish", "บันทึกผลรวม"}:
                self.search_action_buttons[label] = b
        rv.addLayout(row)
        rv.addWidget(QLabel("Final Result · CN / TH / SEX / NOTE"))
        rv.addWidget(self.final_table)
        copy = QHBoxLayout()
        for label, fn in [
            ("Copy Selected", lambda: self.copy_final(selected=True)),
            ("Copy All", self.copy_final),
            ("Copy as Step A Format", self.copy_step_a_format),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            copy.addWidget(b)
        rv.addLayout(copy)
        self.tabs.addTab(review, "2–4. ตรวจผล / เกลา / Copy")
        self.setCentralWidget(root)
        self.apply_theme()
        self.results_stale = False
        self.stale_label = QLabel("ไฟล์ SOURCE หรือ VOCAB เปลี่ยนแล้ว · ผลเดิมอาจล้าสมัย กรุณาค้นหาใหม่")
        self.stale_label.setStyleSheet("color: #a05a00; font-weight: bold")
        self.stale_label.setVisible(False)
        rv.insertWidget(0, self.stale_label)
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.fileChanged.connect(self.schedule_file_check)
        self.file_watcher.directoryChanged.connect(self.schedule_file_check)
        self.file_check_timer = QTimer(self)
        self.file_check_timer.setSingleShot(True)
        self.file_check_timer.setInterval(500)
        self.file_check_timer.timeout.connect(self.check_profile_files)
        self.file_signatures = {}
        self.pending_file_refreshes = {}
        self.initialize_profile_files()
        self.statusBar().showMessage("Ready")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_request)
        self.cancel_button.setVisible(False)
        self.statusBar().addPermanentWidget(self.cancel_button)
        if self.settings.show_welcome:
            self.welcome()
        if self.settings.check_updates_on_startup:
            self.check_updates(silent=True)

    def _busy_with_ai(self):
        return bool(
            (self._search_thread and self._search_thread.isRunning())
            or (self._thread and self._thread.isRunning())
        )

    def _save_profile_state(self):
        if not getattr(self, "profile", None):
            return
        if self.profile.id not in {item.id for item in load_profiles().profiles}:
            return
        self.profile = update_profile(
            self.profile.id,
            source_path=self.source_path,
            vocab_path=self.vocab_path,
            search_chunks=self.settings.search_chunks,
            selected_search_prompt=self.settings.selected_search_prompt,
            selected_polish_prompt=self.settings.selected_polish_prompt,
        )
        self.profile_collection = load_profiles()

    def manage_profiles(self):
        if self._busy_with_ai():
            QMessageBox.information(self, "โปรไฟล์นิยาย", "รอให้คำขอ AI ที่กำลังทำงานจบก่อนสลับโปรไฟล์")
            return
        self._save_profile_state()
        dialog = NovelProfileDialog(self, self.profile.id)
        if dialog.exec():
            if dialog.selected_profile_id != self.profile.id:
                self.switch_profile(dialog.selected_profile_id)
            else:
                self.profile = next(
                    item for item in load_profiles().profiles if item.id == self.profile.id
                )
                self.profile_button.setText(f"เรื่อง: {self.profile.name}")
        else:
            collection = load_profiles()
            if collection.active_profile_id != self.profile.id:
                self.switch_profile(collection.active_profile_id)
            else:
                self.profile = next(item for item in collection.profiles if item.id == self.profile.id)
                self.profile_button.setText(f"เรื่อง: {self.profile.name}")

    def switch_profile(self, profile_id):
        self._save_profile_state()
        set_active_profile(profile_id)
        self.profile_collection = load_profiles()
        self.profile = next(item for item in self.profile_collection.profiles if item.id == profile_id)
        self.profile_button.setText(f"เรื่อง: {self.profile.name}")
        self.settings.search_chunks = self.profile.search_chunks
        self.settings.selected_search_prompt = self.profile.selected_search_prompt
        self.settings.selected_polish_prompt = self.profile.selected_polish_prompt
        save_settings(self.settings)
        self.new_table.clear()
        self.update_table.clear()
        self.final_table.setRowCount(0)
        self._set_results_stale(False)
        self.source_view.clear()
        self.vocab_view.clear()
        self.source_path = self.profile.source_path
        self.vocab_path = self.profile.vocab_path
        self.workflow = Workflow()
        self.initialize_profile_files()
        self.statusBar().showMessage(f"เปิดโปรไฟล์: {self.profile.name}")

    def initialize_profile_files(self):
        self.file_signatures = {}
        self._refresh_watched_paths()
        for kind, path in (("source", self.source_path), ("vocab", self.vocab_path)):
            if not path:
                continue
            try:
                snapshot = file_snapshot(path)
                self.file_signatures[kind] = snapshot.sha256
                self._apply_file_snapshot(kind, snapshot, initial=True)
            except (OSError, UnicodeError) as exc:
                self.file_signatures[kind] = None
                label = "SOURCE" if kind == "source" else "VOCAB"
                self.statusBar().showMessage(f"อ่าน {label} ไม่สำเร็จ: {exc}")
        missing = [
            label
            for label, path in (("SOURCE", self.source_path), ("VOCAB", self.vocab_path))
            if path and not Path(path).is_file()
        ]
        if missing:
            self.statusBar().showMessage(f"ไม่พบไฟล์ {' / '.join(missing)} ของโปรไฟล์นี้ · เลือกไฟล์ใหม่ได้")

    def _refresh_watched_paths(self):
        old_files = self.file_watcher.files()
        old_dirs = self.file_watcher.directories()
        if old_files:
            self.file_watcher.removePaths(old_files)
        if old_dirs:
            self.file_watcher.removePaths(old_dirs)
        paths = [path for path in (self.source_path, self.vocab_path) if path]
        files = [path for path in paths if Path(path).is_file()]
        directories = list(dict.fromkeys(str(Path(path).parent) for path in paths if Path(path).parent.is_dir()))
        if files:
            self.file_watcher.addPaths(files)
        if directories:
            self.file_watcher.addPaths(directories)

    def schedule_file_check(self, *_args):
        self.file_check_timer.start()

    def check_profile_files(self):
        for kind, path in (("source", self.source_path), ("vocab", self.vocab_path)):
            if not path:
                continue
            try:
                snapshot = file_snapshot(path)
            except (OSError, UnicodeError) as exc:
                if self.file_signatures.get(kind) is not None:
                    self.file_signatures[kind] = None
                    self._mark_results_stale()
                    self.statusBar().showMessage(f"หาไฟล์ {'SOURCE' if kind == 'source' else 'VOCAB'} ไม่พบหรืออ่านไม่ได้: {exc}")
                continue
            previous = self.file_signatures.get(kind)
            if previous is not None and previous != snapshot.sha256:
                self.file_signatures[kind] = snapshot.sha256
                if self._busy_with_ai():
                    self.pending_file_refreshes[kind] = snapshot
                    self.statusBar().showMessage("ไฟล์เปลี่ยนระหว่างคำขอ · จะโหลดเนื้อหาใหม่เมื่องานปัจจุบันจบ")
                else:
                    self._apply_file_snapshot(kind, snapshot)
            elif previous is None:
                self.file_signatures[kind] = snapshot.sha256
                self._apply_file_snapshot(kind, snapshot)
        self._refresh_watched_paths()

    def _apply_file_snapshot(self, kind, snapshot: FileSnapshot, initial=False):
        if kind == "source":
            if not initial and self.source_view.document().isModified():
                choice = QMessageBox.question(
                    self,
                    "SOURCE เปลี่ยนแปลง",
                    "ไฟล์ SOURCE ถูกแก้ไขภายนอก แต่มีข้อความที่ยังไม่ได้บันทึกในหน้าจอ ต้องการโหลดไฟล์ล่าสุดหรือไม่?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if choice != QMessageBox.Yes:
                    self._mark_results_stale()
                    self.statusBar().showMessage("เก็บข้อความ SOURCE ในหน้าจอไว้ · ไฟล์บนดิสก์มีการเปลี่ยนแปลง")
                    return
            self.source_view.setPlainText(snapshot.text)
            self.source_view.document().setModified(False)
            self.workflow.source = snapshot.text
        else:
            self.vocab_view.setPlainText(snapshot.text)
            self.workflow.vocab = snapshot.text
        if not initial:
            self._mark_results_stale()
            label = "SOURCE" if kind == "source" else "VOCAB"
            self.statusBar().showMessage(f"โหลด {label} เวอร์ชันล่าสุดแล้ว · ผลค้นหาเดิมถูกทำเครื่องหมายว่าล้าสมัย")

    def _finish_pending_file_refreshes(self):
        if self._busy_with_ai() or not self.pending_file_refreshes:
            return
        pending = self.pending_file_refreshes
        self.pending_file_refreshes = {}
        for kind, snapshot in pending.items():
            self._apply_file_snapshot(kind, snapshot)

    def _after_ai_thread_finished(self):
        QTimer.singleShot(0, self._finish_pending_file_refreshes)

    def _set_results_stale(self, stale):
        self.results_stale = stale
        self.stale_label.setVisible(stale)
        polish_button = self.search_action_buttons.get("Send Selected NEW to Polish")
        if polish_button:
            polish_button.setEnabled(not stale)

    def _mark_results_stale(self):
        if self.new_table.row_count() or self.update_table.row_count() or self.final_table.rowCount():
            self._set_results_stale(True)

    def _record_profile_file(self, kind, path):
        if kind == "source":
            self.source_path = path
        else:
            self.vocab_path = path
        self.file_signatures[kind] = file_snapshot(path).sha256
        self._save_profile_state()
        self._refresh_watched_paths()
        self._mark_results_stale()

    def _clear_profile_workspace(self):
        self.source_view.clear()
        self.vocab_view.clear()
        self.new_table.clear()
        self.update_table.clear()
        self.final_table.setRowCount(0)
        self._set_results_stale(False)

    def welcome(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Welcome to TermFlow")
        layout = QVBoxLayout(dialog)
        instructions = (
            "Welcome to TermFlow\n\n1. ตั้งค่า AI Provider\n2. เลือก/เปิด VOCAB\n3. เปิด SOURCE\n"
            "4. Run Search\n5. Review\n6. Polish\n7. Copy"
        )
        layout.addWidget(QLabel(instructions))
        hide = QCheckBox("Do not show again")
        layout.addWidget(hide)
        close = QPushButton("เริ่มใช้งาน")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        self.settings.show_welcome = not hide.isChecked()
        save_settings(self.settings)

    def apply_theme(self):
        app = QApplication.instance()
        if self.settings.theme != "Dark":
            app.setPalette(app.style().standardPalette())
        else:
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(37, 40, 46))
            palette.setColor(QPalette.WindowText, QColor(235, 237, 240))
            palette.setColor(QPalette.Base, QColor(27, 29, 34))
            palette.setColor(QPalette.AlternateBase, QColor(45, 48, 55))
            palette.setColor(QPalette.ToolTipBase, QColor(235, 237, 240))
            palette.setColor(QPalette.ToolTipText, QColor(27, 29, 34))
            palette.setColor(QPalette.Text, QColor(235, 237, 240))
            palette.setColor(QPalette.Button, QColor(52, 56, 64))
            palette.setColor(QPalette.ButtonText, QColor(235, 237, 240))
            palette.setColor(QPalette.Highlight, QColor(62, 128, 210))
            palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            app.setPalette(palette)
        app.setFont(QFont("Segoe UI", self.settings.font_size))
        dark_editor = app.palette().color(QPalette.Window).lightness() < 128
        for editor in (getattr(self, "new_table", None), getattr(self, "update_table", None)):
            if editor:
                editor.set_editor_theme(dark_editor)
                editor.set_text_point_size(self.settings.font_size + 2)

    def open_source(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open SOURCE", "", "Text files (*.txt *.md);;All files (*)")
        if p:
            try:
                snapshot = file_snapshot(p)
                self.source_view.setPlainText(snapshot.text)
                self.source_view.document().setModified(False)
                self.workflow.source = snapshot.text
                self._record_profile_file("source", p)
                self.statusBar().showMessage("SOURCE loaded")
            except Exception as e:
                QMessageBox.warning(self, "Open SOURCE", str(e))

    def open_vocab(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open VOCAB", "", "VOCAB files (*.txt *.tsv);;All files (*)")
        if p:
            try:
                snapshot = file_snapshot(p)
                self.vocab_view.setPlainText(snapshot.text)
                self.workflow.vocab = snapshot.text
                self._record_profile_file("vocab", p)
                self.statusBar().showMessage("VOCAB loaded · READ ONLY")
            except Exception as e:
                QMessageBox.warning(self, "Open VOCAB", str(e))

    def prompt_file(self, step):
        category = "Search" if step == "A" else "Polish"
        prompt_id = self.settings.selected_search_prompt if step == "A" else self.settings.selected_polish_prompt
        return next((x for x in list_prompts() if x["id"] == prompt_id and x["category"] == category), None)

    def request(self, step, user_input=""):
        selected_model = self.settings.model_for_step(step)
        if not selected_model:
            self.open_settings()
            self.settings = load_settings()
            selected_model = self.settings.model_for_step(step)
        secret = get(self.settings.provider)
        if not secret:
            QMessageBox.warning(self, "API Key", "ตั้งค่า API Key ก่อนใช้งาน")
            return
        try:
            selected_prompt = self.prompt_file(step)
            if not selected_prompt:
                raise ValueError("Selected prompt is unavailable; open Prompt Manager and select a prompt.")
            prompt = selected_prompt["content"]
            if not prompt.strip():
                raise ValueError("Selected prompt is empty.")
        except Exception as e:
            QMessageBox.warning(self, "Prompt", str(e))
            return
        # Exact prompt text is passed unchanged as system prompt. The execution wrapper is separate user content.
        wrapper = "Return the requested result only. Do not write or modify files."
        if step == "B":
            wrapper += (
                "\nInclude a distinct section headed exactly: === COPY-READY TSV ===, followed only by the polished rows "
                "as CN<TAB>TH<TAB>NOTE. Preserve one row for every input row."
            )
        request = GenerateRequest(
            prompt=prompt,
            source=self.source_view.toPlainText() if step == "A" else "",
            vocab=self.vocab_view.toPlainText(),
            user_input=wrapper + ("\n\n" + user_input if user_input else ""),
        )
        provider = create_provider(
            ProviderConfig(
                provider=self.settings.provider,
                model=selected_model,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                retries=self.settings.retries,
            ),
            secret,
        )
        self._step = step
        self._prompt = prompt
        self._selected_prompt = selected_prompt
        self._request = request
        self._request_cache_key = cache_key(
            workflow=f"step-{step}", provider=self.settings.provider, base_url=self.settings.base_url,
            model=selected_model, prompt=prompt, source=request.source, vocab=request.vocab,
            user_input=request.user_input, validator_version=f"step-{step}-v1",
        )
        validator = (lambda value: validate_step_b(value, [line.split("\t") for line in self._b_input().splitlines()])) if step == "B" else None
        if self.settings.reuse_results and validator is not None:
            cached = ResultCache().get(self._request_cache_key, validator)
            if cached is not None:
                self._cache_hit = True
                self.on_response(cached)
                self.statusBar().showMessage("ใช้ผลเดิมที่ตรวจผ่านแล้ว · ไม่เรียก API")
                return
        self._cache_hit = False
        self.statusBar().showMessage("Searching..." if step == "A" else "Polishing...")
        self._provider = provider
        self.start_worker(provider, request)

    def start_worker(self, provider, request):
        self._request_started_at = monotonic()
        self.cancel_button.setVisible(True)
        self._thread = QThread()
        self._worker = Worker(provider, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self.on_response)
        self._worker.failed.connect(self.on_error)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._close_after_background_work)
        self._thread.finished.connect(self._after_ai_thread_finished)
        self._thread.start()

    def closeEvent(self, event):
        active_search = self._search_thread and self._search_thread.isRunning()
        active_request = self._thread and self._thread.isRunning()
        if active_search or active_request:
            self._close_after_worker = True
            if active_search:
                self.cancel_search_batch()
            elif self._provider:
                self._provider.cancel()
            self.statusBar().showMessage("กำลังยกเลิกคำขอก่อนปิดโปรแกรม…")
            event.ignore()
            return
        event.accept()

    def _close_after_background_work(self):
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def run_search(self):
        if self._search_thread and self._search_thread.isRunning():
            return
        self.workflow.source = self.source_view.toPlainText()
        self.workflow.vocab = self.vocab_view.toPlainText()
        if not self.workflow.source.strip():
            QMessageBox.information(self, "หาศัพท์", "เปิด SOURCE หรือวางเนื้อหาก่อนเริ่มค้นหา")
            return
        if not self.settings.model_for_step("A"):
            self.open_settings()
            self.settings = load_settings()
        if not self.settings.model_for_step("A"):
            QMessageBox.information(self, "Model", "เลือก Default Model ใน Settings ก่อนเริ่มค้นหา")
            return
        api_key = get(self.settings.provider)
        if not api_key:
            QMessageBox.warning(self, "API Key", "ตั้งค่า API Key ก่อนใช้งาน")
            return
        selected_prompt = self.prompt_file("A")
        if not selected_prompt or not selected_prompt.get("content", "").strip():
            QMessageBox.warning(self, "Prompt", "ไม่พบ Prompt A ที่เลือก กรุณาเลือก Prompt ใน Prompt Manager")
            return
        try:
            plan = plan_search(selected_prompt["content"], self.workflow.vocab, self.workflow.source, context_window=128_000)
        except ValueError as exc:
            QMessageBox.warning(self, "หาศัพท์", f"คำนวณขนาดคำขอไม่สำเร็จ: {exc}")
            return
        chunk_count = max(plan.chunk_count, self.settings.search_chunks)
        estimated_total = plan.estimated_total_tokens + max(0, chunk_count - plan.chunk_count) * (
            estimate_tokens(selected_prompt["content"]) + estimate_tokens(self.workflow.vocab) + 256
        )
        preview = (
            f"SOURCE: {len(self.workflow.source):,} characters\n"
            f"Estimated API requests: {chunk_count}\n"
            f"Estimated input: ~{estimated_total:,} tokens"
            + ("\nPrompt และ VOCAB จะถูกส่งซ้ำในแต่ละ request" if chunk_count > 1 else "")
            + "\n\nเริ่ม Search หรือไม่?"
        )
        if QMessageBox.question(self, "Search request preview", preview) != QMessageBox.Yes:
            return
        try:
            self.workflow.begin_search()
        except ValueError as exc:
            QMessageBox.warning(self, "หาศัพท์", str(exc))
            return
        self._search_batch = SearchBatch(split_source(self.workflow.source, count=chunk_count, overlap_units=1))
        self._search_prompt = selected_prompt["content"]
        self._search_selected_prompt = selected_prompt
        self._search_api_key = api_key
        self._search_config = ProviderConfig(
            provider=self.settings.provider,
            model=self.settings.model_for_step("A"),
            base_url=self.settings.base_url,
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            reuse_results=self.settings.reuse_results,
        )
        if self.search_progress is None or self.search_progress.chunk_count != chunk_count:
            self.search_progress = SearchProgressDialog(self, chunk_count=chunk_count)
            self.search_progress.cancel_requested.connect(self.cancel_search_batch)
            self.search_progress.retry_requested.connect(self.retry_failed_chunks)
            self.search_progress.split_requested.connect(self.split_failed_chunk)
        self.search_progress.show()
        self._start_search_worker()

    def _start_search_worker(self):
        self.search_progress.set_active(True)
        self.cancel_button.setVisible(True)
        for button in self.search_action_buttons.values():
            button.setEnabled(False)
        self.statusBar().showMessage(f"กำลังค้นหาทั้ง {len(self._search_batch.runs)} ช่วง…")
        self._search_thread = QThread(self)
        self._search_worker = MultiSearchWorker(
            self._search_batch,
            self._search_prompt,
            self.workflow.vocab,
            self._search_config,
            self._search_api_key,
        )
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.progress.connect(self.search_progress.update_chunk)
        self._search_worker.finished.connect(self.on_search_batch_finished)
        self._search_worker.failed.connect(self.on_search_batch_error)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_worker.failed.connect(self._search_thread.quit)
        self._search_thread.finished.connect(self._search_worker.deleteLater)
        self._search_thread.finished.connect(self._close_after_background_work)
        self._search_thread.finished.connect(self._after_ai_thread_finished)
        self._search_thread.start()

    def cancel_search_batch(self):
        if self._search_worker:
            self._search_worker.cancel()
            self.statusBar().showMessage("กำลังยกเลิกคำขอที่กำลังทำงาน…")

    def retry_failed_chunks(self):
        if self._search_thread and self._search_thread.isRunning():
            return
        failed = [run for run in self._search_batch.runs if run.status == ChunkStatus.FAILED]
        if not failed:
            return
        answer = QMessageBox.question(
            self, "ส่งคำขอใหม่", "การลองใหม่จะสร้าง API request ใหม่และอาจมีค่าใช้จ่าย ดำเนินการต่อหรือไม่?"
        )
        if answer != QMessageBox.Yes:
            return
        for run in failed:
            self._search_batch.retry_chunk(run.chunk.index)
        self._search_batch.resume()
        try:
            self.workflow.state.transition(State.SEARCH_RUNNING)
        except ValueError:
            pass
        self._start_search_worker()

    def split_failed_chunk(self):
        if self._search_thread and self._search_thread.isRunning():
            return
        failed = next((run for run in self._search_batch.runs if run.status == ChunkStatus.FAILED), None)
        if failed is None:
            return
        answer = QMessageBox.question(
            self,
            "แบ่ง SOURCE ช่วงที่ล้มเหลว",
            "ช่วงนี้จะถูกแบ่งเป็นสูงสุด 2 API requests (ผลที่ cache ตรงกันอาจ reuse ได้) และ Prompt กับ VOCAB จะถูกส่งซ้ำในแต่ละ request\n"
            f"คำขอที่ timeout ไปแล้ว: {failed.request_count} · ดำเนินการต่อหรือไม่?",
        )
        if answer != QMessageBox.Yes:
            return
        first, second = SearchCoordinator._split_source(failed.chunk.text)
        if not first.strip() or not second.strip():
            QMessageBox.warning(self, "แบ่งช่วงไม่ได้", "ช่วงนี้สั้นเกินกว่าจะแบ่งเป็นคำขอที่มีข้อความทั้งสองส่วน")
            return
        start = failed.chunk.request_start
        middle = start + len(first)
        child_runs = [
            ChunkRun(SourceChunk(0, start, middle, start, middle, first)),
            ChunkRun(SourceChunk(0, middle, failed.chunk.request_end, middle, failed.chunk.request_end, second)),
        ]
        child_runs[0].request_count = failed.request_count
        child_runs[0].retry_count = failed.retry_count
        child_runs[0].attempts = list(failed.attempts)
        runs = []
        for run in self._search_batch.runs:
            if run is failed:
                runs.extend(child_runs)
            else:
                runs.append(run)
        for index, run in enumerate(runs, 1):
            run.chunk = replace(run.chunk, index=index)
        self._search_batch.runs = runs
        self._search_batch.chunks = tuple(run.chunk for run in runs)
        self.search_progress.close()
        self.search_progress = SearchProgressDialog(self, chunk_count=len(runs))
        self.search_progress.cancel_requested.connect(self.cancel_search_batch)
        self.search_progress.retry_requested.connect(self.retry_failed_chunks)
        self.search_progress.split_requested.connect(self.split_failed_chunk)
        self.search_progress.show()
        try:
            self.workflow.state.transition(State.SEARCH_RUNNING)
        except ValueError:
            pass
        self._start_search_worker()

    def on_search_batch_error(self, message):
        self.cancel_button.setVisible(False)
        for button in self.search_action_buttons.values():
            button.setEnabled(True)
        self.search_progress.set_active(False)
        try:
            self.workflow.state.transition(State.SEARCH_FAILED)
        except ValueError:
            pass
        self.statusBar().showMessage("ค้นหาไม่สำเร็จ")
        QMessageBox.warning(self, "ค้นหาศัพท์ไม่สำเร็จ", message)

    def on_search_batch_finished(self, batch):
        self.cancel_button.setVisible(False)
        for button in self.search_action_buttons.values():
            button.setEnabled(True)
        self._search_batch = batch
        self.search_progress.set_batch(batch)
        if any(run.status == ChunkStatus.FAILED for run in batch.runs):
            try:
                self.workflow.state.transition(State.SEARCH_FAILED)
            except ValueError:
                pass
            self.statusBar().showMessage("บางช่วงค้นหาไม่สำเร็จ · กดลองช่วงที่ผิดพลาดอีกครั้ง")
            return
        if batch.cancellation_requested or any(run.status == ChunkStatus.CANCELLED for run in batch.runs):
            try:
                self.workflow.state.transition(State.READY_FOR_SEARCH)
            except ValueError:
                pass
            self.statusBar().showMessage("ยกเลิกการค้นหาแล้ว · ผลที่ยังไม่ครบจะไม่ถูกรวม")
            return
        try:
            aggregation = aggregate_batch(batch)
            if aggregation.conflicts:
                dialog = ConflictResolutionDialog(aggregation, self)
                if dialog.exec() != QDialog.Accepted:
                    self.workflow.state.transition(State.SEARCH_FAILED)
                    self.statusBar().showMessage("ยังไม่รวมผล · เลือกผลที่ขัดแย้งแล้วค้นหาใหม่ได้")
                    return
                aggregation = apply_conflict_choices(aggregation, dialog.choices)
            new_rows, update_rows = aggregation.new_rows, aggregation.update_rows
            combined_raw = format_step_a_result(new_rows, update_rows)
            self.workflow.accept_search(combined_raw)
            self.fill_table(self.new_table, new_rows)
            self.fill_table(self.update_table, update_rows)
            self.final_table.setRowCount(0)
            self._set_results_stale(False)
            self._save_search_batch_history(new_rows, update_rows)
            self.statusBar().showMessage(f"Search Complete · NEW {len(new_rows)} · UPDATE {len(update_rows)}")
        except Exception as exc:
            try:
                self.workflow.state.transition(State.SEARCH_FAILED)
            except ValueError:
                pass
            self.statusBar().showMessage("Validation Failed")
            QMessageBox.warning(self, "รวมผลค้นหาไม่สำเร็จ", str(exc))

    def _save_search_batch_history(self, new_rows, update_rows):
        batch = self._search_batch
        input_text = self.workflow.source + self.workflow.vocab
        secret = self._search_api_key or ""

        def redact(value):
            if isinstance(value, str):
                return value.replace(secret, "[REDACTED]") if secret else value
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, tuple):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value

        record = {
                "workflow": f"{len(batch.runs)}-part-search",
                "source_filename": Path(self.source_path).name if self.source_path else "",
                "vocab_filename": Path(self.vocab_path).name if self.vocab_path else "",
                "prompt_id": self._search_selected_prompt["id"],
                "prompt_name": self._search_selected_prompt["name"],
                "prompt_version": self._search_selected_prompt["version"],
                "exact_prompt_text": self._search_prompt,
                "prompt_sha256": hashlib.sha256(self._search_prompt.encode("utf-8")).hexdigest(),
                "provider": self._search_config.provider,
                "model": self._search_config.model,
                "input_hash": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "parsed_result": {"new": new_rows, "update": update_rows},
                "validation_result": {"passed": True, "details": "All non-empty source chunks passed strict STEP A validation."},
                "chunks": [
                    {
                        "index": run.chunk.index,
                        "core_range": [run.chunk.core_start, run.chunk.core_end],
                        "request_range": [run.chunk.request_start, run.chunk.request_end],
                        "input_sha256": hashlib.sha256(run.chunk.text.encode("utf-8")).hexdigest(),
                        "status": run.status.value,
                        "retry_count": run.retry_count,
                        "request_count": run.request_count,
                        "usage": run.usage,
                        "cache_hit": run.cache_hit,
                        "duration_seconds": run.duration_seconds,
                        "raw_response": run.original_response or run.raw_response,
                        "repaired_response": run.repaired_response,
                        "origin": run.origin,
                        "parsed_result": {"new": run.new_rows, "update": run.update_rows},
                        "validation_result": {"passed": run.status == ChunkStatus.COMPLETE, "details": run.error},
                        "attempts": run.attempts,
                    }
                    for run in batch.runs
                ],
                "api_request_count": sum(run.request_count for run in batch.runs),
                "usage": {
                    "input_tokens": sum(run.usage.get("input_tokens") or 0 for run in batch.runs) or None,
                    "output_tokens": sum(run.usage.get("output_tokens") or 0 for run in batch.runs) or None,
                },
                "cache_hit": any(run.cache_hit for run in batch.runs),
                "duration_seconds": sum(run.duration_seconds for run in batch.runs),
                "timeout_seconds": self._search_config.timeout,
            }
        save_snapshot(redact(record))

    def export_search_result(self):
        if self.workflow.state.current not in {State.USER_REVIEW, State.FINAL_READY}:
            QMessageBox.information(self, "บันทึกผลรวม", "ต้องค้นหาและตรวจผลครบก่อน")
            return
        destination, _ = QFileDialog.getSaveFileName(self, "บันทึกผลค้นหา", "TermFlow-ผลค้นหา.txt", "Text files (*.txt)")
        if not destination:
            return
        target = Path(destination).resolve()
        protected = {Path(path).resolve() for path in (self.source_path, self.vocab_path) if path}
        if target in protected:
            QMessageBox.warning(self, "บันทึกไม่ได้", "เลือก path ใหม่ ห้ามบันทึกทับ SOURCE หรือ VOCAB")
            return
        content = format_step_a_result(self.new_table.all_rows(), self.update_table.all_rows())
        temp_path = None
        try:
            destination_path = Path(destination)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=destination_path.parent, delete=False) as stream:
                stream.write(content)
                temp_path = Path(stream.name)
            os.replace(temp_path, destination_path)
            QMessageBox.information(self, "บันทึกผลรวม", "บันทึกไฟล์ผลค้นหาเรียบร้อย")
        except Exception as exc:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            QMessageBox.warning(self, "บันทึกผลรวมไม่สำเร็จ", str(exc))

    def run_polish(self):
        if self.results_stale:
            QMessageBox.information(self, "Polish", "SOURCE หรือ VOCAB เปลี่ยนแล้ว กรุณา Run Search ใหม่ก่อนเกลาศัพท์")
            return
        selected = self.new_table.selected_rows()
        if not selected:
            QMessageBox.information(self, "Polish", "เลือก NEW อย่างน้อยหนึ่งรายการ")
            return
        try:
            payload = self.workflow.prepare_polish(selected)
        except Exception as e:
            QMessageBox.warning(self, "Polish", str(e))
            return
        self.workflow.begin_polish()
        self.request("B", payload)

    def on_response(self, raw):
        self.cancel_button.setVisible(False)
        original_raw = raw
        repaired_response = ""
        self._local_repair_response = ""
        try:
            if self._step == "A":
                new, updates = self.workflow.accept_search(raw)
                self.fill_table(self.new_table, new)
                self.fill_table(self.update_table, updates)
                self.final_table.setRowCount(0)
                self._set_results_stale(False)
                parsed = {"new": new, "update": updates}
                valid = True
                self.statusBar().showMessage("Search Complete")
            else:
                try:
                    validate_step_b(raw, [line.split("\t") for line in self._b_input().splitlines()])
                except Exception:
                    repaired_response = repair_formatting(raw, "B") or ""
                    if not repaired_response:
                        raise
                    validate_step_b(repaired_response, [line.split("\t") for line in self._b_input().splitlines()])
                    raw = repaired_response
                    self._local_repair_response = repaired_response
                final = self.workflow.accept_polish(raw, self._b_input())
                self.fill_final_table(final)
                parsed = final
                valid = True
                self.statusBar().showMessage("Polish Complete")
        except Exception as e:
            valid = False
            parsed = []
            self.statusBar().showMessage("Validation Failed")
            self.save_current_snapshot(original_raw, {"validation_error": str(e)}, valid)
            self.validation_failure(str(e), raw)
            return
        self.save_current_snapshot(original_raw, parsed, valid)
        if valid and self.settings.reuse_results and getattr(self, "_request_cache_key", None) and self._step == "B":
            validator = lambda value: validate_step_b(value, [line.split("\t") for line in self._b_input().splitlines()])
            secret = get(self.settings.provider) or ""
            cache_result = repaired_response or raw
            if not secret or secret not in cache_result:
                ResultCache().put(self._request_cache_key, cache_result, validator)

    def _b_input(self):
        return "\n".join(x.b_input for x in self.workflow.adapted)

    def save_current_snapshot(self, raw, parsed, valid):
        input_text = self._request.user_input + self._request.source + self._request.vocab
        save_snapshot(
            {
                "source_filename": Path(self.source_path).name if self.source_path else "",
                "vocab_filename": Path(self.vocab_path).name if self.vocab_path else "",
                "prompt_id": self._selected_prompt["id"],
                "prompt_name": self._selected_prompt["name"],
                "prompt_version": self._selected_prompt["version"],
                "exact_prompt_text": self._prompt,
                "prompt_sha256": hashlib.sha256(self._prompt.encode("utf-8")).hexdigest(),
                "provider": self.settings.provider,
                "model": self.settings.model,
                "input_hash": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                "raw_response": raw,
                "parsed_result": parsed,
                "validation_result": {"passed": valid, "details": parsed.get("validation_error", "") if isinstance(parsed, dict) else ""},
                "api_request_count": getattr(self._provider, "request_count", 0),
                "usage": {"raw": getattr(self._provider, "last_usage", {}), **getattr(self._provider, "normalized_usage", lambda: {})()},
                "cache_hit": getattr(self, "_cache_hit", False),
                "duration_seconds": max(0.0, monotonic() - getattr(self, "_request_started_at", monotonic())),
                "timeout_seconds": self.settings.timeout,
                "repaired_response": getattr(self, "_local_repair_response", ""),
            }
        )

    def on_error(self, msg):
        self.cancel_button.setVisible(False)
        self.save_current_snapshot("", {"request_error": msg}, False)
        if msg == "Request cancelled":
            try:
                target = State.READY_FOR_SEARCH if self._step == "A" else State.POLISH_READY
                self.workflow.state.transition(target)
            except ValueError:
                pass
            self.statusBar().showMessage("Cancelled")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Request failed")
        box.setText(f"Reason: {msg}")
        box.setInformativeText("การลองใหม่จะสร้าง API request ใหม่และอาจมีค่าใช้จ่าย")
        retry = box.addButton("Retry", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == retry:
            self.retry_same_request()
        self.statusBar().showMessage("Request failed")

    def cancel_request(self):
        if self._search_thread and self._search_thread.isRunning():
            self.cancel_search_batch()
            return
        if self._provider:
            self._provider.cancel()
            self.statusBar().showMessage("Cancelling request…")

    def retry_same_request(self):
        target = State.SEARCH_RUNNING if self._step == "A" else State.POLISH_RUNNING
        try:
            self.workflow.state.transition(target)
        except ValueError:
            self.workflow.state.current = State.USER_REVIEW if self._step == "A" else State.POLISH_READY
            self.workflow.state.transition(target)
        secret = get(self.settings.provider) or ""
        self._provider = create_provider(
            ProviderConfig(
                provider=self.settings.provider,
                model=self.settings.model_for_step(self._step),
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                retries=self.settings.retries,
            ),
            secret,
        )
        self.start_worker(self._provider, self._request)

    def validation_failure(self, details, raw):
        box = QMessageBox(self)
        box.setWindowTitle("STRICT VALIDATION FAILED")
        box.setText("AI output did not pass strict validation.")
        box.setInformativeText(f"{details}\n\nการลองใหม่จะสร้าง API request ใหม่และอาจมีค่าใช้จ่าย")
        retry = box.addButton("Retry Same Request", QMessageBox.AcceptRole)
        view = box.addButton("View Raw Response", QMessageBox.ActionRole)
        copy = box.addButton("Copy Raw Response", QMessageBox.ActionRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == retry:
            self.retry_same_request()
        elif box.clickedButton() == view:
            dialog = QDialog(self)
            dialog.setWindowTitle("Raw AI Response")
            dialog.resize(900, 650)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(raw)
            text.setReadOnly(True)
            layout.addWidget(text)
            dialog.exec()
        elif box.clickedButton() == copy:
            QApplication.clipboard().setText(raw)

    def fill_table(self, table, rows):
        table.fill_rows(rows)

    def select_rows(self, on):
        for table in (self.new_table, self.update_table):
            table.select_all_rows(on)

    def copy_table(self, table):
        QApplication.clipboard().setText("\n".join("\t".join(row) for row in table.selected_rows()))

    def copy_all_a(self):
        lines = []
        for table in (self.new_table, self.update_table):
            lines.extend("\t".join(row) for row in table.selected_rows())
        QApplication.clipboard().setText("\n".join(lines))

    def copy_final(self, selected=False):
        indexes = {index.row() for index in self.final_table.selectionModel().selectedRows()} if selected else set()
        rows = [
            [self.final_table.item(row, col).text() for col in range(4)]
            for row in range(self.final_table.rowCount())
            if not selected or row in indexes
        ]
        value = "\n".join("\t".join(row) for row in rows)
        QApplication.clipboard().setText(value)

    def copy_step_a_format(self):
        rows = ["\t".join(self.final_table.item(row, col).text() for col in range(4)) for row in range(self.final_table.rowCount())]
        value = "=== คำศัพท์ใหม่ ===\n" + ("\n".join(rows) if rows else "— ไม่มีรายการ —")
        value += "\n\n=== คำศัพท์อัปเดต ===\n— ไม่มีรายการ —"
        QApplication.clipboard().setText(value)

    def fill_final_table(self, rows):
        self.final_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                self.final_table.setItem(i, j, QTableWidgetItem(value))
        self.final_table.resizeColumnsToContents()

    def new_session(self):
        self.workflow = Workflow()
        self.workflow.source = self.source_view.toPlainText()
        self.workflow.vocab = self.vocab_view.toPlainText()
        self.new_table.clear()
        self.update_table.clear()
        self.final_table.setRowCount(0)
        self._set_results_stale(False)
        self.statusBar().showMessage("Ready")

    def open_settings(self):
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec():
            self.settings = load_settings()
            self._save_profile_state()
            self.apply_theme()

    def prompt_manager(self):
        dialog = PromptManagerDialog(self)
        if dialog.exec() and dialog.selected_prompt:
            prompt = dialog.selected_prompt
            if prompt["category"] == "Search":
                self.settings.selected_search_prompt = prompt["id"]
            else:
                self.settings.selected_polish_prompt = prompt["id"]
            save_settings(self.settings)
            self._save_profile_state()

    def history_dialog(self):
        entries = list_history()
        if not entries:
            QMessageBox.information(self, "History", "No history yet")
            return
        dialog = HistoryDialog(self, entries[:100])
        if dialog.exec():
            entry = dialog.selected_entry()
            if entry:
                parsed = entry.get("parsed_result", {})
                if isinstance(parsed, list):
                    self.fill_final_table(parsed)
                elif isinstance(parsed, dict):
                    self.fill_table(self.new_table, parsed.get("new", []))
                    self.fill_table(self.update_table, parsed.get("update", []))
                self.tabs.setCurrentIndex(2)

    def check_updates(self, silent=False):
        self._silent_update = silent
        self.update_thread = QThread(self)
        self.update_worker = UpdateWorker()
        self.update_worker.moveToThread(self.update_thread)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_worker.done.connect(self.on_update_check)
        self.update_worker.failed.connect(self.on_update_failed)
        self.update_worker.done.connect(self.update_thread.quit)
        self.update_worker.failed.connect(self.update_thread.quit)
        self.update_thread.start()

    def on_update_failed(self, error):
        if not self._silent_update:
            QMessageBox.warning(self, "Update check", error)

    def on_update_check(self, data):
        tag = data.get("tag_name", "")
        if not is_newer(tag):
            if not self._silent_update:
                QMessageBox.information(self, "Updates", "TermFlow is up to date")
            return
        self.statusBar().showMessage(f"Update available: {tag}")
        message = QMessageBox(self)
        message.setWindowTitle("Update available")
        message.setText(f"TermFlow {tag.removeprefix('v')} is available")
        message.setInformativeText(f"Installed: {__version__}\nLatest: {tag.removeprefix('v')}\n\n{data.get('body', '')[:3000]}")
        download_button = message.addButton("Download Update", QMessageBox.AcceptRole)
        release_button = message.addButton("Open Release Page", QMessageBox.ActionRole)
        message.addButton("Later", QMessageBox.RejectRole)
        message.exec()
        if message.clickedButton() == release_button:
            QDesktopServices.openUrl(QUrl(data.get("html_url", "")))
        elif message.clickedButton() == download_button:
            self.download_release(data)

    def download_release(self, release):
        assets = release.get("assets", [])
        installer = next((a for a in assets if a.get("name") == "TermFlow-Setup-x64.exe"), None)
        checksum = next((a for a in assets if a.get("name") == "TermFlow-Setup-x64.exe.sha256"), None)
        if not installer:
            QMessageBox.warning(self, "Update", "This release does not include a Windows x64 installer.")
            return
        self.download_progress = QProgressDialog("Downloading TermFlow update…", "Cancel", 0, 100, self)
        self.download_progress.setWindowTitle("Download Update")
        self.download_progress.setAutoClose(False)
        self.download_thread = QThread(self)
        self.download_worker = DownloadWorker(installer, checksum)
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress.connect(self.on_download_progress)
        self.download_progress.canceled.connect(self.download_worker.cancel)
        self.download_worker.done.connect(self.on_download_done)
        self.download_worker.failed.connect(self.on_download_failed)
        self.download_worker.done.connect(self.download_thread.quit)
        self.download_worker.failed.connect(self.download_thread.quit)
        self.download_thread.start()
        self.download_progress.show()

    def on_download_progress(self, done, total):
        if total:
            self.download_progress.setValue(min(99, int(done * 100 / total)))
            self.download_progress.setLabelText(f"Downloading… {done // 1048576} / {total // 1048576} MB")

    def on_download_failed(self, error):
        self.download_progress.close()
        if error != "Download cancelled":
            QMessageBox.warning(self, "Download failed", error)

    def on_download_done(self, result):
        self.download_progress.setValue(100)
        self.download_progress.close()
        path, digest = result.split("|", 1)
        self.activateWindow()
        self.raise_()
        message = QMessageBox(self)
        message.setWindowTitle("Update downloaded")
        message.setIcon(QMessageBox.Information)
        message.setText("ดาวน์โหลดอัปเดตเสร็จแล้ว · ยืนยันการติดตั้งในขั้นตอนถัดไป")
        message.setInformativeText(
            f"ไฟล์ติดตั้งตรวจสอบแล้ว\nSHA-256: {digest}\n\n"
            "กด ‘Install and Close TermFlow’ เพื่อปิด TermFlow แล้วเปิดหน้าต่างติดตั้ง "
            "จากนั้นทำตามขั้นตอนบนหน้าจอ"
        )
        message.setWindowModality(Qt.ApplicationModal)
        message.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        install_button = message.addButton("Install and Close TermFlow", QMessageBox.AcceptRole)
        message.addButton("Cancel", QMessageBox.RejectRole)
        message.setDefaultButton(install_button)
        message.exec()
        if message.clickedButton() == install_button:
            try:
                launch_installer(Path(path))
            except Exception as exc:
                QMessageBox.critical(self, "เปิดตัวติดตั้งไม่ได้", f"TermFlow เปิดตัวติดตั้งไม่สำเร็จ:\n{exc}")
                return
            QApplication.quit()


def main():
    if "--check-prompts" in sys.argv:
        from termflow.core.prompts import list_prompts

        prompts = list_prompts()
        sys.exit(0 if {item["id"] for item in prompts} >= {"builtin-search", "builtin-polish"} else 1)
    if "--remove-user-data" in sys.argv:
        for provider in ("openai", "anthropic", "gemini", "compatible"):
            delete(provider)
        shutil.rmtree(APPDATA, ignore_errors=True)
        shutil.rmtree(LOCAL, ignore_errors=True)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("TermFlow")
    configure_logging(load_settings().debug)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
