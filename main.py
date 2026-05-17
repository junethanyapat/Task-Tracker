import os
import uuid
import hmac
import hashlib
import base64
import json
import re
import threading
import time

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from database import (
    init_db, get_all_tasks, get_all_staff, get_staff_by_id,
    get_task_by_token, create_task, mark_done, get_due_tasks,
    update_next_remind, add_staff, update_staff_line_id,
    increment_reminder_count, cancel_task, mark_escalated,
    mark_first_notified, get_holidays, add_holiday, delete_holiday,
    reset_staff_line_id,
)
from line_api import send_task_message, send_text_message
from utils import thai_now, is_work_time, next_work_start, calc_next_remind

BASE_URL            = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
BOSS_LINE_USER_ID   = os.getenv("BOSS_LINE_USER_ID", "")

app = FastAPI(title="Task Tracker")
templates = Jinja2Templates(directory="templates")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    init_db()
    threading.Thread(target=reminder_loop, daemon=True).start()
    print("[App] Started — reminder loop running (Thai time)")


# ── Reminder loop ─────────────────────────────────────────────────────────────
def reminder_loop():
    while True:
        try:
            now = thai_now()
            if is_work_time(now):
                for task in get_due_tasks(now.isoformat()):
                    process_task_reminder(task, now)
        except Exception as e:
            print(f"[Reminder] Error: {e}")
        time.sleep(60)


def process_task_reminder(task, now):
    staff = get_staff_by_id(task["assigned_to"])

    # ─ ยังไม่ได้ส่งการแจ้งเตือนแรก ─
    if not task["first_notified"]:
        if staff and staff.get("line_user_id"):
            confirm_url = f"{BASE_URL}/confirm/{task['confirm_token']}"
            sent = send_task_message(
                to=staff["line_user_id"],
                title=task["title"],
                confirm_url=confirm_url,
                description=task.get("description", ""),
                is_reminder=False,
            )
            if not sent:
                return  # ส่งไม่ได้ → ลองใหม่รอบหน้า ไม่นับครั้ง
        mark_first_notified(task["id"])
        next_remind = calc_next_remind(now, task["interval_hours"])
        update_next_remind(task["id"], next_remind)
        return

    # ─ ถึง max 3 ครั้งแล้ว → escalate ─
    if task["reminder_count"] >= 3:
        if not task["escalated"]:
            if BOSS_LINE_USER_ID:
                name = staff["name"] if staff else "น้อง"
                msg = (f"⚠️ {name} ยังไม่ส่งงานหลังตาม 3 ครั้งแล้วค่ะ!\n"
                       f"📋 งาน: {task['title']}\n"
                       f"กรุณาติดต่อโดยตรงนะคะ")
                send_text_message(BOSS_LINE_USER_ID, msg)
            mark_escalated(task["id"])
        return

    # ─ ส่ง reminder (เฉพาะถ้าส่งสำเร็จถึงนับครั้ง) ─
    if staff and staff.get("line_user_id"):
        confirm_url = f"{BASE_URL}/confirm/{task['confirm_token']}"
        sent = send_task_message(
            to=staff["line_user_id"],
            title=task["title"],
            confirm_url=confirm_url,
            description=task.get("description", ""),
            is_reminder=True,
        )
        if sent:
            increment_reminder_count(task["id"])
            next_remind = calc_next_remind(now, task["interval_hours"])
            update_next_remind(task["id"], next_remind)
        # ถ้าส่งไม่ได้ → ไม่นับ ไม่เลื่อน next_remind → ลองใหม่รอบหน้า


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks     = get_all_tasks()
    staff     = get_all_staff()
    pending   = [t for t in tasks if t["status"] == "pending"]
    done      = [t for t in tasks if t["status"] == "done"]
    escalated = [t for t in tasks if t["status"] == "escalated"]
    return templates.TemplateResponse("index.html", {
        "request": request, "tasks": tasks, "staff": staff,
        "pending_count": len(pending), "done_count": len(done),
        "escalated_count": len(escalated),
    })


# ── Create task ───────────────────────────────────────────────────────────────
@app.get("/create", response_class=HTMLResponse)
async def create_form(request: Request):
    staff = [s for s in get_all_staff() if s.get("line_user_id")]
    return templates.TemplateResponse("create.html", {"request": request, "staff": staff})


@app.post("/tasks")
async def create_task_route(request: Request):
    form        = await request.form()
    title       = str(form.get("title", "")).strip()
    description = str(form.get("description", ""))
    assigned_to = int(form.get("assigned_to", 0))
    deadline    = str(form.get("deadline", "")) or None

    # รับ interval_hours ได้หลายค่า → เอาค่าแรกที่ไม่ว่าง
    raw_intervals = form.getlist("interval_hours")
    interval_hours = None
    for v in raw_intervals:
        v = str(v).strip()
        if v:
            try:
                interval_hours = float(v)
                break
            except ValueError:
                continue
    if not interval_hours:
        interval_hours = 2.0

    if not title or not assigned_to:
        return RedirectResponse("/create", status_code=302)

    token       = str(uuid.uuid4())
    confirm_url = f"{BASE_URL}/confirm/{token}"
    now         = thai_now()

    if is_work_time(now):
        next_remind      = calc_next_remind(now, interval_hours)
        first_notify_now = True
    else:
        next_remind      = next_work_start(now)
        first_notify_now = False

    task_id = create_task(
        title, description, assigned_to, interval_hours, token,
        next_remind_at=next_remind,
        deadline=deadline,
    )

    if first_notify_now:
        staff = get_staff_by_id(assigned_to)
        if staff and staff.get("line_user_id"):
            sent = send_task_message(
                to=staff["line_user_id"],
                title=title,
                confirm_url=confirm_url,
                description=description,
                is_reminder=False,
            )
            if sent:
                mark_first_notified(task_id)
        # ถ้าส่งไม่ได้ → first_notified ยังเป็น 0 → loop จะลองส่งอีกทีเช้าวันถัดไป

    return RedirectResponse("/", status_code=302)


@app.post("/tasks/{task_id}/cancel")
async def cancel_task_route(task_id: int):
    cancel_task(task_id)
    return RedirectResponse("/", status_code=302)


# ── Staff ─────────────────────────────────────────────────────────────────────
@app.get("/staff", response_class=HTMLResponse)
async def staff_page(request: Request):
    return templates.TemplateResponse("staff.html", {
        "request": request, "staff": get_all_staff(), "base_url": BASE_URL,
    })


@app.post("/staff")
async def add_staff_route(name: str = Form(...)):
    name = name.strip()
    if not name:
        return RedirectResponse("/staff", status_code=302)
    # เช็ค duplicate ชื่อ
    existing = [s for s in get_all_staff() if s["name"] == name]
    if not existing:
        add_staff(name, str(uuid.uuid4())[:8].upper())
    return RedirectResponse("/staff", status_code=302)


@app.post("/staff/{staff_id}/reset")
async def reset_staff_line(staff_id: int):
    reset_staff_line_id(staff_id)
    return RedirectResponse("/staff", status_code=302)


# ── Holidays ──────────────────────────────────────────────────────────────────
@app.get("/holidays", response_class=HTMLResponse)
async def holidays_page(request: Request):
    return templates.TemplateResponse("holidays.html", {
        "request": request, "holidays": get_holidays(),
    })


@app.post("/holidays")
async def add_holiday_route(date: str = Form(...), name: str = Form("")):
    add_holiday(date, name)
    return RedirectResponse("/holidays", status_code=302)


@app.post("/holidays/{holiday_id}/delete")
async def delete_holiday_route(holiday_id: int):
    delete_holiday(holiday_id)
    return RedirectResponse("/holidays", status_code=302)


# ── Confirm ───────────────────────────────────────────────────────────────────
@app.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_page(request: Request, token: str):
    task = get_task_by_token(token)
    if not task:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return templates.TemplateResponse("confirm.html", {"request": request, "task": task})


@app.post("/confirm/{token}")
async def confirm_task(token: str):
    task = get_task_by_token(token)
    if not task:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")

    if task["status"] not in ("done", "cancelled"):
        mark_done(task["id"])
        if BOSS_LINE_USER_ID:
            staff = get_staff_by_id(task["assigned_to"])
            name  = staff["name"] if staff else "น้อง"
            when  = thai_now().strftime("%d/%m %H:%M")
            msg   = f"✅ {name} ส่งงานแล้วค่ะ!\n📋 {task['title']}\n🕐 {when}"
            send_text_message(BOSS_LINE_USER_ID, msg)

    return RedirectResponse(f"/confirm/{token}/done", status_code=302)


@app.get("/confirm/{token}/done", response_class=HTMLResponse)
async def confirm_done(request: Request, token: str):
    return templates.TemplateResponse("done.html", {
        "request": request, "task": get_task_by_token(token),
    })


# ── Webhook ───────────────────────────────────────────────────────────────────
def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        return True
    digest   = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    sig  = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data       = json.loads(body)
    staff_list = get_all_staff()

    for event in data.get("events", []):
        if event.get("type") == "message" and event["message"]["type"] == "text":
            line_user_id = event["source"]["userId"]
            text = event["message"]["text"].strip().upper()

            matched = False
            for staff in staff_list:
                if staff.get("reg_code") == text and not staff.get("line_user_id"):
                    update_staff_line_id(staff["id"], line_user_id)
                    send_text_message(
                        line_user_id,
                        f"✅ ลงทะเบียนสำเร็จแล้วค่ะ!\nสวัสดี {staff['name']} 😊\n"
                        f"ระบบจะส่งงานมาให้ที่นี่นะคะ",
                    )
                    matched = True
                    break

            # รหัสผิด → แจ้งน้อง
            if not matched and re.match(r'^[A-Z0-9]{8}$', text):
                send_text_message(
                    line_user_id,
                    "❌ ไม่พบรหัสนี้ค่ะ\nกรุณาตรวจสอบรหัส 8 หลักและลองใหม่อีกครั้งนะคะ 🙏"
                )

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
