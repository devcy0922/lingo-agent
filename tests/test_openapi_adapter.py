import json
from pathlib import Path
from unittest.mock import patch

import translate
from lingo.adapters.openapi_adapter import (
    OpenApiAdapter,
    _apply_translations,
    _extract_translatable,
    is_openapi_document,
)
from lingo.config import LingoConfig


def _sample_spec():
    return {
        "openapi": "3.1.0",
        "info": {"title": "사용자 API", "description": "사용자 관리 API 입니다."},
        "tags": [{"name": "Users", "description": "사용자 관련 엔드포인트"}],
        "paths": {
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "summary": "사용자 조회",
                    "description": "ID로 단일 사용자를 조회합니다.",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "description": "사용자 식별자",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "조회 성공",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "description": "사용자 정보",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "사용자 이름",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["ACTIVE", "INACTIVE"],
                        },
                    },
                }
            }
        },
    }


def test_extract_translatable_only_pulls_description_summary_title():
    spec = _sample_spec()
    flat = _extract_translatable(spec)

    assert flat[("info", "title")] == "사용자 API"
    assert flat[("info", "description")] == "사용자 관리 API 입니다."
    assert flat[("tags", "0", "description")] == "사용자 관련 엔드포인트"
    assert flat[("paths", "/users/{id}", "get", "summary")] == "사용자 조회"
    assert flat[("paths", "/users/{id}", "get", "description")] == "ID로 단일 사용자를 조회합니다."
    assert (
        flat[("paths", "/users/{id}", "get", "parameters", "0", "description")]
        == "사용자 식별자"
    )
    assert (
        flat[("paths", "/users/{id}", "get", "responses", "200", "description")]
        == "조회 성공"
    )
    assert flat[("components", "schemas", "User", "description")] == "사용자 정보"
    assert (
        flat[("components", "schemas", "User", "properties", "name", "description")]
        == "사용자 이름"
    )

    # 구조적 필드는 절대 뽑히지 않는다
    labels = {".".join(p) for p in flat}
    assert not any("operationId" in label for label in labels)
    assert not any(label.endswith("schema") for label in labels)
    assert not any(label.endswith("$ref") for label in labels)
    assert not any(label.endswith("enum") for label in labels)
    assert not any(label.endswith("parameters.0.name") for label in labels)
    assert not any(label.endswith("properties.status") and "description" not in label for label in labels)


def test_apply_translations_preserves_structure():
    spec = _sample_spec()
    flat = _extract_translatable(spec)
    translated = {path: f"EN::{value}" for path, value in flat.items()}

    result = _apply_translations(spec, translated)

    assert result["info"]["title"] == "EN::사용자 API"
    assert result["paths"]["/users/{id}"]["get"]["operationId"] == "getUser"
    assert result["paths"]["/users/{id}"]["get"]["parameters"][0]["name"] == "id"
    assert result["paths"]["/users/{id}"]["get"]["parameters"][0]["schema"] == {
        "type": "string"
    }
    assert result["components"]["schemas"]["User"]["properties"]["status"]["enum"] == [
        "ACTIVE",
        "INACTIVE",
    ]
    assert (
        result["components"]["schemas"]["User"]["properties"]["name"]["description"]
        == "EN::사용자 이름"
    )
    # 원본은 그대로 남아있어야 한다 (deep copy)
    assert spec["info"]["title"] == "사용자 API"


def test_is_openapi_document_rejects_plain_locale_json(tmp_path):
    locale = tmp_path / "ko.json"
    locale.write_text(json.dumps({"greeting": "안녕"}), encoding="utf-8")
    assert is_openapi_document(locale) is False

    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(_sample_spec(), ensure_ascii=False), encoding="utf-8")
    assert is_openapi_document(spec_path) is True


def test_openapi_adapter_end_to_end(tmp_path):
    spec = _sample_spec()
    source_path = tmp_path / "openapi.json"
    source_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    expected_paths = _extract_translatable(spec)

    def fake_translate_with_llm(source_subset_content, target_lang, feedback, **kwargs):
        parsed = json.loads(source_subset_content)

        def upper(node):
            if isinstance(node, dict):
                return {k: upper(v) for k, v in node.items()}
            return f"EN::{node}"

        return json.dumps(upper(parsed), ensure_ascii=False), False

    review = translate.QualityReview(
        "PASSED",
        100,
        "통과",
        [
            {
                "key": ".".join(path),
                "semantic_accuracy": 5,
                "naturalness": 5,
                "terminology": 5,
                "ui_fit": 5,
                "critical_errors": [],
                "critique": "",
            }
            for path in expected_paths
        ],
    )

    config = LingoConfig(profile=None, target_langs=["en-US"])
    adapter = OpenApiAdapter(config)

    with patch.object(
        translate, "translate_with_llm", side_effect=fake_translate_with_llm
    ), patch.object(translate, "evaluate_quality", return_value=review):
        exit_code = adapter.translate(
            source_path=source_path,
            target_langs=["en-US"],
            output_dir=tmp_path,
            report_path=tmp_path / "lingo-report.json",
        )

    assert exit_code == 0

    output_path = tmp_path / "openapi.en.json"
    assert output_path.exists()
    translated_doc = json.loads(output_path.read_text(encoding="utf-8"))

    assert translated_doc["info"]["title"] == "EN::사용자 API"
    assert translated_doc["paths"]["/users/{id}"]["get"]["operationId"] == "getUser"
    assert translated_doc["paths"]["/users/{id}"]["get"]["parameters"][0]["name"] == "id"
    assert translated_doc["components"]["schemas"]["User"]["properties"]["status"][
        "enum"
    ] == ["ACTIVE", "INACTIVE"]

    cache_path = tmp_path / "openapi.en.i18n.json"
    assert cache_path.exists()
