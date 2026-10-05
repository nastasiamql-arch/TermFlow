# TermFlow

**Glossary Extraction & Polish Workbench** สำหรับช่วยจัดการศัพท์งานนิยายจีน → ไทย โดยผู้ใช้เป็นผู้ตรวจ แก้ และคัดลอกผลลัพธ์ด้วยตนเอง

> TermFlow 1.0.0 สำหรับ Windows x64

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

## Screenshots

ยังไม่มีภาพหน้าจอสำหรับรุ่นนี้

## Installation

ดาวน์โหลด `TermFlow-Setup-x64.exe` จาก GitHub Releases แล้วเรียกใช้ installer แบบ user-level ซึ่งติดตั้งค่าเริ่มต้นใต้ `%LOCALAPPDATA%\Programs\TermFlow` ไม่ต้องใช้สิทธิ์ Administrator

Release installer จะเผยแพร่จาก GitHub Actions เมื่อมีการ push tag รูปแบบ `v*` ที่ตรงกับเวอร์ชันแอป

## First Run

1. เปิด Settings แล้วตั้ง Provider, API Key และ Model
2. เปิด VOCAB (แอปอ่านอย่างเดียว)
3. เปิด SOURCE หรือวางข้อความ
4. Run Search แล้วตรวจ/เลือก NEW rows
5. เลือกศัพท์และส่งไป Polish
6. ตรวจผลสุดท้ายและ Copy TSV ไปวางด้วยตนเอง

## AI API Setup

Settings รองรับ OpenAI, Anthropic, Google Gemini และ OpenAI-compatible service โดยค่าที่จำเป็นแตกต่างกันตามผู้ให้บริการ กรอก API key ใน Settings; key จะเก็บผ่าน keyring แยกจาก `settings.json` ส่วน local-compatible endpoint สามารถใช้ Base URL ของบริการได้

## Search Workflow

STEP A ใช้ `prompts/search/vocab_extractor_v3.md` ซึ่งนำเข้าจากไฟล์ต้นฉบับ `a หาศัพท์.md` โดยคงไบต์เดิมไว้ ตรวจผลให้มี section คำศัพท์ใหม่และคำศัพท์อัปเดตตามรูปแบบ TSV 4 คอลัมน์

## Polish Workflow

ส่งเฉพาะ NEW rows ที่เลือกผ่าน adapter ในรูป CN, TH, NOTE; SEX จะถูกพักไว้และคืนตาม CN หลังตรวจ STEP B สำเร็จ ไม่ส่ง UPDATE ไปโดยอัตโนมัติ

## Update App

ปุ่ม Check for Updates ตรวจ release stable ล่าสุดจาก GitHub และดาวน์โหลด installer พร้อมตรวจ SHA-256 เมื่อ release มีไฟล์ checksum ก่อนเปิด installer จะถามยืนยันทุกครั้ง ไม่มีการดาวน์โหลดหรือติดตั้งอัตโนมัติ

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

อัปเดต `src/termflow/version.py` และ `installer/TermFlow.iss` ให้ตรงกัน จากนั้น push annotated tag เช่น `v1.0.0` workflow จะรันทดสอบ สร้าง installer, SHA-256 และ GitHub Release

## Troubleshooting

- **Prompt not found:** ตรวจว่าโฟลเดอร์ `prompts/` ถูกติดตั้ง/รวมใน package
- **Request failed:** ตรวจอินเทอร์เน็ต, API key, Model และ provider quota
- **No models listed:** ป้อน Model ID เองสำหรับ provider ที่ไม่รองรับ model listing
- **Installer build failed:** ติดตั้ง Inno Setup 6 และตรวจว่าคำสั่ง `ISCC.exe` ใช้งานได้
