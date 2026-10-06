from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class PolishRemovalReview(QDialog):
    """No omission becomes final until the user explicitly approves it."""

    def __init__(self, excluded, raw, retained_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ตรวจศัพท์ที่ AI ตัดออกก่อน Copy")
        self.resize(1050, 750)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"ส่งเข้าเกลา {retained_count + len(excluded)} แถว · เหลือ {retained_count} แถว · AI ไม่คืน {len(excluded)} แถว\n"
            "ตรวจศัพท์ด้านล่างและเหตุผลในคำตอบ AI หากไม่เห็นเหตุผลชัดเจน ให้กลับไปเกลาใหม่"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        table = QTableWidget(len(excluded), 4)
        table.setHorizontalHeaderLabels(["CN ที่ถูกตัด", "TH เดิม", "SEX", "NOTE เดิม"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for index, row in enumerate(excluded):
            for column, field in enumerate(("cn", "th", "sex", "note")):
                table.setItem(index, column, QTableWidgetItem(row[field]))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        layout.addWidget(QLabel("คำตอบเต็มของ AI · ใช้ตรวจเหตุผลที่ตัดศัพท์"))
        response = QPlainTextEdit(raw)
        response.setReadOnly(True)
        layout.addWidget(response, 2)
        self.approval = QCheckBox("ตรวจแล้ว และยืนยันให้ตัดเฉพาะรายการข้างต้นออกจากผลเกลา")
        layout.addWidget(self.approval)
        buttons = QHBoxLayout()
        back = QPushButton("ไม่ยืนยัน · กลับไปเกลาใหม่")
        self.confirm = QPushButton("ยืนยันรายการที่ตัดและแสดง Final Result")
        self.confirm.setEnabled(False)
        self.approval.toggled.connect(self.confirm.setEnabled)
        self.confirm.clicked.connect(self.accept)
        back.clicked.connect(self.reject)
        buttons.addWidget(back)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)

    def accept(self):
        if self.approval.isChecked():
            super().accept()
