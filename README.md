# TermFlow

**Glossary Extraction & Polish Workbench** สำหรับช่วยจัดการศัพท์งานนิยายจีน → ไทย โดยผู้ใช้เป็นผู้ตรวจ แก้ และคัดลอกผลลัพธ์ด้วยตนเอง

> TermFlow 1.1.3 สำหรับ Windows x64

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
- พื้นที่รายการศัพท์ธีมเข้ม ตัวอักษรใหญ่ขึ้น ลากเลือกข้อความแบบ VS Code และกด Ctrl+C เพื่อคัดลอก
- ปรับขนาดตัวอักษรได้ใน Settings
- แบ่ง SOURCE ได้ 1–20 ช่วง และค้นหาพร้อมกัน โดยใช้ Prompt A เดิมทุกคำ (ค่าเริ่มต้น 3 ช่วง เหมาะกับ SOURCE ราว 25,000 ตัวอักษร)
- แสดงสถานะแยกแต่ละช่วง จำนวน NEW/UPDATE และเหตุผลเมื่อช่วงใดทำไม่สำเร็จ
- ลองใหม่เฉพาะช่วงที่ล้มเหลว หรือยกเลิกคำขอที่กำลังทำงานได้
- หากคำขอของช่วงใดหมดเวลารอ โปรแกรมจะแบ่งเฉพาะ SOURCE ช่วงนั้นเป็นส่วนย่อยและตรวจผลแต่ละส่วนก่อนรวม โดยไม่ส่งช่วงที่สำเร็จแล้วซ้ำ
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
4. กด Run Search โปรแกรมจะแบ่ง SOURCE เป็น 3 ช่วงโดยค่าเริ่มต้นและแสดงความคืบหน้า หากบางช่วงล้มเหลว กดลองเฉพาะช่วงนั้นซ้ำได้
5. เมื่อครบทุกช่วง โปรแกรมรวมผลที่ผ่าน validation ให้ตรวจ/เลือก NEW rows หากพบ CN ที่ผลไม่ตรงกัน ให้เลือกหนึ่งแถวที่ต้องการ
6. เลือกศัพท์ NEW แล้วกด Send Selected NEW to Polish
7. ตรวจผลสุดท้ายและ Copy TSV ไปวางด้วยตนเอง หรือกดบันทึกผลรวมเป็นไฟล์ข้อความ

## AI API Setup

Settings รองรับ OpenAI, Anthropic, Google Gemini และ OpenAI-compatible service โดยค่าที่จำเป็นแตกต่างกันตามผู้ให้บริการ กรอก API key ใน Settings; key จะเก็บผ่าน keyring แยกจาก `settings.json` สำหรับ OpenAI-compatible ให้ใส่ Base URL ของบริการ/Pool; TermFlow จะใช้ route `/v1` สำหรับ chat และ model listing โดยอัตโนมัติ หาก provider ปิดการ list models ให้กรอก Model ID เอง

## Search Workflow

STEP A ใช้ `prompts/search/vocab_extractor_v3.md` ซึ่งนำเข้าจากไฟล์ต้นฉบับ `a หาศัพท์.md` โดยคงเนื้อหา Prompt เดิมไว้ โปรแกรมส่ง Prompt A ฉบับเดิม, VOCAB (ถ้ามี) และส่วนของ SOURCE ที่แบ่งไว้ให้แต่ละคำขอ ทุกคำขอต้องผ่าน strict validator ก่อนรวมผล

แต่ละช่วงใช้บริบทเหลื่อมใกล้ขอบเขตเล็กน้อยเพื่อไม่ตัดศัพท์ที่อยู่ตรงรอยแบ่ง โปรแกรมตัดเฉพาะแถวที่เหมือนกันทุกช่องซึ่งเกิดซ้ำจากบริเวณเหลื่อม ส่วนแถว CN เดียวกันที่มีข้อมูลต่างกันจะแสดงหน้าต่างให้ผู้ใช้เลือกทั้งแถว ไม่มีการผสมหรือเขียนทับข้อมูลให้อัตโนมัติ ผลจะใช้ได้เมื่อทุกช่วงผ่าน validation ครบเท่านั้น

จำนวนช่วงปรับได้ตั้งแต่ 1–20 ช่วงใน Settings พร้อมคำแนะนำขนาด SOURCE โดยประมาณ เช่น 2 ช่วงสำหรับ 10,000–20,000 ตัวอักษร หรือ 3 ช่วงสำหรับ 15,000–30,000 ตัวอักษร (นิยายราว 25,000 ตัวอักษร) จำนวนช่วงมากขึ้นจะแบ่งละเอียดและสร้างหลาย API requests มากขึ้น สำหรับ 10 ช่วงขึ้นไป งานจะทำพร้อมกันสูงสุด 10 คำขอ หากผู้ให้บริการจำกัดคำขอ ช่วงที่ผิดพลาดสามารถกดลองใหม่โดยคงผลของช่วงที่สำเร็จไว้ หากเกิด read timeout โปรแกรมจะแบ่ง SOURCE เฉพาะช่วงที่ช้าและลองส่วนย่อยโดยอัตโนมัติได้สูงสุด 2 ระดับ ทุกส่วนยังใช้ Prompt A และ VOCAB เดิม และต้องผ่าน validator ก่อนนำมารวม

## โปรไฟล์นิยายและไฟล์ที่เปลี่ยน

กด **โปรไฟล์นิยาย** เพื่อสร้าง เปลี่ยนชื่อ ลบ หรือสลับเรื่อง โปรไฟล์จำ path ของ SOURCE/VOCAB, จำนวนช่วงค้นหา และ Prompt ที่เลือกไว้ เมื่อเปิดโปรแกรมครั้งต่อไป TermFlow จะเปิดไฟล์ของโปรไฟล์ล่าสุดให้อัตโนมัติ หากย้ายไฟล์ ให้เลือกไฟล์ใหม่ผ่านปุ่ม Open SOURCE หรือ Open VOCAB

TermFlow เฝ้าดูไฟล์ที่เลือกไว้ เมื่อไฟล์ถูกบันทึกจากแอปอื่น โปรแกรมจะโหลดเนื้อหาล่าสุดและทำเครื่องหมายผลค้นหาเดิมว่าล้าสมัย ต้องค้นหาใหม่ก่อนส่งศัพท์ไปเกลา หากมีข้อความ SOURCE ที่แก้ในหน้าจอแต่ยังไม่บันทึก โปรแกรมจะถามก่อนว่าจะโหลดไฟล์ล่าสุดหรือเก็บข้อความในหน้าจอไว้ ระหว่าง API ทำงาน คำขอจะใช้ snapshot เดิมจนจบ แล้วจึงอัปเดตไฟล์ในหน้าจอ

## Polish Workflow

ส่งเฉพาะ NEW rows ที่เลือกผ่าน adapter ในรูป CN, TH, NOTE; SEX จะถูกพักไว้และคืนตาม CN หลังตรวจ STEP B สำเร็จ ไม่ส่ง UPDATE ไปโดยอัตโนมัติ โปรแกรมแยก TSV จาก code block ตามรูปแบบของ Prompt B แล้วตรวจจำนวนแถว, CN, TH, NOTE ก่อนแสดงผล

## Update App

ปุ่ม Check for Updates ตรวจ release stable ล่าสุดจาก GitHub และดาวน์โหลด installer พร้อมตรวจ SHA-256 เมื่อ release มีไฟล์ checksum หลังโหลดจะเปิดหน้าต่างยืนยันติดตั้งไว้ด้านหน้า ผู้ใช้ต้องกดยืนยันทุกครั้ง ไม่มีการติดตั้งอัตโนมัติ

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

อัปเดต `src/termflow/version.py`, `pyproject.toml` และค่า fallback ใน `installer/TermFlow.iss` ให้ตรงกัน จากนั้น push annotated tag ตามรุ่น เช่น `v1.1.3` workflow จะรันทดสอบ สร้าง installer, SHA-256 และ GitHub Release

## Troubleshooting

- **Prompt not found:** ตรวจว่าโฟลเดอร์ `prompts/` ถูกติดตั้ง/รวมใน package
- **Request failed:** ตรวจอินเทอร์เน็ต, API key, Model และ provider quota
- **No models listed:** ป้อน Model ID เองสำหรับ provider ที่ไม่รองรับ model listing
- **Installer build failed:** ติดตั้ง Inno Setup 6 และตรวจว่าคำสั่ง `ISCC.exe` ใช้งานได้
