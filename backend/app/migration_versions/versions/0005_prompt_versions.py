from alembic import op
import sqlalchemy as sa

revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('agent_executions',sa.Column('prompt_version',sa.String(60),nullable=False,server_default='legacy-m2-v1'))


def downgrade():
    raise RuntimeError('Restore backup to downgrade')
