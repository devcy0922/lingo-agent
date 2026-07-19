import json
import unittest
from unittest.mock import patch

import httpx
import translate


class TranslationScopeTests(unittest.TestCase):
    def test_changed_missing_only_and_existing_translation_preserved(self):
        source = {"a": "같음", "b": "변경", "c": "추가"}
        base = {"a": "같음", "b": "이전"}
        existing = {"a": "Human translation", "b": "Old translation"}

        scope = translate.plan_translation(source, existing, base)

        self.assertEqual({("b",), ("c",)}, scope.selected)
        self.assertEqual({("a",)}, scope.preserved)

        review = translate.QualityReview(
            "PASSED",
            100,
            "통과",
            [
                {
                    "key": "b",
                    "semantic_accuracy": 5,
                    "naturalness": 5,
                    "terminology": 5,
                    "ui_fit": 5,
                    "critical_errors": [],
                    "critique": "",
                },
                {
                    "key": "c",
                    "semantic_accuracy": 5,
                    "naturalness": 5,
                    "terminology": 5,
                    "ui_fit": 5,
                    "critical_errors": [],
                    "critique": "",
                },
            ],
        )
        with patch.object(
            translate,
            "translate_with_llm",
            return_value=(json.dumps({"b": "Changed", "c": "Added"}), False),
        ), patch.object(translate, "evaluate_quality", return_value=review):
            result = translate.run_pipeline(
                json.dumps(source),
                "en-US",
                existing_content=json.dumps(existing),
                base_source_content=json.dumps(base),
            )

        self.assertTrue(result.success)
        self.assertEqual("Human translation", json.loads(result.content)["a"])
        self.assertEqual("Changed", json.loads(result.content)["b"])
        self.assertEqual("Added", json.loads(result.content)["c"])

    def test_sync_all_requires_explicit_flag(self):
        source = {"a": "원문"}
        existing = {"a": "Existing"}
        self.assertFalse(translate.plan_translation(source, existing).selected)
        self.assertEqual(
            {("a",)}, translate.plan_translation(source, existing, sync_all=True).selected
        )


class QualityGateTests(unittest.TestCase):
    def test_qa_unavailable_never_succeeds(self):
        scope = translate.TranslationScope(selected={("title",)})
        result = translate.TranslationResult("en-US", scope)
        result.lint_passed = True
        result.glossary_passed = True
        result.qa_status = "UNAVAILABLE"
        self.assertFalse(result.success)

    def test_reviewer_covers_every_key_in_batches(self):
        source = {f"key{i}": f"원문 {i}" for i in range(9)}
        target = {f"key{i}": f"Translation {i}" for i in range(9)}
        responses = []
        for keys in ([f"key{i}" for i in range(8)], ["key8"]):
            responses.append(
                json.dumps(
                    {
                        "results": [
                            {
                                "key": key,
                                "semantic_accuracy": 5,
                                "naturalness": 5,
                                "terminology": 5,
                                "ui_fit": 5,
                                "critical_errors": [],
                                "critique": "",
                            }
                            for key in keys
                        ]
                    }
                )
            )

        with patch.object(translate, "_chat_completion", side_effect=responses) as call:
            review = translate.evaluate_quality(
                json.dumps(source), json.dumps(target), "en-US"
            )

        self.assertEqual("PASSED", review.status)
        self.assertEqual(9, len(review.results))
        self.assertEqual(2, call.call_count)

    def test_reviewer_retries_invalid_schema(self):
        valid = json.dumps(
            {
                "results": [
                    {
                        "key": "title",
                        "semantic_accuracy": 5,
                        "naturalness": 5,
                        "terminology": 5,
                        "ui_fit": 5,
                        "critical_errors": [],
                        "critique": "",
                    }
                ]
            }
        )
        with patch.object(
            translate,
            "_chat_completion",
            side_effect=['{"score": 100}', valid],
        ) as call:
            review = translate.evaluate_quality(
                json.dumps({"title": "제목"}),
                json.dumps({"title": "Title"}),
                "en-US",
            )

        self.assertEqual("PASSED", review.status)
        self.assertEqual(2, call.call_count)

    def test_glossary_rejects_known_bad_translations(self):
        glossary = {
            "preserve": [],
            "entries": [
                {
                    "source": "장애 우회",
                    "targets": {"en-US": "failover"},
                    "forbidden": {"en-US": ["failure bypass"]},
                },
                {
                    "source": "재현 가능한",
                    "targets": {"ja-JP": "再現可能な"},
                    "forbidden": {"ja-JP": ["生再現可能な"]},
                },
            ],
        }
        en_ok, _ = translate.validate_glossary(
            {"evidence": "장애 우회 증거"},
            {"evidence": "Failure Bypass Evidence"},
            "en-US",
            glossary,
        )
        ja_ok, _ = translate.validate_glossary(
            {"delivery": "재현 가능한 배포"},
            {"delivery": "生再現可能なデプロイ"},
            "ja-JP",
            glossary,
        )
        self.assertFalse(en_ok)
        self.assertFalse(ja_ok)

    def test_english_required_term_is_case_insensitive(self):
        glossary = {
            "preserve": [],
            "entries": [
                {
                    "source": "감사 신호",
                    "targets": {"en-US": "audit events"},
                    "forbidden": {},
                }
            ],
        }
        ok, message = translate.validate_glossary(
            {"audit": "감사 신호를 기록"},
            {"audit": "Record Audit Events"},
            "en-US",
            glossary,
        )
        self.assertTrue(ok, message)

    def test_chat_completion_retries_rate_limit(self):
        request = httpx.Request("POST", "https://gateway.example/chat/completions")
        limited = httpx.Response(429, request=request, headers={"Retry-After": "1"})
        success = httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "{\"ok\": true}"}}]},
        )
        client = unittest.mock.MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = [limited, success]

        with patch.object(translate, "LLM_GATEWAY_URL", "https://gateway.example"), patch.object(
            translate.httpx, "Client", return_value=client
        ), patch.object(translate.time, "sleep") as sleep:
            content = translate._chat_completion("auto", [], 128)

        self.assertEqual('{"ok": true}', content)
        self.assertEqual(2, client.post.call_count)
        sleep.assert_called_once_with(1.0)


if __name__ == "__main__":
    unittest.main()
