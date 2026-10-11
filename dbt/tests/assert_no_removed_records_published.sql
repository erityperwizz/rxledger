-- Records CMS listed as removed or deleted must not appear in the published general file.
select g.record_id
from {{ ref('stg_op__general_payments') }} g
join read_parquet('{{ var("bronze_dir") }}/op_removed_deleted.parquet') r
  on g.record_id = cast(r.Record_ID as bigint)
