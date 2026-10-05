from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


class _LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_number_area(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.editor.begin_line_gutter_drag(event.position().toPoint().y())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.editor.extend_line_gutter_drag(event.position().toPoint().y())
            event.accept()

    def mouseReleaseEvent(self, event):
        self.editor.leave_line_gutter_drag()
        super().mouseReleaseEvent(event)


class CopyableTableWidget(QPlainTextEdit):
    """Editable TSV view with VS Code-like text selection and row selection gutter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_lines: set[int] = set()
        self._drag_line = None
        self._drag_target_state = None
        self._line_number_area = _LineNumberArea(self)
        self._base_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.set_text_point_size(12)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setPlaceholderText("ยังไม่มีรายการ")
        self.setStyleSheet(
            "QPlainTextEdit { background: #1e1e1e; color: #d4d4d4; "
            "selection-background-color: #264f78; selection-color: #ffffff; "
            "border: 1px solid #3c3c3c; padding: 7px; }"
        )
        self.setToolTip(
            "ลากเลือกข้อความแล้วกด Ctrl+C เพื่อคัดลอกเหมือน VS Code · "
            "คลิกแถบเลขบรรทัดเพื่อเลือกศัพท์สำหรับ Polish"
        )
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.textChanged.connect(self._on_text_changed)
        self.update_line_number_area_width()

    def line_number_area_width(self):
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits + 14

    def update_line_number_area_width(self, *_args):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_number_area(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#252526"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_rect = QRect(0, top, self._line_number_area.width(), self.fontMetrics().height())
                line_index = block.blockNumber()
                if line_index in self._selected_lines:
                    painter.fillRect(line_rect, QColor("#264f78"))
                    painter.setPen(QColor("#4fc1ff"))
                    painter.drawText(1, top, 13, line_rect.height(), Qt.AlignCenter, "✓")
                else:
                    painter.setPen(QColor("#858585"))
                painter.drawText(
                    14,
                    top,
                    self._line_number_area.width() - 17,
                    line_rect.height(),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def _line_at(self, y):
        point = self._line_number_area.mapTo(self.viewport(), QPoint(0, y))
        return self.cursorForPosition(point).blockNumber()

    def begin_line_gutter_drag(self, y):
        line = self._line_at(y)
        if line in self._selected_lines:
            self._selected_lines.remove(line)
            self._drag_target_state = False
        else:
            self._selected_lines.add(line)
            self._drag_target_state = True
        self._drag_line = line
        self._apply_line_highlights()
        self._line_number_area.update()

    def extend_line_gutter_drag(self, y):
        line = self._line_at(y)
        if self._drag_line == line:
            return
        if self._drag_target_state:
            self._selected_lines.add(line)
        else:
            self._selected_lines.discard(line)
        self._drag_line = line
        self._apply_line_highlights()
        self._line_number_area.update()

    def leave_line_gutter_drag(self):
        self._drag_line = None
        self._drag_target_state = None

    def _on_text_changed(self):
        count = self.blockCount()
        self._selected_lines = {line for line in self._selected_lines if line < count}
        self._apply_line_highlights()
        self._line_number_area.update()

    def _apply_line_highlights(self):
        selections = []
        color = QColor("#293b4d")
        for line in sorted(self._selected_lines):
            block = self.document().findBlockByNumber(line)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.setPosition(block.position())
            selections.append(selection)
        self.setExtraSelections(selections)

    def fill_rows(self, rows):
        self.blockSignals(True)
        self.setPlainText("\n".join("\t".join(str(value) for value in row) for row in rows))
        self._selected_lines = set(range(len(rows)))
        self.blockSignals(False)
        self.update_line_number_area_width()
        self._apply_line_highlights()
        self._line_number_area.update()

    def clear(self):
        self._selected_lines.clear()
        self._drag_line = None
        self._drag_target_state = None
        super().clear()
        self._line_number_area.update()

    def all_rows(self):
        rows = []
        block = self.document().begin()
        while block.isValid():
            line = block.text()
            if line.strip():
                rows.append(line.split("\t"))
            block = block.next()
        return rows

    def selected_rows(self):
        rows = []
        block = self.document().begin()
        while block.isValid():
            index = block.blockNumber()
            line = block.text()
            if line.strip() and index in self._selected_lines:
                rows.append(line.split("\t"))
            block = block.next()
        return rows

    def row_count(self):
        return len(self.all_rows())

    def select_all_rows(self, selected):
        self._selected_lines = set(range(self.blockCount())) if selected else set()
        self._apply_line_highlights()
        self._line_number_area.update()

    def set_text_point_size(self, size):
        font = self._base_font
        font.setPointSize(size)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.update_line_number_area_width()
        self._line_number_area.update()
