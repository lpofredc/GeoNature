
\restrict fEgDLCxoaDR5vmg57Uxyy1wGlp6rZUf1f16Eom3ue3TPyXrD7THvXqB2Mt0LVgx

CREATE TABLE utilisateurs.cor_roles (
    id_role_groupe integer NOT NULL,
    id_role_utilisateur integer NOT NULL
);

ALTER TABLE ONLY utilisateurs.cor_roles
    ADD CONSTRAINT cor_roles_pkey PRIMARY KEY (id_role_groupe, id_role_utilisateur);

ALTER TABLE ONLY utilisateurs.cor_roles
    ADD CONSTRAINT cor_roles_id_role_groupe_fkey FOREIGN KEY (id_role_groupe) REFERENCES utilisateurs.t_roles(id_role) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE ONLY utilisateurs.cor_roles
    ADD CONSTRAINT cor_roles_id_role_utilisateur_fkey FOREIGN KEY (id_role_utilisateur) REFERENCES utilisateurs.t_roles(id_role) ON UPDATE CASCADE ON DELETE CASCADE;

\unrestrict fEgDLCxoaDR5vmg57Uxyy1wGlp6rZUf1f16Eom3ue3TPyXrD7THvXqB2Mt0LVgx

