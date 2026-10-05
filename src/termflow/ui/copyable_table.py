from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTableWidget


def format_selected_cells(cells: list[tuple[int, int, str]], first_data_column: int = 0) -> str:
    """Format selected table cells as a rectangular TSV block."""
    values = {(row, column): text for row, column, text in cells if column >= first_data_column}
    if not values:
        return ""

    rows = range(min(row for row, _column in values), max(row for row, _column in values) + 1)
    columns = range(min(column for _row, column in values), max(column for _row, column in values) + 1)
    return "\n".join(
        "\t".join(values.get((row, column), "") for column in columns)
        for row in rows
    )


class CopyableTableWidget(QTableWidget):
    def __init__(self, rows=0, columns=0, *, first_data_column=0, parent=None):
        super().__init__(rows, columns, parent)
        self.first_data_column = first_data_column
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setToolTip("ลากเลือกช่องที่ต้องการ แล้วกด Ctrl+C เพื่อคัดลอกเป็น TSV")

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            cells = [
                (index.row(), index.column(), str(index.data() or ""))
                for index in self.selectionModel().selectedIndexes()
            ]
            value = format_selected_cells(cells, self.first_data_column)
            if value:
                QApplication.clipboard().setText(value)
                event.accept()
                return
        super().keyPressEvent(event)
