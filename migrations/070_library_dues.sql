-- Library fines and deposits uploaded by librarian for students.
CREATE TABLE IF NOT EXISTS library_due_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL CHECK (record_type IN ('fine', 'deposit')),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    note TEXT,
    recorded_at DATE NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_library_due_records_user_id ON library_due_records(user_id);
CREATE INDEX IF NOT EXISTS idx_library_due_records_school_id ON library_due_records(school_id);
CREATE INDEX IF NOT EXISTS idx_library_due_records_created_at ON library_due_records(created_at DESC);
