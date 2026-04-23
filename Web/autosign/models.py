from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


ATTENDANCE_MAP = {
    "1": "正常出勤",
    "2": "迟到",
    "0": "未出勤",
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
        return ATTENDANCE_MAP.get(str(self.raw_status), "未出勤")

    @property
    def key(self) -> str:
        # 兼容“同一个 schedule_id 在不同日期重复出现”的情况
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


@dataclass
class PromptNotification:
    key: str
    schedule_id: str
    course_name: str
    start_time: datetime
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "scheduleId": self.schedule_id,
            "courseName": self.course_name,
            "startTime": self.start_time.isoformat(),
            "createdAt": self.created_at.isoformat(),
        }


@dataclass
class RuntimeEvent:
    level: str
    message: str
    at: datetime
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "message": self.message,
            "at": self.at.isoformat(),
            "meta": self.meta,
        }
