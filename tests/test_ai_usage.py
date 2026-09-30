from __future__ import annotations
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from phase9_fixtures import complete_fixture
from app.services.final_validator import validate_final_project
from app.services.production_exporter import build_package


def test_usage_log_distinguishes_offline_mock_and_not_external_calls(tmp_path):
    state, plan, adapted, pack, batch, evidence, sources, source, root = complete_fixture(tmp_path)
    validation = validate_final_project(project_state=state, source_screenplay=source, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        cultural_evidence=evidence, cultural_sources=sources)
    package, usage, limitations, _ = build_package(project_state=state, adaptation_plan=plan,
        adapted_screenplay=adapted, visual_pack=pack, generation_batch=batch,
        evidence=evidence, sources=sources, validation=validation, data_root=root)
    assert package.project_id == state.project_id
    assert all(not record.network_used for record in usage.records)
    assert any("mock" in record.mode for record in usage.records)
    assert any("Marwari" in item.detail for item in limitations.items)
    assert any("cinematic" in item.detail for item in limitations.items)
