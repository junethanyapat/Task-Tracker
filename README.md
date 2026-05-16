# 📋 ระบบตามงาน — LINE Task Tracker

ระบบ assign งานให้น้องผ่าน Web แล้วส่ง reminder อัตโนมัติผ่าน LINE OA จนกว่าน้องจะกดส่งงาน

---

## ขั้นตอน Setup ทั้งหมด

### ขั้นที่ 1 — สร้าง LINE Official Account (ฟรี)

1. ไปที่ https://manager.line.biz → สร้าง Official Account ใหม่
2. เลือก **Messaging API** (ไม่ใช่ LINE@ Basic)
3. ไปที่ **Settings → Messaging API → Issue Channel Access Token**
4. Copy **Channel Access Token** และ **Channel Secret** เก็บไว้

### ขั้นที่ 2 — Deploy บน Railway (ฟรี)

1. ไปที่ https://railway.app → สมัคร/เข้าสู่ระบบ
2. กด **New Project → Deploy from GitHub repo**
3. เลือก repo นี้ (ต้อง push ขึ้น GitHub ก่อน)
4. Railway จะ detect `Procfile` และ deploy อัตโนมัติ
5. ไปที่ **Settings → Domains** → copy URL ของ app

### ขั้นที่ 3 — ตั้งค่า Environment Variables ใน Railway

ไปที่ Variables tab แล้วเพิ่ม:

| Key | Value |
|-----|-------|
| `BASE_URL` | URL ของ app จาก Railway เช่น `https://my-app.railway.app` |
| `LINE_CHANNEL_ACCESS_TOKEN` | จากขั้นที่ 1 |
| `LINE_CHANNEL_SECRET` | จากขั้นที่ 1 |
| `BOSS_LINE_USER_ID` | (ดูวิธีหาด้านล่าง) |

### ขั้นที่ 4 — หา BOSS_LINE_USER_ID

1. Add LINE OA ของตัวเองเป็นเพื่อน
2. ส่งข้อความอะไรก็ได้ไปหา OA
3. ดู Railway logs → จะเห็น userId ใน webhook event
   - หรือใช้ tool เช่น https://developers.line.biz/console/ → webhook test

### ขั้นที่ 5 — ตั้งค่า Webhook ใน LINE

1. ไปที่ LINE Developers Console → Messaging API → Webhook settings
2. ใส่ Webhook URL: `https://your-app.railway.app/webhook`
3. กด **Verify** → ต้องได้ Success
4. เปิด **Use webhook: ON**

### ขั้นที่ 6 — เพิ่มน้องเข้าระบบ

1. เปิด app → กด **👥 จัดการน้อง** → เพิ่มชื่อน้อง
2. ระบบจะสร้างรหัส 8 ตัว เช่น `A3F9K2M1`
3. ส่งรหัสนั้นให้น้อง
4. น้อง **Add LINE OA** → พิมพ์รหัสในแชท
5. ระบบจะแจ้ง "ลงทะเบียนสำเร็จ" และสถานะน้องจะเปลี่ยนเป็น **✓ เชื่อมแล้ว**

---

## วิธีใช้งานหลัง Setup

1. เปิด `https://your-app.railway.app`
2. กด **มอบหมายงานใหม่**
3. กรอกชื่องาน, เลือกน้อง, ตั้งกี่ชั่วโมง
4. กด **ส่งงานให้น้อง**
5. น้องจะรับข้อความใน LINE พร้อมปุ่มลิงก์
6. ระบบตามทุก X ชั่วโมงอัตโนมัติ
7. น้องกด **ส่งงานแล้ว** → ระบบหยุดตาม → แจ้งเจ้านายทาง LINE

---

## Environment Variables สรุป

```
BASE_URL                   = https://xxx.railway.app
LINE_CHANNEL_ACCESS_TOKEN  = xxxxxx...
LINE_CHANNEL_SECRET        = xxxxxx...
BOSS_LINE_USER_ID          = Uxxxxxx...  (optional แต่แนะนำ)
```

---

## Tech Stack

- **Backend**: Python 3.11 + FastAPI
- **Database**: SQLite (ฝังใน server)
- **Scheduler**: Python threading loop (ตรวจทุก 1 นาที)
- **LINE**: Messaging API (Push Message + Webhook)
- **Hosting**: Railway free tier
