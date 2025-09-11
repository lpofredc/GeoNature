
\restrict Es58PgLfW1n5bCe6E7KeI64kBFCihtP8UVsH3V0epcEg7f1S5t5wVrkXELzSW9l

CREATE TABLE gn_imports.t_contentmappings (
    id integer NOT NULL,
    "values" json
);

ALTER TABLE ONLY gn_imports.t_contentmappings
    ADD CONSTRAINT t_contentmappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY gn_imports.t_contentmappings
    ADD CONSTRAINT t_contentmappings_id_fkey FOREIGN KEY (id) REFERENCES gn_imports.t_mappings(id) ON DELETE CASCADE;

\unrestrict Es58PgLfW1n5bCe6E7KeI64kBFCihtP8UVsH3V0epcEg7f1S5t5wVrkXELzSW9l

