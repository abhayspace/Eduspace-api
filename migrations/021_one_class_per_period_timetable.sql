-- Each class may belong to at most one period timetable.

-- Split existing timetables that have multiple classes into separate timetables.
DO $split$
DECLARE
    r RECORD;
    new_id uuid;
BEGIN
    FOR r IN
        SELECT
            ptc.id AS link_id,
            ptc.timetable_id,
            ptc.class_id,
            pt.school_id,
            pt.period_count,
            pt.times_saved,
            pt.created_at,
            ROW_NUMBER() OVER (PARTITION BY ptc.timetable_id ORDER BY ptc.class_name) AS rn
        FROM period_timetable_classes ptc
        JOIN period_timetables pt ON pt.id = ptc.timetable_id
    LOOP
        IF r.rn > 1 THEN
            new_id := gen_random_uuid();
            INSERT INTO period_timetables (id, school_id, period_count, times_saved, created_at, updated_at)
            VALUES (new_id, r.school_id, r.period_count, r.times_saved, r.created_at, now());

            UPDATE period_timetable_classes
            SET timetable_id = new_id
            WHERE id = r.link_id;

            INSERT INTO period_timetable_slots (
                timetable_id, period_index, start_time, start_meridiem, end_time, end_meridiem
            )
            SELECT new_id, period_index, start_time, start_meridiem, end_time, end_meridiem
            FROM period_timetable_slots
            WHERE timetable_id = r.timetable_id;
        END IF;
    END LOOP;
END $split$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_period_timetable_classes_class_unique
    ON period_timetable_classes (class_id);
