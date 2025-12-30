"""Severity level and weight definitions for aiocop."""

from typing import Literal

IoSeverityLevel = Literal["low", "medium", "high"]

WEIGHT_HEAVY = 50
WEIGHT_MODERATE = 10
WEIGHT_LIGHT = 1
WEIGHT_TRIVIAL = 0

THRESHOLD_HIGH = 50
THRESHOLD_MEDIUM = 10
THRESHOLD_LOW = 1
