\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS mosaic.agent_tool_contract (
    tool_name          text NOT NULL,
    tool_version       text NOT NULL,
    description        text NOT NULL,
    input_schema       jsonb NOT NULL,
    output_schema      jsonb NOT NULL,
    read_only          boolean NOT NULL DEFAULT true,
    enabled            boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tool_name, tool_version)
);

CREATE TABLE IF NOT EXISTS mosaic.agent_session (
    agent_session_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_session_id text,
    user_context       jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at         timestamptz NOT NULL DEFAULT now(),
    ended_at           timestamptz,
    metadata           jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS mosaic.agent_turn (
    agent_turn_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_session_id   uuid NOT NULL REFERENCES mosaic.agent_session(agent_session_id) ON DELETE CASCADE,
    turn_number        integer NOT NULL CHECK (turn_number > 0),
    user_message       text NOT NULL,
    assistant_message  text,
    extracted_intent   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agent_session_id, turn_number)
);

CREATE TABLE IF NOT EXISTS mosaic.agent_tool_event (
    tool_event_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_turn_id      uuid NOT NULL REFERENCES mosaic.agent_turn(agent_turn_id) ON DELETE CASCADE,
    search_event_id    uuid,
    tool_name          text NOT NULL,
    tool_version       text NOT NULL,
    outcome            mosaic.tool_outcome NOT NULL,
    execution_origin   text NOT NULL DEFAULT 'model'
        CHECK (execution_origin IN ('model', 'controller_fallback')),
    input_payload      jsonb NOT NULL,
    output_payload     jsonb,
    duration_ms        integer CHECK (duration_ms >= 0),
    error_detail       text,
    occurred_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tool_name, tool_version)
        REFERENCES mosaic.agent_tool_contract(tool_name, tool_version)
);

ALTER TABLE mosaic.agent_tool_event
    ADD COLUMN IF NOT EXISTS execution_origin text NOT NULL DEFAULT 'model';
ALTER TABLE mosaic.agent_tool_event
    DROP CONSTRAINT IF EXISTS agent_tool_event_execution_origin_check;
ALTER TABLE mosaic.agent_tool_event
    ADD CONSTRAINT agent_tool_event_execution_origin_check
    CHECK (execution_origin IN ('model', 'controller_fallback'));

CREATE INDEX IF NOT EXISTS agent_tool_event_turn_idx
    ON mosaic.agent_tool_event (agent_turn_id, occurred_at);
CREATE INDEX IF NOT EXISTS agent_tool_event_tool_idx
    ON mosaic.agent_tool_event (tool_name, outcome, occurred_at DESC);
