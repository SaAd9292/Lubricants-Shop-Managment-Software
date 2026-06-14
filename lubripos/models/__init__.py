"""Domain models / typed row helpers.

Currently the service layer returns sqlite3.Row / dicts directly. As modules
grow, typed dataclasses (Product, Sale, ...) will live here to give the rest
of the app a stable, validated shape independent of the DB schema.
"""
