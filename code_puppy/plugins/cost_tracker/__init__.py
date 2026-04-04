"""Cost tracker plugin – tracks API costs per model and enforces budgets.

Provides cost tracking and budget awareness for API calls, with configurable
daily and per-session budget limits. Alerts at 75% threshold and hard-stops
at 100% budget consumption.
"""
