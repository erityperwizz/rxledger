-- Grain: general payment record x product slot. A payment that names several products is
-- split evenly across them (amount = payment amount / products named), so summing amount
-- over any slice reproduces the published total. Payments naming no product keep one row
-- with product_slot 0. prescriber_key is NULL for teaching hospitals (no NPI).
-- drug_key is set only for Drug or Biological products that map to a Part D drug.

with pay as (
    select * from {{ ref('stg_op__general_payments') }}
),

products as (
    select pp.*, m.drug_key
    from {{ ref('stg_op__payment_products') }} pp
    left join {{ ref('int_op_product_drug_map') }} m
      on m.product_name_norm = pp.product_name_norm
     and m.is_primary
     and pp.product_type in ('Drug', 'Biological')
),

product_counts as (
    select record_id, count(*) as products_named from products group by 1
),

lines as (
    select
        p.record_id,
        coalesce(pr.product_slot, 0)                as product_slot,
        pr.product_type,
        pr.product_name,
        pr.product_category,
        pr.drug_key,
        coalesce(pc.products_named, 0)              as products_named,
        p.amount_usd                                as payment_amount_usd,
        p.amount_usd / greatest(coalesce(pc.products_named, 1), 1) as amount_usd,
        p.npi,
        p.manufacturer_id,
        p.payment_date,
        p.payment_date_invalid,
        p.nature_of_payment,
        p.form_of_payment,
        p.recipient_type,
        p.is_teaching_hospital,
        p.number_of_payments
    from pay p
    left join products pr using (record_id)
    left join product_counts pc using (record_id)
)

select
    l.record_id,
    l.product_slot,
    dp.prescriber_key,
    m.manufacturer_key,
    l.drug_key,
    cast(strftime(l.payment_date, '%Y%m%d') as integer)  as date_key,
    l.amount_usd,
    l.payment_amount_usd,
    l.products_named,
    l.nature_of_payment,
    l.form_of_payment,
    l.recipient_type,
    l.is_teaching_hospital,
    l.product_type,
    l.product_name,
    l.product_category,
    l.number_of_payments,
    l.payment_date_invalid
from lines l
left join {{ ref('dim_prescriber') }} dp using (npi)
left join {{ ref('dim_manufacturer') }} m using (manufacturer_id)
