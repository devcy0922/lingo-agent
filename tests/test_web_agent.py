import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from database import Base  # noqa: E402
from models import Job, Translation  # noqa: E402
import agent  # noqa: E402
from main import healthz  # noqa: E402


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_health_readback_includes_service_identity():
    response = healthz()

    assert response["status"] == "ok"
    assert response["service"] == "lingo-agent"
    assert response["version"]
    assert response["git_sha"]


def test_nested_json_fallback_preserves_shape_and_variables():
    source = {"home": {"welcome": "{username}님, 환영합니다!"}}
    fallback = agent.simulate_fallback_translation(json.dumps(source), "en-US")

    assert json.loads(fallback) == {"home": {"welcome": "[EN] {username}, 환영합니다!"}}
    assert agent.lint_translation(json.dumps(source), fallback) == (True, "Passed")


def test_llm_failure_is_unavailable_instead_of_passing(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kwargs: FailingClient())

    score, critique, status = asyncio.run(
        agent.evaluate_quality_with_llm("{}", "{}", "en-US")
    )

    assert (score, status) == (-1, "UNAVAILABLE")
    assert "판정하지 못했습니다" in critique


def test_fallback_job_becomes_degraded(monkeypatch):
    async def fallback_translation(*args, **kwargs):
        return '{"title":"[EN] 제목"}', True

    monkeypatch.setattr(agent, "translate_with_llm", fallback_translation)
    db = make_session()
    db.add(
        Job(
            id="job-1",
            target_langs=["en-US"],
            source_content='{"title":"제목"}',
        )
    )
    db.commit()

    asyncio.run(agent.run_lingo_agent_loop("job-1", db))

    job = db.query(Job).filter(Job.id == "job-1").one()
    translation = db.query(Translation).filter(Translation.job_id == "job-1").one()
    assert job.status == "DEGRADED"
    assert translation.is_fallback is True
    assert translation.qa_status == "UNAVAILABLE"
    assert translation.quality_score == -1
