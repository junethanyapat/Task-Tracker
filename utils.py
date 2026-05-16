from datetime import datetime, timedelta, time as dt_time
import pytz

THAI_TZ   = pytz.timezone('Asia/Bangkok')
WORK_START = dt_time(9, 0)
WORK_END   = dt_time(18, 0)


def thai_now() -> datetime:
    """เวลาปัจจุบันในโซนเวลาไทย (naive datetime)"""
    return datetime.now(THAI_TZ).replace(tzinfo=None)


def is_work_time(dt: datetime) -> bool:
    """
    True ถ้า dt อยู่ในเวลาทำงาน: จ-ศ 09:00-18:00 และไม่ใช่วันหยุดนักขัตฤกษ์
    dt ต้องเป็น naive datetime ในโซนเวลาไทย
    """
    # Import here to avoid circular import at module level
    from database import is_holiday

    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if dt.time() < WORK_START or dt.time() >= WORK_END:
        return False
    if is_holiday(dt.date()):
        return False
    return True


def next_work_start(from_dt: datetime) -> datetime:
    """
    คืน 09:00 ของวันทำงานถัดไป (ข้ามเสาร์-อาทิตย์ และวันหยุดนักขัตฤกษ์)
    ถ้า from_dt ยังไม่ถึง 09:00 ในวันทำงาน → คืน 09:00 ของวันนั้น
    ถ้า from_dt ผ่าน 09:00 แล้ว → คืน 09:00 วันทำงานถัดไป
    """
    from database import is_holiday

    candidate = from_dt.replace(hour=9, minute=0, second=0, microsecond=0)

    # ถ้าถึงหรือเกิน 09:00 แล้ว ย้ายไปวันถัดไป
    if from_dt.time() >= WORK_START:
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    # ข้ามเสาร์-อาทิตย์ และวันหยุด
    while candidate.weekday() >= 5 or is_holiday(candidate.date()):
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    return candidate


def calc_next_remind(from_dt: datetime, interval_hours: float) -> datetime:
    """
    คำนวณเวลา reminder ถัดไป
    - from_dt + interval_hours
    - ถ้าผลลัพธ์ตกนอกเวลาทำงาน → ดันไปเป็น 09:00 วันทำงานถัดไป
    """
    from database import is_holiday

    candidate = from_dt + timedelta(hours=interval_hours)

    if not is_work_time(candidate):
        # ถ้ายังไม่ถึง 09:00 ในวันทำงาน → ใช้ 09:00 วันนั้น
        day_start = candidate.replace(hour=9, minute=0, second=0, microsecond=0)
        if (candidate.time() < WORK_START
                and candidate.weekday() < 5
                and not is_holiday(candidate.date())):
            return day_start
        # กรณีอื่น → วันทำงานถัดไป
        return next_work_start(candidate)

    return candidate
