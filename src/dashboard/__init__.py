"""Sistema multiagente para geração dinâmica de dashboards interativos (Plotly)."""

from src.dashboard.orchestrator import default_output_path, generate_dashboard
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
    "default_output_path",
    "generate_dashboard",
]
