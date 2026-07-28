-- Allow chat file attachments (documents) in addition to image/video.

alter table messages
    drop constraint if exists messages_media_type_check;

alter table messages
    add constraint messages_media_type_check
    check (media_type is null or media_type in ('image', 'video', 'file'));
