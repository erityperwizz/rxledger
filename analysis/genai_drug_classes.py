"""Phase 8 (optional): classify each Part D generic name into a therapeutic class with a
local LLM, and validate the classes against hand labels before using them.

Author: Erica Mathias

Steps (run in order):
  python analysis/genai_drug_classes.py sample      write the blind labeling sheet
  python analysis/genai_drug_classes.py classify    classify every generic name (resumable)
  python analysis/genai_drug_classes.py evaluate    compare with the hand labels

Design
------
- One fixed prompt and a fixed list of classes (CLASSES). The model must answer with JSON
  that matches a schema (Ollama structured outputs); answers outside the list are
  rejected, retried once, and otherwise recorded as "Unclassified".
- Temperature 0 and a fixed seed, so reruns give the same answers.
- Validation: a random sample of SAMPLE_SIZE generic names (seed 2024) is labeled by hand
  without seeing the model output. Accuracy must reach ACCEPT_ACCURACY (fixed before
  looking at any results) for the classes to be used anywhere in the project.
- Generic drug names are public, so the class table is safe to publish.
"""

import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis.common import write_section  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
SAMPLE_SIZE = 100
ACCEPT_ACCURACY = 0.85
GENAI_DIR = config.ROOT / "analysis" / "genai"
LABEL_SHEET = GENAI_DIR / "hand_labels.csv"
CACHE_DIR = config.DATA_DIR / "genai"
OUT = config.PUBLIC_OUT / "genai_drug_classes.csv"

# class name: what belongs in it (shown to the model and to the human labeler)
CLASSES = {
    "Cardiovascular": "blood pressure, heart failure, angina, arrhythmia, diuretics",
    "Lipid lowering": "statins, ezetimibe, PCSK9 inhibitors, fibrates, omega-3 prescription",
    "Anticoagulant and antiplatelet": "warfarin, DOACs such as apixaban, heparins, clopidogrel",
    "Diabetes": "insulins, metformin, GLP-1, SGLT2, DPP-4, sulfonylureas, diabetes supplies are NOT here",
    "Endocrine and hormones": "thyroid, osteoporosis, corticosteroids taken by mouth, sex hormones, contraceptives, growth hormone",
    "Respiratory and allergy": "asthma and COPD inhalers, montelukast, antihistamines, nasal steroids",
    "Mental health": "antidepressants, antipsychotics, anxiolytics, sedative hypnotics, ADHD stimulants, lithium",
    "Neurology": "anticonvulsants, Parkinson's, dementia, migraine, multiple sclerosis, muscle relaxants",
    "Pain and anesthesia": "opioid analgesics, NSAIDs, acetaminophen combinations, gout, local anesthetics",
    "Substance use disorder": "buprenorphine and naloxone, naltrexone, varenicline, nicotine replacement",
    "Anti-infective": "antibiotics, antivirals including HIV and hepatitis, antifungals, antiparasitics",
    "Vaccine": "any vaccine or immune globulin given for prevention",
    "Cancer": "chemotherapy, targeted cancer drugs, hormone therapy for cancer",
    "Immunology": "biologics and small molecules for rheumatoid arthritis, psoriasis, IBD; transplant immunosuppressants",
    "Gastrointestinal": "acid reducers, antiemetics, laxatives, antidiarrheals, pancreatic enzymes, ursodiol",
    "Kidney and urology": "overactive bladder, BPH, erectile dysfunction, phosphate binders, kidney disease drugs",
    "Hematology": "iron, anemia, clotting factors, sickle cell, platelet and blood cell disorders",
    "Ophthalmic": "eye drops and eye ointments of any kind",
    "Dermatologic": "skin creams, ointments, topical steroids, acne, topical antifungals",
    "Nutrition and electrolytes": "vitamins, minerals, potassium, electrolytes, prenatal vitamins",
    "Medical supplies": "needles, syringes, pen needles, test strips, lancets, alcohol pads",
    "Other": "anything that clearly fits none of the classes above",
}
CLASS_NAMES = list(CLASSES)

SYSTEM_PROMPT = (
    "You are a clinical pharmacist. Classify a United States Medicare Part D drug, given by "
    "its generic name, into exactly one therapeutic class from the list. Choose the class for "
    "the drug's main use in Medicare patients. Answer only with JSON.\n\nClasses:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in CLASSES.items())
)

SCHEMA = {
    "type": "object",
    "properties": {
        "therapeutic_class": {"type": "string", "enum": CLASS_NAMES},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["therapeutic_class", "confidence"],
}


# ---------------------------------------------------------------- data

def generic_names():
    """Distinct generic names with example brands and 2024 Part D cost (for weighting)."""
    con = config.duckdb_connect(read_only=True)
    return con.execute("""
        with d as (
            select d.generic_name_norm, d.generic_name, d.brand_name, d.brand_generic,
                   sum(f.drug_cost) as drug_cost
            from marts.fact_prescriptions f join marts.dim_drug d using (drug_key)
            group by all
        )
        select generic_name_norm,
               arg_max(generic_name, drug_cost)                          as generic_name,
               string_agg(distinct brand_name, '; ')
                   filter (where brand_generic = 'Brand')                as brand_names,
               sum(drug_cost)                                            as drug_cost
        from d group by 1 order by 1""").df()


def validate(answer):
    """Return (class, confidence) if the answer matches the schema, else None."""
    try:
        obj = json.loads(answer) if isinstance(answer, str) else answer
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    cls, conf = obj.get("therapeutic_class"), obj.get("confidence")
    if cls in CLASS_NAMES and conf in ("high", "medium", "low"):
        return cls, conf
    return None


def user_message(row):
    brands = row["brand_names"] if isinstance(row["brand_names"], str) else "none"
    brands = "; ".join(brands.split("; ")[:3])
    return f"Generic name: {row['generic_name']}\nBrand names in Part D: {brands}"


# ---------------------------------------------------------------- LLM

def ask(model, row, timeout=300):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user_message(row)}],
        "format": SCHEMA,
        "stream": False,
        "options": {"temperature": 0, "seed": config.SEED, "num_predict": 60},
    }
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"]


def classify(model, limit=None):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"classes_{model.replace('/', '_').replace(':', '_')}.jsonl"
    done = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["generic_name_norm"]] = rec
    names = generic_names()
    todo = names[~names["generic_name_norm"].isin(done)]
    if limit:
        todo = todo.head(limit)
    print(f"{len(done):,} cached, {len(todo):,} to classify with {model}", flush=True)
    t0 = time.time()
    with open(cache, "a", encoding="utf-8") as f:
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            result, raw, attempts = None, None, 0
            while result is None and attempts < 2:
                attempts += 1
                raw = ask(model, row)
                result = validate(raw)
            cls, conf = result if result else ("Unclassified", "none")
            rec = {"generic_name_norm": row["generic_name_norm"], "therapeutic_class": cls,
                   "confidence": conf, "attempts": attempts, "valid_json": result is not None,
                   "model": model}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[rec["generic_name_norm"]] = rec
            if i % 50 == 0 or i == len(todo):
                rate = (time.time() - t0) / i
                print(f"  {i:,}/{len(todo):,}  {rate:.1f}s per drug, "
                      f"about {rate * (len(todo) - i) / 60:.0f} min left", flush=True)
    out = names.merge(pd.DataFrame(done.values()), on="generic_name_norm", how="left")
    out = out[["generic_name", "generic_name_norm", "therapeutic_class", "confidence",
               "valid_json", "attempts", "model", "drug_cost"]]
    if not limit:
        out.to_csv(OUT, index=False)
        print(f"wrote {OUT}")
    return out


# ---------------------------------------------------------------- validation

def sample():
    """Write the blind labeling sheet (no model output in it)."""
    GENAI_DIR.mkdir(parents=True, exist_ok=True)
    if LABEL_SHEET.exists():
        print(f"{LABEL_SHEET} already exists; not overwriting hand labels.")
        return
    names = generic_names()
    rng = np.random.default_rng(config.SEED)
    idx = rng.choice(len(names), size=SAMPLE_SIZE, replace=False)
    s = names.iloc[np.sort(idx)].reset_index(drop=True)
    sheet = pd.DataFrame({
        "sample_id": range(1, len(s) + 1),
        "generic_name": s["generic_name"],
        "example_brands": s["brand_names"].fillna("").map(lambda b: "; ".join(b.split("; ")[:3])),
        "hand_label": "",
        "notes": "",
    })
    sheet.to_csv(LABEL_SHEET, index=False)
    print(f"wrote {LABEL_SHEET} ({len(sheet)} drugs). Fill hand_label with one class from "
          "docs/genai_labeling_guide.md.")


def wilson(k, n, z=1.96):
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def evaluate():
    labels = pd.read_csv(LABEL_SHEET)
    labels["hand_label"] = labels["hand_label"].fillna("").str.strip()
    missing = labels["hand_label"].eq("").sum()
    bad = labels.loc[~labels["hand_label"].isin(CLASS_NAMES + [""]), "hand_label"].unique()
    if missing or len(bad):
        raise SystemExit(f"{missing} drugs unlabeled; labels not in the class list: {list(bad)}")
    pred = pd.read_csv(OUT)
    m = labels.merge(pred[["generic_name", "therapeutic_class", "confidence", "drug_cost"]],
                     on="generic_name", how="left")
    m["correct"] = m["hand_label"] == m["therapeutic_class"]
    n, k = len(m), int(m["correct"].sum())
    acc = k / n
    lo, hi = wilson(k, n)
    weighted = (m["correct"] * m["drug_cost"]).sum() / m["drug_cost"].sum()
    by_conf = m.groupby("confidence")["correct"].agg(["size", "mean"]).reset_index()
    accepted = bool(acc >= ACCEPT_ACCURACY)
    errors = m.loc[~m["correct"], ["generic_name", "hand_label", "therapeutic_class", "confidence"]]
    result = pd.DataFrame([
        ("model", pred["model"].iloc[0]),
        ("sample_size", n),
        ("accuracy", acc),
        ("accuracy_ci_low", lo),
        ("accuracy_ci_high", hi),
        ("cost_weighted_accuracy", weighted),
        ("acceptance_threshold", ACCEPT_ACCURACY),
        ("accepted", accepted),
        ("valid_json_rate", pred["valid_json"].mean()),
    ], columns=["metric", "value"])
    result.to_csv(config.PUBLIC_OUT / "genai_validation.csv", index=False)
    errors.to_csv(config.PUBLIC_OUT / "genai_validation_errors.csv", index=False)
    md = "\n".join([
        "## Phase 8: GenAI drug classification (validated)",
        "",
        f"A local model ({pred['model'].iloc[0]}, via Ollama) classified all "
        f"{len(pred):,} Part D generic names into {len(CLASS_NAMES)} therapeutic classes with "
        "a fixed prompt, JSON schema output, temperature 0, and a fixed seed. "
        f"{pred['valid_json'].mean():.1%} of answers were valid on the first or second try.",
        "",
        f"On a random sample of {n} generic names labeled by hand without seeing the model "
        f"output, accuracy was **{acc:.0%}** (95% CI {lo:.0%} to {hi:.0%}); weighted by 2024 "
        f"Part D cost it was {weighted:.0%}. The acceptance threshold, set before evaluation, "
        f"was {ACCEPT_ACCURACY:.0%}: the classes were "
        + ("**accepted** and are used as `therapeutic_class` in the drug dimension."
           if accepted else "**not accepted** and are not used anywhere in the analysis.")
        + "",
        "",
        "| Model confidence | Drugs in sample | Accuracy |",
        "|---|---:|---:|",
        *[f"| {r.confidence} | {r['size']} | {r['mean']:.0%} |" for _, r in by_conf.iterrows()],
        "",
        "Misclassified examples are in `outputs_public/genai_validation_errors.csv`.",
    ])
    write_section(config.DOCS_DIR / "findings.md", "genai", md)
    print(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "classify", "evaluate"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, help="classify only the first N (smoke test)")
    args = ap.parse_args()
    if args.step == "sample":
        sample()
    elif args.step == "classify":
        out = classify(args.model, args.limit)
        if args.limit:
            print(out.dropna(subset=["therapeutic_class"]).head(args.limit)[
                ["generic_name", "therapeutic_class", "confidence", "valid_json"]].to_string())
    else:
        evaluate()


if __name__ == "__main__":
    main()
