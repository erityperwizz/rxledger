"""Checks against the built DuckDB warehouse: suppression handling and the construction of
the Question 2 model inputs. Skipped when the warehouse has not been built.

Author: Erica Mathias
"""

import duckdb
import pytest

import config

pytestmark = pytest.mark.skipif(not config.DUCKDB_PATH.exists(),
                                reason="run the pipeline first (no warehouse)")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
    yield c
    c.close()


def one(con, sql):
    return con.execute(sql).fetchone()


def test_suppressed_beneficiaries_are_null_never_zero(con):
    zero, null_rows, flagged_mismatch = one(con, """
        select count(*) filter (where beneficiaries = 0),
               count(*) filter (where beneficiaries is null),
               count(*) filter (where (beneficiaries is null) <> beneficiaries_suppressed)
        from staging.stg_partd__prescriber_drug""")
    assert zero == 0
    assert null_rows > 0          # suppression exists in the source and was kept
    assert flagged_mismatch == 0


def test_ge65_flags_blank_the_values(con):
    leaked = one(con, """
        select count(*) from staging.stg_partd__prescriber_drug
        where (ge65_suppression_flag is not null and coalesce(ge65_claims, ge65_drug_cost,
               ge65_fills_30day, ge65_day_supply) is not null)
           or (ge65_bene_suppression_flag is not null and ge65_beneficiaries is not null)""")[0]
    assert leaked == 0


def test_raw_blank_beneficiaries_match_staging_nulls(con):
    raw, staged = one(con, f"""
        select (select count(*) from read_parquet(
                    '{(config.BRONZE_DIR / "partd_prescriber_drug.parquet").as_posix()}')
                where nullif(trim(Tot_Benes), '') is null),
               (select count(*) from staging.stg_partd__prescriber_drug
                where beneficiaries is null)""")
    assert raw == staged


def test_q2_model_inputs_are_consistent(con):
    from analysis.payments_vs_prescribing import BUILD_SQL

    con.execute(BUILD_SQL)
    n_fam, bad_claims, bad_other, bad_pay, dup = one(con, """
        select count(distinct family),
               count(*) filter (where family_claims < 0 or (family_claims between 1 and 10)),
               count(*) filter (where other_claims < 0),
               count(*) filter (where paid_mfr_usd < 0 or paid_product_usd < 0),
               count(*) - count(distinct (family, prescriber_key))
        from analysis""")
    assert n_fam == 30
    assert bad_claims == 0        # visible Part D rows always have 11+ claims
    assert bad_other == 0
    assert bad_pay == 0
    assert dup == 0               # one row per family x prescriber
    # every eligible prescriber is a Part D prescriber in an eligible specialty
    stray = one(con, """
        select count(*) from analysis a
        left join fam_spec fs using (family, specialty_key)
        where fs.family is null""")[0]
    assert stray == 0
