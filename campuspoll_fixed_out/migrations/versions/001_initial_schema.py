"""initial schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-04-29T01:21:51.471606

"""
from alembic import op
import sqlalchemy as sa

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(120), nullable=False),
        sa.Column('password', sa.String(200), nullable=False),
        sa.Column('student_id', sa.String(20), nullable=False),
        sa.Column('department', sa.String(100), nullable=False),
        sa.Column('year', sa.String(20), nullable=False),
        sa.Column('role', sa.String(20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('verify_token', sa.String(200), nullable=True),
        sa.Column('reset_token', sa.String(200), nullable=True),
        sa.Column('totp_secret', sa.String(100), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), nullable=True),
        sa.Column('session_token', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('student_id'),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_role', 'users', ['role'])
    op.create_index('ix_users_student_id', 'users', ['student_id'])

    op.create_table('elections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('position', sa.String(100), nullable=False),
        sa.Column('nomination_start', sa.DateTime(), nullable=False),
        sa.Column('nomination_end', sa.DateTime(), nullable=False),
        sa.Column('voting_start', sa.DateTime(), nullable=False),
        sa.Column('voting_end', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('results_published', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_elections_status', 'elections', ['status'])

    op.create_table('announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('nominations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('election_id', sa.Integer(), nullable=False),
        sa.Column('manifesto', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['election_id'], ['elections.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_nominations_election_id', 'nominations', ['election_id'])
    op.create_index('ix_nominations_user_id', 'nominations', ['user_id'])

    op.create_table('candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('election_id', sa.Integer(), nullable=False),
        sa.Column('manifesto', sa.Text(), nullable=False),
        sa.Column('photo', sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(['election_id'], ['elections.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_candidates_election_id', 'candidates', ['election_id'])
    op.create_index('ix_candidates_user_id', 'candidates', ['user_id'])

    op.create_table('votes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('voter_id', sa.Integer(), nullable=False),
        sa.Column('election_id', sa.Integer(), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('voted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id']),
        sa.ForeignKeyConstraint(['election_id'], ['elections.id']),
        sa.ForeignKeyConstraint(['voter_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('voter_id', 'election_id', name='unique_vote'),
    )
    op.create_index('ix_votes_candidate_id', 'votes', ['candidate_id'])
    op.create_index('ix_votes_election_id', 'votes', ['election_id'])
    op.create_index('ix_votes_voter_id', 'votes', ['voter_id'])

    op.create_table('notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('type', sa.String(50), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])

    op.create_table('login_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(120), nullable=False),
        sa.Column('ip_address', sa.String(50), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('attempted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_attempts_ip_address', 'login_attempts', ['ip_address'])

    op.create_table('analytics_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('page', sa.String(100), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('load_time_ms', sa.Float(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(300), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_analytics_events_event_type', 'analytics_events', ['event_type'])
    op.create_index('ix_analytics_events_timestamp', 'analytics_events', ['timestamp'])

    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(200), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_timestamp', 'audit_logs', ['timestamp'])


def downgrade():
    op.drop_table('audit_logs')
    op.drop_table('analytics_events')
    op.drop_table('login_attempts')
    op.drop_table('notifications')
    op.drop_table('votes')
    op.drop_table('candidates')
    op.drop_table('nominations')
    op.drop_table('announcements')
    op.drop_table('elections')
    op.drop_table('users')
