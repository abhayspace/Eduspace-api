-- Multiple student documents (jpg, jpeg, png, pdf).

alter table students add column if not exists documents jsonb not null default '[]'::jsonb;

update students
set documents = jsonb_build_array(
    jsonb_build_object(
        'document_url', document_url,
        'document_name', coalesce(document_name, 'document')
    )
)
where document_url is not null
  and (documents is null or documents = '[]'::jsonb);
