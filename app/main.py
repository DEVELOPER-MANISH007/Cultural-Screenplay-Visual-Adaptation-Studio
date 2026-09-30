"""Streamlit entry point for the Phase 0 foundation demo.

Run with:  streamlit run app/main.py   (or: python run.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when launched via `streamlit run app/main.py`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Project  # noqa: E402
from app.ui.screenplay_input import render_extraction, render_screenplay_input  # noqa: E402
from app.ui.project_memory import render_project_memory  # noqa: E402
from app.ui.cultural_research import render_cultural_research  # noqa: E402
from app.ui.adaptation_plan import render_adaptation_plan  # noqa: E402
from app.ui.adapted_screenplay import render_adapted_screenplay  # noqa: E402
from app.ui.visual_production_pack import render_visual_production_pack  # noqa: E402
from app.ui.visual_generation import render_visual_generation  # noqa: E402
from app.ui.final_production_package import render_final_production_package  # noqa: E402

OTHER = "Other (specify)"

SETTING_OPTIONS = [
    "Urban apartment",
    "Village home",
    "Market / bazaar",
    "Temple / place of worship",
    "Wedding venue",
    "Railway station",
    OTHER,
]

SCRIPT_OPTIONS = [
    "Devanagari",
    "Bengali-Assamese",
    "Gurmukhi",
    "Gujarati",
    "Odia",
    "Tamil",
    "Telugu",
    "Kannada",
    "Malayalam",
    "Latin (romanized)",
    OTHER,
]


def _choice(label: str, options: list[str], key: str) -> str:
    """Selectbox with an optional free-text fallback."""
    selected = st.selectbox(label, options, key=f"{key}_select")
    if selected == OTHER:
        return st.text_input(f"{label} (custom)", key=f"{key}_custom").strip()
    return selected


def main() -> None:
    settings = get_settings()
    st.set_page_config(page_title=settings.app_name, layout="centered")
    st.title("Cultural Screenplay & Visual Adaptation Studio")
    st.caption("Phases 0–9: screenplay ingestion, structured extraction, project memory, cultural research, adaptation planning, approved screenplay adaptation, visual production specifications, approval-gated visual generation, and validated production export.")

    title = st.text_input("Project title")
    culture = st.text_input("Culture")
    dialect = st.text_input("Dialect")
    region = st.text_input("Region")
    setting = _choice("Setting", SETTING_OPTIONS, "setting")
    script = _choice("Script", SCRIPT_OPTIONS, "script")

    if st.button("Create Project"):
        try:
            st.session_state["project"] = Project(
                title=title,
                culture=culture,
                dialect=dialect,
                region=region,
                setting=setting,
                script=script,
            )
        except ValidationError as exc:
            st.session_state.pop("project", None)
            st.error("Could not create project. A non-empty project title is required.")
            if settings.debug:
                st.code(str(exc))
        else:
            st.success("Project created successfully.")

    project: Project | None = st.session_state.get("project")
    if project is not None:
        data = project.model_dump(mode="json")
        st.subheader("Created project")
        st.table({"Field": list(data.keys()), "Value": [str(v) for v in data.values()]})
        with st.expander("View as JSON"):
            st.json(data)

    st.divider()
    render_screenplay_input()
    render_extraction()
    render_project_memory()
    render_cultural_research()
    render_adaptation_plan()
    render_adapted_screenplay()
    render_visual_production_pack()
    render_visual_generation()
    render_final_production_package()


main()
