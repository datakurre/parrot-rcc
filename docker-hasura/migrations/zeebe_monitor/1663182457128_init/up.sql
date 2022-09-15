CREATE VIEW public.process_resource AS
 SELECT process.key_,
    encode(lo_get(process.resource_), 'escape'::text) AS resource
   FROM public.process;

CREATE VIEW public.variable_value AS
 SELECT variable.id,
    (encode(lo_get(variable.value_), 'escape'::text))::json AS value
   FROM public.variable;
