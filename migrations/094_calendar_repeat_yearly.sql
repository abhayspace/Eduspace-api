alter table school_calendar_events
    add column if not exists repeat_yearly boolean not null default false;

-- Relax the original event_type check so 'event' (supported by the API schema) is allowed.
alter table school_calendar_events
    drop constraint if exists school_calendar_events_event_type_check;

alter table school_calendar_events
    add constraint school_calendar_events_event_type_check
    check (event_type in ('holiday', 'birthday', 'special_day', 'event'));
