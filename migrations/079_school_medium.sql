-- Add medium column to schools table for language of instruction
ALTER TABLE schools ADD COLUMN IF NOT EXISTS medium text DEFAULT 'English';
