import unittest

import server


class ServerBehaviorTests(unittest.TestCase):
    def test_fallback_response_includes_reports_and_risk(self):
        reports = [
            {"restaurant": "Crisp Bites", "concern": "Food poisoning", "severity": "High", "status": "pending"},
            {"restaurant": "Noodle House", "concern": "Cold storage", "severity": "Medium", "status": "pending"},
        ]
        answer = server.build_fallback_response(
            "Summarize the current food safety risk",
            reports,
            [{"name": "Crisp Bites", "score": 64}, {"name": "Noodle House", "score": 61}],
        )
        self.assertIn("Crisp Bites", answer)
        self.assertIn("Food poisoning", answer)
        self.assertIn("High", answer)


if __name__ == "__main__":
    unittest.main()
