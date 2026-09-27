from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autosign.auto_sign import AutoSignService, SHANGHAI_TZ, UserRuntimeState
from autosign.iclass_client import IClassApiError
from autosign.models import ClassSession


class RuntimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.service = AutoSignService()
        self.service.close()
        self.client = Mock()
        self.course = ClassSession(
            schedule_id="course-1",
            course_id="course",
            course_name="软件工程",
            teacher="教师",
            start_time=datetime.now(SHANGHAI_TZ) - timedelta(minutes=1),
            end_time=datetime.now(SHANGHAI_TZ) + timedelta(hours=1),
            raw_status="0",
        )
        self.client.get_week_schedule.return_value = [self.course]
        self.state = UserRuntimeState(client=self.client)
        self.state.week_sessions = {self.course.key: self.course}
        self.service.users["token"] = self.state

    def sign(self):
        return self.service._do_sign(
            self.state,
            self.course.schedule_id,
            reason="签到",
            session_key=self.course.key,
        )

    def test_status_zero_without_sign_confirmation_is_not_success(self):
        for response in (
            {"STATUS": 0},
            {"STATUS": "0", "result": {}},
            {"STATUS": 0, "result": {"stuSignStatus": 0}},
            {"STATUS": 1, "result": {"stuSignStatus": 1}},
        ):
            with self.subTest(response=response):
                self.client.sign_now.return_value = response
                self.assertFalse(self.sign()["ok"])
                self.assertNotIn(self.course.key, self.state.completed_sign_keys)
        self.client.get_week_schedule.assert_not_called()

    def test_all_supported_status_types_require_confirmation(self):
        for status in (0, "0", 200, "200", "success"):
            with self.subTest(status=status):
                self.client.sign_now.return_value = {
                    "STATUS": status,
                    "result": {"stuSignStatus": "1"},
                }
                self.assertTrue(self.sign()["ok"])
                self.assertIn(self.course.key, self.state.completed_sign_keys)

    def test_confirmed_sign_survives_followup_schedule_failure(self):
        self.client.sign_now.return_value = {"STATUS": "0", "result": {"stuSignStatus": 1}}
        self.client.get_week_schedule.side_effect = IClassApiError("查询暂时不可用")
        self.assertTrue(self.sign()["ok"])
        self.assertIn(self.course.key, self.state.completed_sign_keys)
        row = self.service.get_week_sessions("token")[0]
        self.assertEqual(row["attendance"], "已签到（待同步）")
        self.assertEqual(row["rawStatus"], "0")
        self.assertIn("暂未同步", self.state.events[-1].message)
        self.assertFalse(self.service.manual_sign("token", self.course.key, None)["ok"])
        self.assertEqual(self.client.sign_now.call_count, 1)

    def test_server_attendance_is_not_replaced_by_local_clock(self):
        self.client.sign_now.return_value = {"STATUS": 0, "result": {"stuSignStatus": 1}}
        self.course.raw_status = "1"
        self.assertTrue(self.sign()["ok"])
        self.assertEqual(self.service.get_week_sessions("token")[0]["rawStatus"], "1")
        self.assertEqual(self.course.raw_status, "1")

    def test_manual_sign_uses_clients_fresh_timestamp_path(self):
        self.client.sign_now.return_value = {"STATUS": 0, "result": {"stuSignStatus": 1}}
        self.assertTrue(self.service.manual_sign("token", self.course.key, None)["ok"])
        self.client.get_adjusted_timestamp_ms.assert_not_called()
        self.client.sign_now.assert_called_once_with("course-1")
        self.assertEqual(self.course.raw_status, "0")

    def test_failed_initial_sync_does_not_register_background_user(self):
        self.client.get_week_schedule.side_effect = IClassApiError("课表查询失败")
        with self.assertRaises(IClassApiError):
            self.service.register_user("new-token", self.client)
        self.assertNotIn("new-token", self.service.users)


class LoginRouteRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app

        cls.module = app
        app.service.close()
        app.app.config.update(TESTING=True)

    def test_initial_sync_failure_returns_login_error_instead_of_http_500(self):
        with patch.object(self.module, "IClassClient") as client_type, patch.object(
            self.module, "service"
        ) as service:
            service.register_user.side_effect = IClassApiError("首次课表同步失败")
            browser = self.module.app.test_client()
            response = browser.post(
                "/login",
                data={"student_id": "test-id", "password": "test-password", "verify_ssl": "on"},
            )
            self.assertEqual(response.status_code, 302)
            with browser.session_transaction() as session:
                self.assertIn("首次课表同步失败", session["login_error"])
                self.assertNotIn("runtime_token", session)
                self.assertNotIn("password", session["login_form"])
            client_type.return_value.session.close.assert_called_once()

    def test_relogin_unregisters_previous_runtime_after_success(self):
        with patch.object(self.module, "IClassClient") as client_type, patch.object(
            self.module, "service"
        ) as service:
            client_type.return_value.login.return_value.user_name = "测试用户"
            browser = self.module.app.test_client()
            with browser.session_transaction() as session:
                session["runtime_token"] = "old-token"
            response = browser.post(
                "/login",
                data={"student_id": "test-id", "password": "test-password", "verify_ssl": "on"},
            )
            self.assertEqual(response.status_code, 302)
            service.unregister_user.assert_called_once_with("old-token")
            with browser.session_transaction() as session:
                self.assertNotEqual(session["runtime_token"], "old-token")


if __name__ == "__main__":
    unittest.main()
