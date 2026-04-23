from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


ATTENDANCE_MAP = {
    "1": "正常出勤",
    "2": "迟到签到",
    "0": "未签到",
}


@dataclass
class ClassSession:
    schedule_id: str
    course_id: str
    course_name: str
    teacher: str
    start_time: datetime
    end_time: datetime
    raw_status: str = "0"

    @property
    def attendance(self) -> str:
        return ATTENDANCE_MAP.get(str(self.raw_status), "未签到")

    @property
    def key(self) -> str:
        return f"{self.schedule_id}::{self.start_time.isoformat()}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "scheduleId": self.schedule_id,
            "courseId": self.course_id,
            "courseName": self.course_name,
            "teacher": self.teacher,
            "startTime": self.start_time.isoformat(),
            "endTime": self.end_time.isoformat(),
            "attendance": self.attendance,
            "rawStatus": str(self.raw_status),
        }
