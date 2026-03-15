"""Sovereign — Hands package."""
from .code_engineer import CodeEngineerHand, CodeRequest, CodeResult
from .other_hands import (
    ResearchHand, ResearchResult,
    DeploymentHand, DeployRequest, DeployResult,
    WritingHand, WritingResult,
    SysAdminHand, SysAdminResult,
)

# Part 11 — Engineering hands
from .engineering import (
    APIBuilderHand, APIBuilderResult,
    DebuggerHand, DebuggerResult,
    TestEngineerHand, TestEngineerResult,
    CICDEngineerHand, CICDResult,
    PerformanceProfilerHand, PerformanceResult,
)

# Part 11 — Data hands
from .data import (
    DataAnalystHand, DataAnalystResult,
    DatabaseArchitectHand, DatabaseArchitectResult,
    ScraperHand, ScraperResult,
)

# Part 11 — Communication hands
from .communication import (
    EmailOperatorHand, EmailResult,
    SocialMediaHand, SocialMediaResult,
    MeetingAssistantHand, MeetingResult,
)

# Part 11 — Business hands
from .business import (
    InvoiceHand, InvoiceResult,
    CompetitiveIntelHand, CompetitiveIntelResult,
    SEOOptimizerHand, SEOResult,
    LegalDrafterHand, LegalDrafterResult,
)

# Part 11 — Product hands
from .product import (
    DocumentationHand, DocumentationResult,
    DesignSystemHand, DesignSystemResult,
    OnboardingArchitectHand, OnboardingResult,
)

# Part 12 — Life Skills: Daily
from .life_daily import (
    DailyPlannerHand, DailyPlanResult,
    HabitTrackerHand, HabitResult,
    BudgetManagerHand, BudgetResult,
    JournalHand, JournalResult,
    NewsCuratorHand, NewsResult,
)

# Part 12 — Life Skills: Growth
from .life_growth import (
    FitnessCoachHand, FitnessResult,
    LearningTutorHand, LearningResult,
    MealPlannerHand, MealPlanResult,
    ContentConsumptionHand, ContentResult,
)

# Part 12 — Life Skills: Major Life
from .life_major import (
    TravelPlannerHand, TravelResult,
    ShoppingAssistantHand, ShoppingResult,
    RelationshipManagerHand, RelationshipResult,
    HomeAutomationHand, HomeAutoResult,
    RelocationHand, RelocationResult,
    HealthMonitorHand, HealthResult,
)

__all__ = [
    # Part 8 originals
    "CodeEngineerHand", "CodeRequest", "CodeResult",
    "ResearchHand", "ResearchResult",
    "DeploymentHand", "DeployRequest", "DeployResult",
    "WritingHand", "WritingResult",
    "SysAdminHand", "SysAdminResult",
    # Part 11 — Engineering
    "APIBuilderHand", "APIBuilderResult",
    "DebuggerHand", "DebuggerResult",
    "TestEngineerHand", "TestEngineerResult",
    "CICDEngineerHand", "CICDResult",
    "PerformanceProfilerHand", "PerformanceResult",
    # Part 11 — Data
    "DataAnalystHand", "DataAnalystResult",
    "DatabaseArchitectHand", "DatabaseArchitectResult",
    "ScraperHand", "ScraperResult",
    # Part 11 — Communication
    "EmailOperatorHand", "EmailResult",
    "SocialMediaHand", "SocialMediaResult",
    "MeetingAssistantHand", "MeetingResult",
    # Part 11 — Business
    "InvoiceHand", "InvoiceResult",
    "CompetitiveIntelHand", "CompetitiveIntelResult",
    "SEOOptimizerHand", "SEOResult",
    "LegalDrafterHand", "LegalDrafterResult",
    # Part 11 — Product
    "DocumentationHand", "DocumentationResult",
    "DesignSystemHand", "DesignSystemResult",
    "OnboardingArchitectHand", "OnboardingResult",
    # Part 12 — Life Skills: Daily
    "DailyPlannerHand", "DailyPlanResult",
    "HabitTrackerHand", "HabitResult",
    "BudgetManagerHand", "BudgetResult",
    "JournalHand", "JournalResult",
    "NewsCuratorHand", "NewsResult",
    # Part 12 — Life Skills: Growth
    "FitnessCoachHand", "FitnessResult",
    "LearningTutorHand", "LearningResult",
    "MealPlannerHand", "MealPlanResult",
    "ContentConsumptionHand", "ContentResult",
    # Part 12 — Life Skills: Major Life
    "TravelPlannerHand", "TravelResult",
    "ShoppingAssistantHand", "ShoppingResult",
    "RelationshipManagerHand", "RelationshipResult",
    "HomeAutomationHand", "HomeAutoResult",
    "RelocationHand", "RelocationResult",
    "HealthMonitorHand", "HealthResult",
]

