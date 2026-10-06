from threading import Event

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from termflow.core.search_batch import SearchBatch
from termflow.core.search_coordinator import SearchCoordinator


class MultiSearchWorker(QObject):
    progress = Signal(int, str, str, int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, batch, prompt, vocab, config, api_key):
        super().__init__()
        self.batch, self.prompt, self.vocab = batch, prompt, vocab
        self.config, self.api_key = config, api_key
        self.coordinator = None
        self.cancel_requested = Event()

    def run(self):
        try:
            self.coordinator = SearchCoordinator(
                self.batch,
                prompt=self.prompt,
                vocab=self.vocab,
                config=self.config,
                api_key=self.api_key,
                on_progress=lambda *args: self.progress.emit(*args),
            )
            if self.cancel_requested.is_set():
                self.coordinator.cancel()
            self.finished.emit(self.coordinator.run())
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.cancel_requested.set()
        if self.coordinator:
            self.coordinator.cancel()


class SearchProgressDialog(QDialog):
    cancel_requested = Signal()
    retry_requested = Signal()

    LABELS = {
        "pending": "รอทำงาน",
        "running": "กำลังค้นหา",
        "validating": "กำลังตรวจ",
        "retrying": "กำลังลองใหม่",
        "complete": "เสร็จแล้ว",
        "failed": "ผิดพลาด",
        "cancelled": "ยกเลิก",
    }

    def __init__(self, parent=None, chunk_count=3):
        super().__init__(parent)
        self.chunk_count = chunk_count
        self.setWindowTitle(f"ค้นหาศัพท์ {chunk_count} ช่วง")
        self.setMinimumSize(660, 440)
        self.setModal(False)
        layout = QVBoxLayout(self)
        self.summary = QLabel("เตรียมเริ่มค้นหา…")
        layout.addWidget(self.summary)
        self.table = QTableWidget(chunk_count, 5)
        self.table.setHorizontalHeaderLabels(["ช่วง", "สถานะ", "NEW", "UPDATE", "รายละเอียด"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row in range(chunk_count):
            for col, value in enumerate((str(row + 1), "รอทำงาน", "0", "0", "")):
                self.table.setItem(row, col, QTableWidgetItem(value))
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.retry = QPushButton("ลองช่วงที่ผิดพลาดอีกครั้ง")
        self.retry.setEnabled(False)
        self.close_button = QPushButton("ยกเลิก")
        self.retry.clicked.connect(self.retry_requested.emit)
        self.close_button.clicked.connect(self._close_or_cancel)
        buttons.addWidget(self.retry)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.active = True

    def update_chunk(self, index, status, message, new_count, update_count):
        row = index - 1
        self.table.item(row, 1).setText(self.LABELS.get(status, status))
        self.table.item(row, 2).setText(str(new_count))
        self.table.item(row, 3).setText(str(update_count))
        self.table.item(row, 4).setText(message)
        self.refresh_summary()

    def refresh_summary(self, batch: SearchBatch | None = None):
        if batch is None:
            statuses = [self.table.item(row, 1).text() for row in range(self.chunk_count)]
            completed = statuses.count(self.LABELS["complete"])
            failed = statuses.count(self.LABELS["failed"])
        else:
            completed = batch.completed_count
            failed = sum(run.status.value == "failed" for run in batch.runs)
        self.summary.setText(f"เสร็จ {completed}/{self.chunk_count} ช่วง · ผิดพลาด {failed} ช่วง")
        self.retry.setEnabled(not self.active and failed > 0)

    def set_batch(self, batch):
        for run in batch.runs:
            self.update_chunk(run.chunk.index, run.status.value, run.error, len(run.new_rows), len(run.update_rows))
        self.active = False
        self.close_button.setText("ปิด")
        self.refresh_summary(batch)

    def set_active(self, active):
        self.active = active
        self.close_button.setText("ยกเลิก" if active else "ปิด")
        if active:
            self.retry.setEnabled(False)

    def _close_or_cancel(self):
        if self.active:
            self.cancel_requested.emit()
        else:
            self.close()

    def closeEvent(self, event):
        if self.active:
            self.cancel_requested.emit()
            event.ignore()
            return
        event.accept()
