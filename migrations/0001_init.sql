CREATE TABLE player (
  id         uuid PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attempt (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id    uuid NOT NULL REFERENCES player(id) ON DELETE CASCADE,
  quiz_slug    text NOT NULL,
  status       text NOT NULL DEFAULT 'in_progress'
               CHECK (status IN ('in_progress', 'completed')),
  score        integer CHECK (score >= 0),
  started_at   timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK (
    (status = 'in_progress' AND score IS NULL AND completed_at IS NULL) OR
    (status = 'completed' AND score IS NOT NULL AND completed_at IS NOT NULL)
  )
);
-- Serves best score, last attempted and ownership lookups for one player.
CREATE INDEX attempt_player_quiz_idx ON attempt (player_id, quiz_slug, started_at DESC);

CREATE TABLE answer (
  attempt_id  uuid NOT NULL REFERENCES attempt(id) ON DELETE CASCADE,
  question_id text NOT NULL,
  selected    text[] NOT NULL CHECK (cardinality(selected) >= 1),
  is_correct  boolean NOT NULL,
  PRIMARY KEY (attempt_id, question_id)  -- one answer per question per attempt
);
