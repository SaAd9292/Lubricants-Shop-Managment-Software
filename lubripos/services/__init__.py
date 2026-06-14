"""Service layer: business logic and data access, independent of the UI.

Services own all SQL and domain rules. Controllers call services; views
never touch the database directly. This keeps the system testable and the
GUI thin.
"""
