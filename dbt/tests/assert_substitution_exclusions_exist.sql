-- Every hand reviewed exclusion must name a real Part D Brand drug (guards against typos).
select e.brand_name
from {{ ref('generic_substitution_exclusions') }} e
left join {{ ref('dim_drug') }} d
  on d.brand_name_norm = {{ normalize_name('e.brand_name') }}
 and d.brand_generic = 'Brand'
where d.drug_key is null
