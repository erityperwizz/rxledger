-- Calendar for 2024. date_key is an integer yyyymmdd.

select
    cast(strftime(d, '%Y%m%d') as integer)  as date_key,
    cast(d as date)                         as date,
    year(d)                                 as year,
    quarter(d)                              as quarter,
    month(d)                                as month,
    strftime(d, '%B')                       as month_name,
    strftime(d, '%b %Y')                    as month_label,
    dayofweek(d)                            as day_of_week,
    strftime(d, '%A')                       as day_name,
    (dayofweek(d) in (0, 6))                as is_weekend
from range(date '2024-01-01', date '2025-01-01', interval 1 day) t(d)
