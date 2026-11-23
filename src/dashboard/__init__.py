"""Sistema multiagente para geração dinâmica de dashboards interativos (Plotly)."""

from src.dashboard.dashboard_agent import edit_dashboard_spec
from src.dashboard.orchestrator import (
    build_dashboard_from_store,
    default_output_path,
    generate_dashboard,
)
from src.dashboard.schemas import (
    ALLOWED_WIDGET_KINDS,
    DashboardRunResult,
    DashboardSpec,
    DatasetResult,
    MAX_REVISIONS,
    MAX_ROWS_TO_LLM,
    OrchestratorPlan,
    ReviewResult,
    WidgetIssue,
    WidgetSpec,
)

__all__ = [
    "ALLOWED_WIDGET_KINDS",
    "DashboardRunResult",
    "DashboardSpec",
    "DatasetResult",
    "MAX_REVISIONS",
    "MAX_ROWS_TO_LLM",
    "OrchestratorPlan",
    "ReviewResult",
    "WidgetIssue",
    "WidgetSpec",
    "build_dashboard_from_store",
    "default_output_path",
    "edit_dashboard_spec",
    "generate_dashboard",
]
