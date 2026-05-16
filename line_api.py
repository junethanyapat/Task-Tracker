import os
import requests

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def push_message(to: str, messages: list) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[LINE] No token set — skipping push")
        return False
    if not to:
        print("[LINE] No recipient userId — skipping push")
        return False
    try:
        resp = requests.post(
            PUSH_URL,
            json={"to": to, "messages": messages},
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[LINE] Push failed: {resp.status_code} {resp.text}")
        return resp.status_code == 200
    except Exception as e:
        print(f"[LINE] Push error: {e}")
        return False


def send_task_message(to: str, title: str, confirm_url: str, description: str = "", is_reminder: bool = False) -> bool:
    prefix = "🔔 ยังรอส่งงานอยู่นะคะ" if is_reminder else "📋 มีงานใหม่มาแล้วค่ะ"

    # Build text (max 160 chars for buttons template without title)
    body = f"{title}"
    if description:
        body = f"{title}\n{description}"
    text = f"{prefix}\n{body}"[:160]

    message = {
        "type": "template",
        "altText": text,
        "template": {
            "type": "buttons",
            "text": text,
            "actions": [
                {
                    "type": "uri",
                    "label": "✅ ส่งงานแล้ว",
                    "uri": confirm_url,
                }
            ],
        },
    }
    return push_message(to, [message])


def send_text_message(to: str, text: str) -> bool:
    return push_message(to, [{"type": "text", "text": text}])
