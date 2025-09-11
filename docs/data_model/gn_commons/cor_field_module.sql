
\restrict hcaSK1FKoOJjy6VmD6yc3IaANm7lJ7EaqVyBJbNkEFY7AbTckLMtSqaG74UdQwo

CREATE TABLE gn_commons.cor_field_module (
    id_field integer NOT NULL,
    id_module integer NOT NULL
);

ALTER TABLE ONLY gn_commons.cor_field_module
    ADD CONSTRAINT pk_cor_field_module PRIMARY KEY (id_field, id_module);

ALTER TABLE ONLY gn_commons.cor_field_module
    ADD CONSTRAINT fk_cor_field_module FOREIGN KEY (id_module) REFERENCES gn_commons.t_modules(id_module) ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE ONLY gn_commons.cor_field_module
    ADD CONSTRAINT fk_cor_field_module_field FOREIGN KEY (id_field) REFERENCES gn_commons.t_additional_fields(id_field) ON UPDATE CASCADE ON DELETE CASCADE;

\unrestrict hcaSK1FKoOJjy6VmD6yc3IaANm7lJ7EaqVyBJbNkEFY7AbTckLMtSqaG74UdQwo

