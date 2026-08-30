-- Study material folders and files per subject.
-- Teachers create folders (e.g. Notes, Worksheets, Recordings) for a subject
-- and upload files into them. Students see folders + files for their subjects.

CREATE TABLE IF NOT EXISTS study_folders (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    school_id TEXT NOT NULL,
    subject_id TEXT,
    subject_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    created_by TEXT,
    created_by_name TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_study_folders_school ON study_folders(school_id);
CREATE INDEX IF NOT EXISTS idx_study_folders_subject ON study_folders(school_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_study_folders_subject_name ON study_folders(school_id, subject_name);

CREATE TABLE IF NOT EXISTS study_files (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    school_id TEXT NOT NULL,
    folder_id TEXT NOT NULL REFERENCES study_folders(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_url TEXT NOT NULL,
    content_type TEXT DEFAULT 'application/octet-stream',
    file_size BIGINT DEFAULT 0,
    uploaded_by TEXT,
    uploaded_by_name TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_study_files_school ON study_files(school_id);
CREATE INDEX IF NOT EXISTS idx_study_files_folder ON study_files(folder_id);
