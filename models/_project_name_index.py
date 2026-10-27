from tortoise.indexes import Index


class ProjectNameIndex(Index):
    """One name per team, or per creator for projects without a team."""

    def __init__(self):
        super().__init__(fields=["team_id", "created_by", "name"], name="uid_novels_scope_name")

    def get_sql(self, schema_generator, model, safe):
        exists = "IF NOT EXISTS " if safe else ""
        # IDs are positive. Zero represents the shared local workspace, never a user/team.
        return (
            f'CREATE UNIQUE INDEX {exists}"uid_novels_scope_name" ON "novels" '
            '((COALESCE("team_id", 0)), '
            '(CASE WHEN "team_id" IS NULL THEN COALESCE("created_by", 0) ELSE 0 END), "name");'
        )
