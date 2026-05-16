import os
import uuid
import hmac
import hashlib
import base64
import json
import threading
import time
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from database import (
    init_db, get_all_tasks, get_all_staff, get_staff_by_id,
    get_task_by_token, create_task, mark_done, get_due_tasks,
    update_next_remind, add_staff, update_staff_line_id,
    increment_reminder_count, cancel_task,
)
from line_api import send_task_message, send_text_message

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL              = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
LINE_CHANNEL_SECRET   = os.getenv("LINE_CHANNEL_SECRET", "")
BOSS_LINE_USER_ID     = os.getenv("BOSS_LINE_USER_ID", "")

app = FastAPI(title="Task Tracker")
templates = Jinja2Templates(directory="templates")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    init_db()
    t = threading.Thread(target=reminder_loop, daemon=True)
    t.start()
    print("[App] Started. Reminder loop running.")


# ── Background reminder loop ──────────────────────────────────────────────────
def reminder_loop():
    while True:
        try:
            for task in get_due_tasks():
                staff = get_staff_by_id(task["assigned_to"])
                if staff and staff.get("line_user_id"):
                    confirm_url = f"{BASE_URL}/confirm/{task['confirm_token']}"
                    send_task_message(
                        to=staff["line_user_id"],
                        title=task["title"],
                        confirm_url=confirm_url,
                        description=task.get("description", ""),
                        is_reminder=True,
                    )
                    increment_reminder_count(task["id"])
                # Advance next reminder time
                next_remind = datetime.now() + timedelta(hours=task["interval_hours"])
                update_next_remind(task["id"], next_remind)
        except Exception as e:
            print(f"[Reminder] Error: {e}")
        time.sleep(60)  # check every minute


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    tasks = get_all_tasks()
    staff = get_all_staff()
    pending = [t for t in tasks if t["status"] == "pending"]
    done    = [t for t in tasks if t["status"] == "done"]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "tasks": tasks,
        "staff": staff,
        "pending_count": len(pending),
        "done_count": len(done),
    })


# ── Create task ───────────────────────────────────────────────────────────────
@app.get("/create", response_class=HTMLResponse)
async def create_form(request: Request):
    staff = get_all_staff()
    registered = [s for s in staff if s.get("line_user_id")]
    return templates.TemplateResponse("create.html", {
        "request": request,
        "staff": registered,
    })


@app.post("/tasks")
async def create_task_route(
    title: str        = Form(...),
    description: str  = Form(""),
    assigned_to: int  = Form(...),
    interval_hours: float = Form(...),
):
    token = str(uuid.uuid4())
    confirm_url = f"{BASE_URL}/confirm/{token}"

    create_task(title, description, assigned_to, interval_hours, token)

    # Send first LINE message immediately
    staff = get_staff_by_id(assigned_to)
    if staff and staff.get("line_user_id"):
        send_task_message(
            to=staff["line_user_id"],
            title=title,
            confirm_url=confirm_url,
            description=description,
            is_reminder=False,
        )

    return RedirectResponse("/", status_code=302)


# ── Cancel task ───────────────────────────────────────────────────────────────
@app.post("/tasks/{task_id}/cancel")
async def cancel_task_route(task_id: int):
    cancel_task(task_id)
    return RedirectResponse("/", status_code=302)


# ── Staff management ──────────────────────────────────────────────────────────
@app.get("/staff", response_class=HTMLResponse)
async def staff_page(request: Request):
    staff = get_all_staff()
    return templates.TemplateResponse("staff.html", {
        "request": request,
        "staff": staff,
        "base_url": BASE_URL,
    })


@app.post("/staff")
async def add_staff_route(name: str = Form(...)):
    reg_code = str(uuid.uuid4())[:8].upper()
    add_staff(name, reg_code)
    return RedirectResponse("/staff", status_code=302)


# ── น้อง Confirm ──────────────────────────────────────────────────────────────
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

    if task["status"] != "done":
        mark_done(task["id"])
        # Notify boss via LINE
        if BOSS_LINE_USER_ID:
            staff = get_staff_by_id(task["assigned_to"])
            name = staff["name"] if staff else "น้อง"
            when = datetime.now().strftime("%d/%m %H:%M")
            msg = f"✅ {name} ส่งงานแล้วค่ะ!\n📋 {task['title']}\n🕐 {when}"
            send_text_message(BOSS_LINE_USER_ID, msg)

    return RedirectResponse(f"/confirm/{token}/done", status_code=302)


@app.get("/confirm/{token}/done", response_class=HTMLResponse)
async def confirm_done(request: Request, token: str):
    task = get_task_by_token(token)
    return templates.TemplateResponse("done.html", {"request": request, "task": task})


# ── LINE Webhook (น้อง registration) ─────────────────────────────────────────
def verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        return True  # skip verification in dev
    digest = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    sig  = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    staff_list = get_all_staff()

    for event in data.get("events", []):
        if event.get("type") == "message" and event["message"]["type"] == "text":
            line_user_id = event["source"]["userId"]
            text = event["message"]["text"].strip().upper()

            # Match registration code
            for staff in staff_list:
                if staff.get("reg_code") == text and not staff.get("line_user_id"):
                    update_staff_line_id(staff["id"], line_user_id)
                    send_text_message(
                        line_user_id,
                        f"✅ ลงทะเบียนสำเร็จแล้วค่ะ!\nสวัสดี {staff['name']} 😊\nระบบจะส่งงานมาให้ที่นี่นะคะ",
                    )
                    break

    return JSONResponse({"status": "ok"})


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
