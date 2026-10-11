{#
  Normalize a drug or product name for matching across datasets:
  upper case, every run of non alphanumeric characters becomes one space, trimmed.
  Mirrors analysis/common.py::normalize_name (tested in tests/test_normalize.py).
#}
{% macro normalize_name(col) -%}
    nullif(trim(regexp_replace(upper({{ col }}), '[^A-Z0-9]+', ' ', 'g')), '')
{%- endmacro %}

{# Schema names without the target prefix, so tables land in staging, intermediate, marts #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
