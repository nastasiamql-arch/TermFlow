from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from termflow.core.search_batch import SearchAggregation


class ConflictResolutionDialog(QDialog):
    """Require one explicit, whole-row choice for each conflicting CN."""

    def __init__(self, aggregation: SearchAggregation, parent=None):
        super().__init__(parent)
        self.setWindowTitle("เลือกผลที่ซ้ำหรือขัดแย้ง")
        self.resize(760, 560)
        self.aggregation = aggregation
        self.choices: dict[str, int] = {}
        self.selectors: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("พบ CN ที่มีหลายผลจากช่วงต่าง ๆ เลือกหนึ่งแถวทั้งแถวสำหรับแต่ละ CN"))
        form = QFormLayout()
        for conflict in aggregation.conflicts:
            selector = QComboBox()
            for index, candidate in enumerate(conflict.candidates):
                category = "NEW" if candidate.category == "new" else "UPDATE"
                row = " · ".join(candidate.row)
                chunks = ", ".join(map(str, candidate.chunk_indices))
                selector.addItem(f"{category} | {row} | ช่วง {chunks}", index)
            self.selectors[conflict.cn] = selector
            form.addRow(QLabel(conflict.cn), selector)
        scroll_content = QWidget()
        scroll_content.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("ใช้ผลที่เลือก")
        buttons.button(QDialogButtonBox.Cancel).setText("ยกเลิกและค้นหาใหม่ภายหลัง")
        buttons.accepted.connect(self.accept_choices)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_choices(self):
        self.choices = {cn: selector.currentData() for cn, selector in self.selectors.items()}
        self.accept()
