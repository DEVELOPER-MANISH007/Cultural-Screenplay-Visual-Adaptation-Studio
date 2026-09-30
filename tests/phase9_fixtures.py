from __future__ import annotations

from pathlib import Path

from test_screenplay_adapter import RAW, evidence_pack, make_change, make_plan, sample_state
from app.models.adaptation import AdaptationCategory
from app.models.screenplay import ScreenplayDocument, SourceType
from app.models.visual_generation import VisualAssetType, VisualGenerationStatus
from app.services.screenplay_adapter import adapt_screenplay
from app.services.visual_artifact_store import VisualArtifactStore
from app.services.visual_generation_planner import create_visual_generation_batch
from app.services.visual_generation_service import VisualGenerationService, set_request_review_status
from app.services.visual_pack_generator import MockVisualPackGenerator
from app.services.image_generation_provider import MockImageGenerationProvider


def complete_fixture(tmp_path: Path, *, generate_visual: bool = True):
    state = sample_state()
    cultural, evidence = evidence_pack(tmp_path / "culture")
    plan = make_plan([make_change("CHANGE_APPROVED", status="approved", category=AdaptationCategory.COSTUME,
                                 target_type="character", target_id="CHAR_001", evidence_ids=["EVID_005"])])
    adapted = adapt_screenplay(state, plan, evidence, RAW)
    pack = MockVisualPackGenerator().generate(state, adapted, plan, evidence)
    batch = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
    data_root = tmp_path / "data"
    if generate_visual:
        request = next(r for r in batch.requests if r.asset_type == VisualAssetType.CHARACTER)
        batch = set_request_review_status(batch, request.request_id, VisualGenerationStatus.APPROVED)
        fresh = create_visual_generation_batch(pack, state, adapted, plan, cultural_evidence=evidence)
        batch = VisualGenerationService(MockImageGenerationProvider(), VisualArtifactStore(data_root)).generate_approved(
            batch, fresh.requests, pack, state)
        VisualArtifactStore(data_root).save_batch(batch)
    source = ScreenplayDocument(document_id=state.screenplay_id, filename="ravi_meena.txt",
                                source_type=SourceType.PASTED_TEXT, raw_text=RAW,
                                character_count=len(RAW), word_count=len(RAW.split()))
    return state, plan, adapted, pack, batch, evidence, cultural.list_sources(), source, data_root
