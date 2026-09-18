from __future__ import annotations

import unittest
from unittest.mock import patch

from tongjianyun import director_dashboard


class TestDirectorDashboard(unittest.TestCase):
    def test_attendance_rate_never_goes_negative_and_rounds(self):
        self.assertEqual(director_dashboard._attendance_rate(100, 7, 4), 89.0)
        self.assertEqual(director_dashboard._attendance_rate(3, 4, 2), 0.0)
        self.assertEqual(director_dashboard._attendance_rate(0, 0, 0), 0.0)

    def test_class_snapshot_contains_only_aggregate_fields(self):
        result = director_dashboard._class_snapshot(
            {
                "student_group": "GROUP-1",
                "class_name": "小一班",
                "enrolled_count": 25,
                "absent_count": 3,
                "leave_count": 1,
                "lunch_count": 21,
            }
        )

        self.assertEqual(result["rate"], 84.0)
        self.assertEqual(result["status"], "danger")
        self.assertEqual(result["present"], 21)
        self.assertEqual(
            set(result),
            {
                "student_group",
                "class_name",
                "enrolled",
                "present",
                "lunch",
                "absent",
                "leave",
                "rate",
                "status",
            },
        )

    def test_nutrition_payload_summarizes_management_attention(self):
        result = director_dashboard._nutrition_payload(
            {
                "analysis": {
                    "standard": {"profile": "自动计算"},
                    "nutrient_evaluations": {
                        "energy": {"status": "适宜", "percent": 95.2},
                        "protein": {"status": "适宜", "percent": 101.1},
                        "calcium": {"status": "偏低", "percent": 76.4},
                        "iron": {"status": "偏高", "percent": 128.0},
                    },
                    "conclusion": "钙偏低，铁偏高。",
                }
            }
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["suitable"], 2)
        self.assertEqual(result["total"], 4)
        self.assertEqual([row["label"] for row in result["attention"]], ["钙", "铁"])
        self.assertEqual(result["profile"], "自动计算")

    def test_dashboard_tasks_put_unconfirmed_meal_first(self):
        tasks = director_dashboard._dashboard_tasks(
            {
                "meal_confirmed": False,
                "confirmation": {"name": "MEAL-1"},
                "enrolled": 100,
                "rate": 82.0,
                "classes": [],
            },
            {"recipe": None, "published": False},
            {"draft_count": 1, "unreceived_count": 0},
            {"available": False, "attention": []},
        )

        self.assertEqual(tasks[0]["title"], "今日就餐人数尚未确认")
        self.assertEqual(tasks[0]["priority"], "urgent")
        self.assertTrue(any(task["title"] == "本周食谱尚未编制" for task in tasks))
        self.assertTrue(any(task["title"] == "采购订单尚未全部提交" for task in tasks))

    @patch.object(director_dashboard, "_safe_get_list")
    def test_material_request_scope_is_tongjianyun_recipe_only(self, get_list):
        get_list.return_value = [{"name": "MAT-REQ-1"}]

        self.assertEqual(
            director_dashboard._tongjianyun_material_request_names(),
            ["MAT-REQ-1"],
        )
        filters = get_list.call_args.kwargs["filters"]
        self.assertEqual(filters["title"], ["like", "童健云食谱采购 · %"])
        self.assertEqual(filters["material_request_type"], "Purchase")


if __name__ == "__main__":
    unittest.main()
