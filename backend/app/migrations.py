from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


def upgrade_database(engine):
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).parent / 'migration_versions'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        tables = set(inspect(connection).get_table_names())
        if 'alembic_version' not in tables and tables & {'projects', 'tasks', 'artifacts'}:
            # Only adopt a verified M1 schema; never silently stamp an arbitrary database.
            expected = {
                'projects': {'id','name','description','sponsor_mode','llm_mode','execution_mode','status','phase','seed','simulation_day','created_at'},
                'tasks': {'id','project_id','wbs_code','title','owner','duration_days','budget_cents','acceptance_criteria'},
                'artifacts': {'id','project_id','kind','version','author','payload','created_at'},
            }
            if not all(name in tables and {c['name'] for c in inspect(connection).get_columns(name)} == cols for name, cols in expected.items()):
                raise RuntimeError('Unrecognized pre-migration database schema')
            command.stamp(config, '0001')
        command.upgrade(config, 'head')
