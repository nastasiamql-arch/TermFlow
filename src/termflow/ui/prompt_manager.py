from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from termflow.core.prompt_loader import import_prompt_text
from termflow.core.prompts import create_prompt, delete_prompt, list_prompts, save_prompt


class PromptManagerDialog(QDialog):
    def __init__(self, parent=None, category=None):
        super().__init__(parent)
        self.setWindowTitle("Prompt Manager")
        self.resize(850, 600)
        self.category = category
        self.selected_prompt = None
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.category_choice = QComboBox()
        self.category_choice.addItems(["Search", "Polish"])
        self.category_choice.setCurrentText(category or "Search")
        self.category_choice.setEnabled(category is None)
        left.addWidget(QLabel("ประเภท Prompt ใหม่ / นำเข้า"))
        left.addWidget(self.category_choice)
        self.items = QListWidget()
        self.items.currentItemChanged.connect(self.show_item)
        left.addWidget(self.items)
        for text, callback in [
            ("New", self.new_prompt),
            ("นำเข้าไฟล์ Prompt", self.import_prompt),
            ("Duplicate", self.duplicate_prompt),
            ("Rename", self.rename_prompt),
            ("Delete", self.remove_prompt),
            ("Preview", self.preview_prompt),
            ("Select", self.select_prompt),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            left.addWidget(button)
        layout.addLayout(left, 1)
        right = QVBoxLayout()
        self.name = QLabel()
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.save_button = QPushButton("Save custom prompt")
        self.save_button.clicked.connect(self.save_current)
        right.addWidget(self.name)
        right.addWidget(self.content)
        right.addWidget(self.save_button)
        layout.addLayout(right, 3)
        self.refresh()

    def refresh(self, select_id=None):
        self.prompts = [x for x in list_prompts() if not self.category or x["category"] == self.category]
        self.items.clear()
        for prompt in self.prompts:
            item = QListWidgetItem(f"{prompt['name']} · {prompt['category']} · v{prompt['version']}")
            item.setData(256, prompt["id"])
            self.items.addItem(item)
            if prompt["id"] == select_id:
                self.items.setCurrentItem(item)
        self.show_item()

    def current(self):
        prompt_id = self.items.currentItem().data(256) if self.items.currentItem() else None
        return next((x for x in self.prompts if x["id"] == prompt_id), None)

    def show_item(self, *_):
        prompt = self.current()
        if not prompt:
            return
        self.name.setText(
            f"{prompt['name']} · {prompt['category']} · version {prompt['version']}" + (" · built-in" if prompt["is_builtin"] else "")
        )
        self.content.setPlainText(prompt["content"])
        self.content.setReadOnly(prompt["is_builtin"])
        self.save_button.setEnabled(not prompt["is_builtin"])

    def new_prompt(self):
        category = self.category or self.category_choice.currentText()
        name, ok = QInputDialog.getText(self, "New Prompt", "Name")
        if ok and name:
            result = create_prompt(name, category)
            self.refresh(result["id"])

    def import_prompt(self):
        filename, _ = QFileDialog.getOpenFileName(self, "นำเข้า Prompt", "", "Prompt (*.md *.txt *.docx)")
        if not filename:
            return
        try:
            text = import_prompt_text(Path(filename))
            result = create_prompt(Path(filename).stem, self.category or self.category_choice.currentText(), text)
            self.refresh(result["id"])
        except Exception as exc:
            QMessageBox.warning(self, "นำเข้า Prompt ไม่สำเร็จ", str(exc))

    def duplicate_prompt(self):
        prompt = self.current()
        if not prompt:
            return
        name, ok = QInputDialog.getText(self, "Duplicate Prompt", "Name", text=f"{prompt['name']} Copy")
        if ok and name:
            result = create_prompt(name, prompt["category"], prompt["content"])
            self.refresh(result["id"])

    def rename_prompt(self):
        prompt = self.current()
        if not prompt or prompt["is_builtin"]:
            QMessageBox.information(self, "Prompt Manager", "Duplicate a built-in prompt before renaming it.")
            return
        name, ok = QInputDialog.getText(self, "Rename Prompt", "Name", text=prompt["name"])
        if ok and name:
            result = save_prompt(prompt["id"], name=name, content=prompt["content"])
            self.refresh(result["id"])

    def remove_prompt(self):
        prompt = self.current()
        if not prompt or prompt["is_builtin"]:
            QMessageBox.information(self, "Prompt Manager", "Built-in prompts cannot be deleted.")
            return
        if QMessageBox.question(self, "Delete Prompt", f"Delete {prompt['name']}?") == QMessageBox.Yes:
            delete_prompt(prompt["id"])
            self.refresh()

    def preview_prompt(self):
        prompt = self.current()
        if prompt:
            QMessageBox.information(self, prompt["name"], prompt["content"][:10000])

    def select_prompt(self):
        prompt = self.current()
        if prompt:
            if not prompt["is_builtin"] and self.content.toPlainText() != prompt["content"]:
                prompt = save_prompt(prompt["id"], name=prompt["name"], content=self.content.toPlainText())
            if not prompt["content"].strip():
                QMessageBox.warning(self, "Prompt", "Prompt ว่าง กรุณาใส่คำสั่งก่อนเลือก")
                return
            self.selected_prompt = prompt
            self.accept()

    def save_current(self):
        prompt = self.current()
        if not prompt or prompt["is_builtin"]:
            return
        result = save_prompt(prompt["id"], name=prompt["name"], content=self.content.toPlainText())
        self.refresh(result["id"])
