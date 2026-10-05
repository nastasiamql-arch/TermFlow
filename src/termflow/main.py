import hashlib
import shutil
import sys
import tempfile
from pathlib import Path
from threading import Event

import httpx
from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
from termflow.core.logging_config import configure_logging
from termflow.core.prompts import list_prompts
from termflow.core.state_machine import State
from termflow.core.workflow import Workflow
from termflow.storage.credentials import delete, get, store
from termflow.storage.paths import APPDATA, LOCAL
from termflow.storage.settings import load_settings, save_settings
from termflow.ui.prompt_manager import PromptManagerDialog
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
        self.timeout = QLineEdit(str(settings.timeout))
        self.retries = QLineEdit(str(settings.retries))
        self.theme = QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.setCurrentText(settings.theme)
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
        form.addRow("Timeout (seconds)", self.timeout)
        form.addRow("Retries", self.retries)
        form.addRow("Theme", self.theme)
        form.addRow("", self.startup)
        row = QHBoxLayout()
        row.addWidget(self.test)
        row.addWidget(self.load_models)
        row.addWidget(self.delete_key)
        row.addWidget(self.updates)
        row.addWidget(self.remember)
        form.addRow(row)

    def save(self):
        s = self.settings
        s.provider = self.provider.currentText()
        s.credential_name = s.provider
        s.base_url = self.base.text().strip()
        s.model = self.model.currentText().strip()
        s.timeout = int(self.timeout.text())
        s.retries = int(self.retries.text())
        s.theme = self.theme.currentText()
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
                "timeout": int(self.timeout.text()),
            }
        )
        key = self.key.text() or get(s.provider) or ""
        return create_provider(
            ProviderConfig(provider=s.provider, model=s.model, base_url=s.base_url, timeout=s.timeout, retries=s.retries), key
        )

    def test_connection(self):
        try:
            self.provider_obj().test_connection()
            QMessageBox.information(self, "Connection", "Connection successful")
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
        self.resize(1100, 760)
        help_menu = self.menuBar().addMenu("Help")
        update_action = help_menu.addAction("Check for Updates")
        update_action.triggered.connect(self.check_updates)
        self.settings = load_settings()
        self.apply_theme()
        self.workflow = Workflow()
        self.source_path = ""
        self.vocab_path = ""
        self._thread = None
        self.update_thread = None
        self.download_thread = None
        root = QWidget()
        layout = QVBoxLayout(root)
        head = QHBoxLayout()
        title = QLabel(f"<h1>TermFlow</h1><p>Glossary Extraction &amp; Polish Workbench · Version {__version__}</p>")
        head.addWidget(title)
        head.addStretch()
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
        self.new_table = QTableWidget(0, 5)
        self.new_table.setHorizontalHeaderLabels(["Select", "CN", "TH", "SEX", "NOTE"])
        self.update_table = QTableWidget(0, 5)
        self.update_table.setHorizontalHeaderLabels(["Select", "CN", "TH", "SEX", "NOTE"])
        self.final_table = QTableWidget(0, 4)
        self.final_table.setHorizontalHeaderLabels(["CN", "TH", "SEX", "NOTE"])
        self.final_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.final_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        rv.addWidget(QLabel("คำศัพท์ใหม่"))
        rv.addWidget(self.new_table)
        rv.addWidget(QLabel("คำศัพท์อัปเดต"))
        rv.addWidget(self.update_table)
        row = QHBoxLayout()
        for label, fn in [
            ("Select All", lambda: self.select_rows(True)),
            ("Select None", lambda: self.select_rows(False)),
            ("Run Search", self.run_search),
            ("Send Selected NEW to Polish", self.run_polish),
            ("Copy NEW", lambda: self.copy_table(self.new_table)),
            ("Copy UPDATE", lambda: self.copy_table(self.update_table)),
            ("Copy All", self.copy_all_a),
        ]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
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
        self.statusBar().showMessage("Ready")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_request)
        self.cancel_button.setVisible(False)
        self.statusBar().addPermanentWidget(self.cancel_button)
        if self.settings.show_welcome:
            self.welcome()
        if self.settings.check_updates_on_startup:
            self.check_updates(silent=True)

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
            return
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

    def open_source(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open SOURCE", "", "Text files (*.txt *.md);;All files (*)")
        if p:
            try:
                self.source_view.setPlainText(Path(p).read_text(encoding="utf-8-sig"))
                self.source_path = p
                self.workflow.source = self.source_view.toPlainText()
                self.statusBar().showMessage("SOURCE loaded")
            except Exception as e:
                QMessageBox.warning(self, "Open SOURCE", str(e))

    def open_vocab(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open VOCAB", "", "VOCAB files (*.txt *.tsv);;All files (*)")
        if p:
            try:
                self.vocab_view.setPlainText(Path(p).read_text(encoding="utf-8-sig"))
                self.vocab_path = p
                self.workflow.vocab = self.vocab_view.toPlainText()
                self.statusBar().showMessage("VOCAB loaded · READ ONLY")
            except Exception as e:
                QMessageBox.warning(self, "Open VOCAB", str(e))

    def prompt_file(self, step):
        category = "Search" if step == "A" else "Polish"
        prompt_id = self.settings.selected_search_prompt if step == "A" else self.settings.selected_polish_prompt
        return next((x for x in list_prompts() if x["id"] == prompt_id and x["category"] == category), None)

    def request(self, step, user_input=""):
        if not self.settings.model:
            self.open_settings()
            self.settings = load_settings()
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
                model=self.settings.model,
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
        self.statusBar().showMessage("Searching..." if step == "A" else "Polishing...")
        self._provider = provider
        self.start_worker(provider, request)

    def start_worker(self, provider, request):
        self.cancel_button.setVisible(True)
        self._thread = QThread()
        self._worker = Worker(provider, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self.on_response)
        self._worker.failed.connect(self.on_error)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def run_search(self):
        self.workflow.source = self.source_view.toPlainText()
        self.workflow.vocab = self.vocab_view.toPlainText()
        try:
            self.workflow.begin_search()
        except ValueError:
            self.workflow = Workflow()
            self.workflow.source = self.source_view.toPlainText()
            self.workflow.vocab = self.vocab_view.toPlainText()
            self.workflow.begin_search()
        self.request("A")

    def run_polish(self):
        selected = []
        for row in range(self.new_table.rowCount()):
            if self.new_table.item(row, 0).checkState().value == 2:
                selected.append([self.new_table.item(row, c).text() for c in range(1, 5)])
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
        try:
            if self._step == "A":
                new, updates = self.workflow.accept_search(raw)
                self.fill_table(self.new_table, new)
                self.fill_table(self.update_table, updates)
                parsed = {"new": new, "update": updates}
                valid = True
                self.statusBar().showMessage("Search Complete")
            else:
                final = self.workflow.accept_polish(raw, self._b_input())
                self.fill_final_table(final)
                parsed = final
                valid = True
                self.statusBar().showMessage("Polish Complete")
        except Exception as e:
            valid = False
            parsed = []
            self.statusBar().showMessage("Validation Failed")
            self.save_current_snapshot(raw, {"validation_error": str(e)}, valid)
            self.validation_failure(str(e), raw)
            return
        self.save_current_snapshot(raw, parsed, valid)

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
        retry = box.addButton("Retry", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == retry:
            self.retry_same_request()
        self.statusBar().showMessage("Request failed")

    def cancel_request(self):
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
                model=self.settings.model,
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
        box.setInformativeText(details)
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
        table.setRowCount(len(rows))
        from PySide6.QtCore import Qt

        for i, row in enumerate(rows):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            table.setItem(i, 0, item)
            for j, value in enumerate(row, 1):
                table.setItem(i, j, QTableWidgetItem(value))
        table.resizeColumnsToContents()

    def select_rows(self, on):
        from PySide6.QtCore import Qt

        for table in (self.new_table, self.update_table):
            for i in range(table.rowCount()):
                table.item(i, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def copy_table(self, table):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(
            "\n".join(
                "\t".join(table.item(i, j).text() for j in range(1, 5))
                for i in range(table.rowCount())
                if table.item(i, 0).checkState().value == 2
            )
        )

    def copy_all_a(self):
        from PySide6.QtWidgets import QApplication

        lines = []
        for table in (self.new_table, self.update_table):
            lines.extend(
                "\t".join(table.item(i, j).text() for j in range(1, 5))
                for i in range(table.rowCount())
                if table.item(i, 0).checkState().value == 2
            )
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
        QApplication.clipboard().setText(value)

    def new_session(self):
        self.workflow = Workflow()
        self.source_view.clear()
        self.new_table.setRowCount(0)
        self.update_table.setRowCount(0)
        self.final_table.setRowCount(0)
        self.statusBar().showMessage("Ready")

    def open_settings(self):
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec():
            self.settings = load_settings()
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
        answer = QMessageBox.question(
            self,
            "Ready to install",
            f"Ready to install TermFlow.\nSHA-256: {digest}\n\nInstall and close TermFlow?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            launch_installer(Path(path))
            QApplication.quit()


def main():
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
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
