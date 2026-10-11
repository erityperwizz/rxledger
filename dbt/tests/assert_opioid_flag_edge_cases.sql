-- Known cases for the opioid flag: substrings that must not match, and buprenorphine.
with expected(generic_name_norm, should_be_opioid) as (
    values
        ('HYDROCODONE ACETAMINOPHEN', true),
        ('TRAMADOL HCL', true),
        ('OXYCODONE HCL', true),
        ('IPRATROPIUM BROMIDE', false),
        ('TIOTROPIUM BROMIDE', false),
        ('APOMORPHINE HCL', false),
        ('BUPRENORPHINE HCL NALOXONE HCL', false),
        ('BUPRENORPHINE', false)
)
select e.generic_name_norm, e.should_be_opioid, d.is_opioid
from expected e
join {{ ref('dim_drug') }} d using (generic_name_norm)
where d.is_opioid <> e.should_be_opioid
