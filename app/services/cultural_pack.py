"""Small, manually curated starter pack from public Rajasthan government sources."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.cultural_evidence import (
    CulturalEvidence, CulturalEvidenceStatus as Status, CulturalSource,
    CulturalSourceType as SourceType, LanguageEvidence,
)
from app.services.cultural_store import CulturalStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_marwari_marwar_pack(store: CulturalStore, *, save: bool = True) -> CulturalStore:
    """Seed only when empty; do not replace edits or conflicting records."""
    if store.sources or store.evidence:
        return store
    retrieved = _now()
    source_specs = [
        ("SRC_001", "Historic Regions", "https://foundation.rajasthan.gov.in/HistoricRegions.aspx", "Rajasthan Foundation, Government of Rajasthan", "Official state foundation overview; regional statements are limited to what the page explicitly enumerates."),
        ("SRC_002", "Rajasthani Language", "https://foundation.rajasthan.gov.in/RajasthaniLanguage.aspx", "Rajasthan Foundation, Government of Rajasthan", "Official language and culture overview; it names Marwari among Rajasthani varieties but does not provide phrase-level dialect evidence."),
        ("SRC_003", "Jodhpur", "https://www.tourism.rajasthan.gov.in/jodhpur.html", "Department of Tourism, Government of Rajasthan", "Official destination page. Useful for named Jodhpur sites and visitor descriptions; not a comprehensive ethnography."),
        ("SRC_004", "Discovering an All New Side of the Heritage of Jodhpur", "https://www.tourism.rajasthan.gov.in/travel-diaries/donasthan.html", "Department of Tourism, Government of Rajasthan", "Official tourism travel diary about the Marwar Festival; clothing and performance descriptions are festival-context observations, not universal daily dress."),
        ("SRC_005", "Shopping in Rajasthan", "https://www.tourism.rajasthan.gov.in/shopping-in-rajasthan.html", "Department of Tourism, Government of Rajasthan", "Official shopping/craft guide. It names Jodhpur and Salawas for particular textiles and crafts; it does not establish household prevalence."),
        ("SRC_006", "Customs and Rituals", "https://www.tourism.rajasthan.gov.in/customs.html", "Department of Tourism, Government of Rajasthan", "Statewide tourism overview; claims are Rajasthan-general and must not be narrowed to Marwar without local corroboration."),
        ("SRC_007", "Cuisine of Rajasthan", "https://foundation.rajasthan.gov.in/CuisineofRajasthan.aspx", "Rajasthan Foundation, Government of Rajasthan", "Official state-level cuisine overview; ingredients and dishes are Rajasthan-general, not proof of Marwari household practice."),
    ]
    for source_id, title, url, publisher, reliability in source_specs:
        store.add_source(CulturalSource(source_id=source_id, title=title, url=url, publisher=publisher,
                                        source_type=SourceType.GOVERNMENT, region="Rajasthan", culture="Rajasthan",
                                        reliability_notes=reliability, retrieved_at=retrieved))
    def evidence(evidence_id, source_id, *, culture="Marwari", region="Marwar / Jodhpur", category,
                 claim, summary, confidence, scope, status=Status.PARTIALLY_SUPPORTED, notes=None):
        source = store.get_source(source_id)
        store.add_evidence(CulturalEvidence(
            evidence_id=evidence_id, source_id=source_id, culture=culture, dialect=None,
            region=region, category=category, claim=claim, evidence_summary=summary,
            source_title=source.title, source_url=source.url, source_type=source.source_type,
            retrieved_at=retrieved, confidence=confidence, scope=scope, notes=notes, status=status,
        ))
    evidence("EVID_001", "SRC_001", category="regional_context",
             claim="Rajasthan Foundation places Jodhpur district within its Marwar region listing.",
             summary="The page enumerates Jaisalmer, Barmer, and Jodhpur districts under Marwar and lists Jodhpur among its towns/cities.",
             confidence=0.97, scope="Marwar-specific", status=Status.VERIFIED,
             notes="Geographic context only; this does not define a single uniform Marwari identity.")
    evidence("EVID_002", "SRC_002", culture="Rajasthan", region=None, category="language",
             claim="The Rajasthan Foundation lists Marwari among the varieties/dialects of Rajasthani.",
             summary="The institutional page names Marwari, Mewari, Dundari, and Vagadi as examples under its Rajasthani-language overview.",
             confidence=0.91, scope="Rajasthan-general", status=Status.VERIFIED,
             notes="The page does not establish fine-grained Jodhpur speech patterns or provide validated phrases.")
    evidence("EVID_003", "SRC_003", category="architecture",
             claim="Rajasthan Tourism describes Mehrangarh Fort as dominating a rocky ridge above Jodhpur and describes blue-toned buildings in the city.",
             summary="The Jodhpur page calls it the Blue City and describes blue shades on forts, palaces, temples, havelis, houses, and the fort's rocky ridge setting.",
             confidence=0.96, scope="Jodhpur-specific", status=Status.VERIFIED,
             notes="A destination description; not a claim that all homes are blue or representative of rural Marwar.")
    evidence("EVID_004", "SRC_004", category="clothing",
             claim="A Rajasthan Tourism account of the Marwar Festival in Jodhpur presents Jodhpuri safas and bandhini dupattas as festival clothing.",
             summary="The travel diary describes festival displays at Mehrangarh Fort and Umaid Bhawan featuring traditional attire including Jodhpuri safas (turbans) and bandhini tie-dye dupattas.",
             confidence=0.87, scope="Marwar-specific", status=Status.PARTIALLY_SUPPORTED,
             notes="Festival presentation evidence; it does not establish everyday or universal clothing.")
    evidence("EVID_005", "SRC_005", category="clothing",
             claim="Rajasthan Tourism lists tie-and-dye bandhej fabrics among textiles associated with Jodhpur.",
             summary="The official shopping guide names Jodhpur, Jaipur, and Bikaner for tie-and-dye bandhej fabrics.",
             confidence=0.94, scope="Jodhpur-specific", status=Status.VERIFIED,
             notes="Craft/location association; no claim about who wears a particular textile or on what occasion.")
    evidence("EVID_006", "SRC_005", category="textiles",
             claim="Rajasthan Tourism identifies Salawas village near Jodhpur with dhurries made using cotton yarn or camel hair.",
             summary="The shopping guide names Salawas in Jodhpur among places to buy dhurries and describes village-made rugs with geometric or floral patterns.",
             confidence=0.92, scope="Jodhpur-specific", status=Status.VERIFIED,
             notes="This supports a named craft/product, not its presence in every home.")
    evidence("EVID_007", "SRC_003", category="landscape",
             claim="Rajasthan Tourism describes Osian near Jodhpur with temple ruins, a stepwell, and a camel-ride/sunset viewpoint.",
             summary="The Jodhpur destination page locates Osian about 65 km from Jodhpur and describes a stepwell, temple ruins, and a rustic camel-ride and sunset setting.",
             confidence=0.89, scope="Jodhpur-specific", status=Status.PARTIALLY_SUPPORTED,
             notes="Visitor-facing description of Osian; it does not define all rural landscapes in Marwar.")
    evidence("EVID_008", "SRC_003", category="landscape",
             claim="Rajasthan Tourism says Khejri trees are prominent in western Rajasthan and identifies Khejrli village near Jodhpur with the tree's name.",
             summary="The Jodhpur page connects the village name Khejrli to Khejri (Prosopis cineraria), described there as prominent in western Rajasthan.",
             confidence=0.90, scope="Western Rajasthan", status=Status.PARTIALLY_SUPPORTED,
             notes="The source is about one village and a regional tree; it does not establish a complete rural ecology profile.")
    evidence("EVID_009", "SRC_003", category="music",
             claim="Rajasthan Tourism describes the Marwar Festival in Jodhpur as featuring folk music and songs honoring former rulers of Marwar.",
             summary="The Jodhpur page says the festival features folk music and art forms revisiting stories written and sung to honor former Marwar rulers.",
             confidence=0.91, scope="Marwar-specific", status=Status.PARTIALLY_SUPPORTED,
             notes="Festival and commemorative performance context; not a general claim about everyday music.")
    evidence("EVID_010", "SRC_004", category="dance",
             claim="Rajasthan Tourism describes Ghoomar performances at Mandore Garden during its Marwar Festival account.",
             summary="The official travel diary identifies Ghoomar as a featured performance at Mandore Garden in its description of the Jodhpur festival.",
             confidence=0.86, scope="Marwar-specific", status=Status.PARTIALLY_SUPPORTED,
             notes="Event-specific evidence; not a claim about all Marwari communities or occasions.")
    evidence("EVID_011", "SRC_006", culture="Rajasthan", region=None, category="rituals",
             claim="Rajasthan Tourism describes Toran-Bandan as a wedding custom in which a mounted groom touches a floral decoration over the bride's doorway.",
             summary="The statewide customs page describes the groom approaching on horseback, touching the toran above the entrance, and being greeted by his mother-in-law with tilak.",
             confidence=0.79, scope="Rajasthan-general", status=Status.PARTIALLY_SUPPORTED,
             notes="Not independently established here as a specifically Marwari or Jodhpur practice.")
    evidence("EVID_012", "SRC_007", culture="Rajasthan", region=None, category="food",
             claim="Rajasthan Foundation lists bajra, gram flour, corn, barley, and dairy products among common ingredients in Rajasthan cuisine.",
             summary="The Foundation's statewide cuisine overview relates listed ingredients to regional availability and notes dal baati churma, ker sangri, and other dishes as examples of Rajasthani cuisine.",
             confidence=0.78, scope="Rajasthan-general", status=Status.PARTIALLY_SUPPORTED,
             notes="Statewide overview only; do not infer a particular Marwari household menu or dietary practice.")
    store.add_language_evidence(LanguageEvidence(
        language_evidence_id="LANG_001", culture="Marwari", dialect="Marwari", phrase=None,
        meaning=None, context=None, source_id="SRC_002", confidence=0.93,
        regional_scope="Rajasthan-general", status=Status.INSUFFICIENT_EVIDENCE,
        notes="The source confirms Marwari is named among Rajasthani varieties but provides no source-backed phrase/meaning/context suitable for dialogue.",
    ))
    if save:
        store.save()
    return store
