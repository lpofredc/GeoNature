
\restrict eCZcryu9qjyuIvWTz3eJ2H0YVATnw8mWmNLryg4W9mY9bvM5Rwwg3HTuali9eM3

CREATE MATERIALIZED VIEW taxonomie.vm_regne AS
 SELECT DISTINCT tx.regne
   FROM taxonomie.taxref tx
  WITH NO DATA;

CREATE UNIQUE INDEX i_unique_regne ON taxonomie.vm_regne USING btree (regne);

\unrestrict eCZcryu9qjyuIvWTz3eJ2H0YVATnw8mWmNLryg4W9mY9bvM5Rwwg3HTuali9eM3

