"""${message}

修订号（Revision ID）: ${up_revision}
父修订（Revises）: ${down_revision | comma,n}
创建时间（Create Date）: ${create_date}

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Alembic 修订标识
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """升级：创建/修改数据库对象。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回滚：按依赖逆序撤销 upgrade 中的变更。"""
    ${downgrades if downgrades else "pass"}
