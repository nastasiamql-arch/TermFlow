from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout


class ResponseEditor(QDialog):
    """Edit a response copy locally; retain the immutable provider response."""

    def __init__(self, raw, validator, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ตรวจและแก้ผลเดิม · ไม่เรียก API")
        self.resize(1100, 750)
        self.validator = validator
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("แก้เฉพาะผลใน workspace · ไม่มีการแก้ SOURCE / VOCAB · ไม่เสีย API เพิ่ม"))
        tabs = QTabWidget()
        self.editor = QPlainTextEdit(raw)
        original = QPlainTextEdit(raw)
        original.setReadOnly(True)
        tabs.addTab(self.editor, "ผลที่แก้ไขได้")
        tabs.addTab(original, "คำตอบ AI ต้นฉบับ")
        layout.addWidget(tabs)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        apply = QPushButton("ตรวจซ้ำและใช้ผลนี้ · ไม่เรียก API")
        apply.clicked.connect(self.check)
        cancel = QPushButton("ปิด")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(apply)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def check(self):
        try:
            self.validator(self.editor.toPlainText())
        except Exception as exc:
            self.error.setText(str(exc))
            return
        self.accept()
