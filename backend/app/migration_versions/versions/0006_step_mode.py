from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('step_mode', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    raise RuntimeError('Restore backup to downgrade')
