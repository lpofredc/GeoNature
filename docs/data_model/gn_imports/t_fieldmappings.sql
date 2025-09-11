
\restrict A57aEgxJSwTwIPTtd3YkvojXHM2TC7Mz1r6vawg3XNrl7E46na2JWUCawalF9In

CREATE TABLE gn_imports.t_fieldmappings (
    id integer NOT NULL,
    "values" json
);

ALTER TABLE ONLY gn_imports.t_fieldmappings
    ADD CONSTRAINT t_fieldmappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY gn_imports.t_fieldmappings
    ADD CONSTRAINT t_fieldmappings_id_fkey FOREIGN KEY (id) REFERENCES gn_imports.t_mappings(id) ON DELETE CASCADE;

\unrestrict A57aEgxJSwTwIPTtd3YkvojXHM2TC7Mz1r6vawg3XNrl7E46na2JWUCawalF9In

