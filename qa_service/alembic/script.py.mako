<%
import datetime
# здесь, при необходимости, можно импортировать любые доп. библиотеки
# или объявить локальные переменные для шаблона
%>
"""${message}

Revision ID: ${up_revision}
Revises: ${', '.join(d for d in down_revisions) if down_revisions else down_revision or 'None'}
Create Date: ${create_date}
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = ${up_revision!r}
down_revision = ${down_revision if down_revision else None!r}
# если у вас несколько down_revisions (feature branch), используйте down_revisions
# см. документацию Alembic о множественных родителях

branch_labels = ${branch_labels if branch_labels else None!r}
depends_on = ${depends_on if depends_on else None!r}

def upgrade():
    ${upgrades if upgrades else "pass"}

def downgrade():
    ${downgrades if downgrades else "pass"}