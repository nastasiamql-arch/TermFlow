# TermFlow

**Glossary Extraction & Polish Workbench** สำหรับช่วยจัดการศัพท์งานนิยายจีน → ไทย โดยผู้ใช้เป็นผู้ตรวจ แก้ และคัดลอกผลลัพธ์ด้วยตนเอง

> TermFlow 1.1.4 สำหรับ Windows x64

## Features

- รองรับ SOURCE `.txt` / `.md` และ VOCAB `.txt` / `.tsv` แบบ UTF-8/BOM
- VOCAB เปิดอ่านอย่างเดียว ไม่มีการเขียนทับหรือ merge
- โหลด Prompt ต้นฉบับจาก `prompts/` และส่งข้อความเดิมเป็น system prompt
- ตรวจโครงสร้าง STEP A และ STEP B ก่อนส่งต่อ
- adapter ส่งเฉพาะ NEW ที่เลือกไป STEP B และเก็บ SEX กลับตาม CN
- OpenAI, Anthropic, Gemini และ OpenAI-compatible provider
- เก็บ API key ผ่าน keyring/Windows Credential Manager
- เก็บประวัติ local พร้อม exact prompt snapshot และ raw response
- ตรวจ GitHub Releases และเปรียบเทียบเวอร์ชัน
- สร้างโปรไฟล์ต่อเรื่องเพื่อจำไฟล์ SOURCE/VOCAB, จำนวนช่วงค้นหา และ Prompt ที่เลือก
- ตรวจจับไฟล์ที่ถูกแก้จากโปรแกรมอื่น โหลดเนื้อหาใหม่ และแจ้งเมื่อผลเดิมล้าสมัย
- พื้นที่รายการศัพท์ใช้สีตามธีม ตัวอักษรใหญ่ขึ้น ลากเลือกข้อความแบบ VS Code และกด Ctrl+C เพื่อคัดลอก
- ปรับขนาดตัวอักษรได้ใน Settings และเปิดหน้าต่างหลักแบบเต็มจอ
- แบ่ง SOURCE ได้ 1–20 ช่วง และค้นหาพร้อมกัน โดยใช้ Prompt A เดิมทุกคำ (ค่าเริ่มต้น 1 คำขอ สำหรับ SOURCE ไม่เกิน 16,000 ตัวอักษร)
- แสดงสถานะแยกแต่ละช่วง จำนวน NEW/UPDATE และเหตุผลเมื่อช่วงใดทำไม่สำเร็จ
- ลองใหม่เฉพาะช่วงที่ล้มเหลว หรือยกเลิกคำขอที่กำลังทำงานได้
- หากหมดเวลารอ จะหยุดและให้เลือก Retry เอง ไม่มีการแบ่งเป็นคำขอเพิ่มอัตโนมัติ และค่าเริ่มต้น Retries = 0
- รวมผลที่ตรวจผ่านเป็นชุดเดียว ตัดแถวซ้ำจากบริเวณเหลื่อม และให้ผู้ใช้เลือกเมื่อ CN เดียวกันได้หลายผล
- บันทึกผลค้นหารวมเป็นไฟล์ UTF-8 ไฟล์เดียว โดย SOURCE และ VOCAB ยังคงอ่านอย่างเดียว

## Screenshots

ยังไม่มีภาพหน้าจอสำหรับรุ่นนี้

## Installation

ดาวน์โหลด `TermFlow-Setup-x64.exe` จาก GitHub Releases แล้วเรียกใช้ installer แบบ user-level ซึ่งติดตั้งค่าเริ่มต้นใต้ `%LOCALAPPDATA%\Programs\TermFlow` ไม่ต้องใช้สิทธิ์ Administrator

Release installer จะเผยแพร่จาก GitHub Actions เมื่อมีการ push tag รูปแบบ `v*` ที่ตรงกับเวอร์ชันแอป

## First Run

1. เปิด Settings แล้วตั้ง Provider, API Key และ Model
2. เปิด VOCAB (แอปอ่านอย่างเดียว)
3. เปิด SOURCE หรือวางข้อความ
4. กด Run Search โปรแกรมจะส่ง SOURCE ทั้งหมดเป็นหนึ่งคำขอโดยค่าเริ่มต้นและแสดงความคืบหน้า หากบางช่วงล้มเหลว กดลองเฉพาะช่วงนั้นซ้ำได้
5. เมื่อครบทุกช่วง โปรแกรมรวมผลที่ผ่าน validation ให้ตรวจ/เลือก NEW rows หากพบ CN ที่ผลไม่ตรงกัน ให้เลือกหนึ่งแถวที่ต้องการ
6. เลือกศัพท์ NEW แล้วกด Send Selected NEW to Polish
7. ตรวจผลสุดท้ายและ Copy TSV ไปวางด้วยตนเอง หรือกดบันทึกผลรวมเป็นไฟล์ข้อความ

## AI API Setup

Settings รองรับ OpenAI, Anthropic, Google Gemini และ OpenAI-compatible service โดยค่าที่จำเป็นแตกต่างกันตามผู้ให้บริการ กรอก API key ใน Settings; key จะเก็บผ่าน keyring แยกจาก `settings.json` สำหรับ OpenAI-compatible ให้ใส่ Base URL ของบริการ/Pool; TermFlow จะใช้ route `/v1` สำหรับ chat และ model listing โดยอัตโนมัติ หาก provider ปิดการ list models ให้กรอก Model ID เอง

## Search Workflow

STEP A ใช้ `prompts/search/vocab_extractor_v3.md` ซึ่งนำเข้าจากไฟล์ต้นฉบับ `a หาศัพท์.md` โดยคงเนื้อหา Prompt เดิมไว้ โปรแกรมส่ง Prompt A ฉบับเดิม, VOCAB (ถ้ามี) และส่วนของ SOURCE ที่แบ่งไว้ให้แต่ละคำขอ ทุกคำขอต้องผ่าน strict validator ก่อนรวมผล

แต่ละช่วงใช้บริบทเหลื่อมใกล้ขอบเขตเล็กน้อยเพื่อไม่ตัดศัพท์ที่อยู่ตรงรอยแบ่ง โปรแกรมตัดเฉพาะแถวที่เหมือนกันทุกช่องซึ่งเกิดซ้ำจากบริเวณเหลื่อม ส่วนแถว CN เดียวกันที่มีข้อมูลต่างกันจะแสดงหน้าต่างให้ผู้ใช้เลือกทั้งแถว ไม่มีการผสมหรือเขียนทับข้อมูลให้อัตโนมัติ ผลจะใช้ได้เมื่อทุกช่วงผ่าน validation ครบเท่านั้น

ค่าเริ่มต้นคือ 1 ช่วง สำหรับ SOURCE ไม่เกิน 16,000 ตัวอักษร และไม่มีการแบ่งย่อยหลัง Timeout โดยอัตโนมัติ หากเลือกหลายช่วงใน Settings จะส่งหลายคำขอและส่ง Prompt/VOCAB ซ้ำตามจำนวนช่วง เก็บผลช่วงที่ผ่านไว้เพื่อ Retry เฉพาะช่วงที่ล้มเหลวได้ การอัปเกรดจากรุ่นก่อนจะตั้ง 1 ช่วง และ Retries = 0 ให้ครั้งเดียว คุณสามารถเปลี่ยนภายหลังได้

## โปรไฟล์นิยายและไฟล์ที่เปลี่ยน

กด **โปรไฟล์นิยาย** เพื่อสร้าง เปลี่ยนชื่อ ลบ หรือสลับเรื่อง โปรไฟล์จำ path ของ SOURCE/VOCAB, จำนวนช่วงค้นหา และ Prompt ที่เลือกไว้ เมื่อเปิดโปรแกรมครั้งต่อไป TermFlow จะเปิดไฟล์ของโปรไฟล์ล่าสุดให้อัตโนมัติ หากย้ายไฟล์ ให้เลือกไฟล์ใหม่ผ่านปุ่ม Open SOURCE หรือ Open VOCAB

TermFlow เฝ้าดูไฟล์ที่เลือกไว้ เมื่อไฟล์ถูกบันทึกจากแอปอื่น โปรแกรมจะโหลดเนื้อหาล่าสุดและทำเครื่องหมายผลค้นหาเดิมว่าล้าสมัย ต้องค้นหาใหม่ก่อนส่งศัพท์ไปเกลา หากมีข้อความ SOURCE ที่แก้ในหน้าจอแต่ยังไม่บันทึก โปรแกรมจะถามก่อนว่าจะโหลดไฟล์ล่าสุดหรือเก็บข้อความในหน้าจอไว้ ระหว่าง API ทำงาน คำขอจะใช้ snapshot เดิมจนจบ แล้วจึงอัปเดตไฟล์ในหน้าจอ

## Polish Workflow

ส่งเฉพาะ NEW rows ที่เลือกผ่าน adapter ในรูป CN, TH, NOTE; SEX จะถูกพักไว้และคืนตาม CN หลังตรวจ STEP B สำเร็จ ไม่ส่ง UPDATE ไปโดยอัตโนมัติ โปรแกรมแยก TSV จาก code block ตามรูปแบบของ Prompt B แล้วตรวจจำนวนแถว, CN, TH, NOTE ก่อนแสดงผล

## เปลี่ยน Prompt และ Model

แถบด้านบนมี **Prompt หาศัพท์** และ **Prompt เกลา** พร้อมปุ่ม **เลือกไฟล์แทนของเดิม** เลือก `.md`, `.txt`, `.docx` ได้โดยตรง เปลี่ยนครั้งเดียวทุกโปรไฟล์ใช้ชุดเดียวกัน โปรแกรมจำ path และอ่านเนื้อหาจากไฟล์ล่าสุดก่อนรันทุกครั้ง ไม่คัดลอกเป็น Prompt แยกตามเรื่องและไม่เขียนทับไฟล์ Prompt ถ้าไฟล์ถูกย้าย/ลบ จะแจ้งให้เลือกใหม่ ไม่กลับไปใช้ Prompt เก่าโดยเงียบ ๆ

`.docx` ดึงข้อความย่อหน้า TAB และขึ้นบรรทัดใหม่ (ไม่เก็บรูปแบบตัวอักษรและรูปภาพ) History เก็บข้อความ Prompt ที่ส่งจริงเป็น snapshot รอบเก่าจึงไม่เปลี่ยนตามไฟล์ สำหรับผู้ที่ต้องการจัดการ custom Prompt ในโปรแกรม ยังมี Prompt Manager; กด Select เพื่อใช้แทนไฟล์ที่เลือก Built-in แก้ได้ผ่าน Duplicate เท่านั้น

Prompt ใหม่ต้องยังให้ข้อมูลตามสัญญาของแต่ละโหมด: หาศัพท์มี NEW/UPDATE และ 4 คอลัมน์ ส่วนเกลาเป็น TSV 3 คอลัมน์ CN/TH/NOTE รับหัวข้อผลลัพธ์ TSV ตาม Prompt เดิม, หัวข้อ COPY-READY TSV หรือ TSV ล้วน ไม่มีการเปลี่ยนคำสั่ง Prompt ให้เอง

Settings มี **Model หาศัพท์** และ **Model เกลา** ถ้าปล่อยว่างจะใช้ Default Model ทั้งสองใช้ Provider/Base URL/API Key ที่ตั้งไว้ เกลาส่งเฉพาะ NEW ที่เลือกและ VOCAB โดยไม่ส่ง SOURCE ทั้งเรื่องซ้ำ

## ลดค่าใช้จ่าย API

เมื่อข้อมูล, Prompt, Model และ Base URL เหมือนเดิม โปรแกรมใช้ผลที่ผ่าน strict validation จาก cache ในเครื่องได้ ไม่เสีย API เพิ่ม ปิด **ใช้ผลเดิม** ใน Settings เพื่อขอผลใหม่ Cache อยู่ที่ `%LOCALAPPDATA%\TermFlow\result-cache` และลบโฟลเดอร์นี้ได้เมื่อไม่มีงานรัน ผลที่ไม่ผ่านจะไม่ถูกเก็บ และตรวจซ้ำทุกครั้งที่อ่าน Cache

History เก็บ token usage ที่ API คืนมาและระบุว่าใช้ผลเดิมหรือไม่ ข้อมูล token ไม่ใช่ยอดเงินของ MaxPlus และไม่รับประกันว่าเส้นทาง API ของคุณรองรับส่วนลด prompt caching จำนวน SOURCE 16,000 ตัวอักษรไม่รวม Prompt/VOCAB; หากเกิน context ของ Model ผู้ให้บริการจะปฏิเสธคำขอ ให้เลือก Model ที่มีขีดจำกัดเหมาะสม

## Update App

ปุ่ม Check for Updates ตรวจ release stable ล่าสุดจาก GitHub และดาวน์โหลด installer พร้อมตรวจ SHA-256 เมื่อ release มีไฟล์ checksum หลังโหลดให้กด **Install and Close TermFlow** แล้วตัวติดตั้ง Windows จะแสดงขึ้นมาให้ทำตามขั้นตอน ไม่มีการติดตั้งอัตโนมัติ

## Privacy / Security

- API keys ไม่อยู่ใน settings หรือ history; ใช้ระบบ keyring ของ OS
- SOURCE/VOCAB ถูกส่งไปยัง AI provider ที่ผู้ใช้เลือกเมื่อเรียกใช้งาน
- VOCAB ถูกอ่านเข้าหน่วยความจำเท่านั้น
- History อยู่ใน `%APPDATA%\TermFlow\history`
- หลีกเลี่ยงการใส่ข้อมูลส่วนตัวลงใน SOURCE หากไม่ต้องการส่งให้ provider

## Build From Source

ต้องมี Windows, Python 3.12+ และ Inno Setup 6

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
powershell -ExecutionPolicy Bypass -File scripts/package.ps1
```

ผลลัพธ์คือ `dist/TermFlow.exe` และ `installer/output/TermFlow-Setup-x64.exe`

## Release Process

อัปเดต `src/termflow/version.py`, `pyproject.toml` และค่า fallback ใน `installer/TermFlow.iss` ให้ตรงกัน จากนั้น push annotated tag ตามรุ่น เช่น `v1.1.5` workflow จะรันทดสอบ สร้าง installer, SHA-256 และ GitHub Release

## Troubleshooting

- **Prompt not found:** ตรวจว่าโฟลเดอร์ `prompts/` ถูกติดตั้ง/รวมใน package
- **Request failed:** ตรวจอินเทอร์เน็ต, API key, Model และ provider quota
- **No models listed:** ป้อน Model ID เองสำหรับ provider ที่ไม่รองรับ model listing
- **Installer build failed:** ติดตั้ง Inno Setup 6 และตรวจว่าคำสั่ง `ISCC.exe` ใช้งานได้
