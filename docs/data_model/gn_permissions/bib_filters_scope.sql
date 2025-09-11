
\restrict ozOM1wSweLQkoMsv3tXDmMQiTWOa6tBcwm30fIbLGDTpzOGxMMO9rXEhVTgei9E

CREATE TABLE gn_permissions.bib_filters_scope (
    value integer NOT NULL,
    label character varying,
    description character varying
);

CREATE SEQUENCE gn_permissions.bib_filters_scope_value_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE gn_permissions.bib_filters_scope_value_seq OWNED BY gn_permissions.bib_filters_scope.value;

ALTER TABLE ONLY gn_permissions.bib_filters_scope
    ADD CONSTRAINT bib_filters_scope_pkey PRIMARY KEY (value);

\unrestrict ozOM1wSweLQkoMsv3tXDmMQiTWOa6tBcwm30fIbLGDTpzOGxMMO9rXEhVTgei9E

