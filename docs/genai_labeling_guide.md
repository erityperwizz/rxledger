# GenAI Validation: Hand Labeling Guide

Author: Erica Mathias

`analysis/genai/hand_labels.csv` holds 100 Part D generic names drawn at random (seed 2024). Label each one by hand **before looking at any model output**, so the accuracy measured in Phase 8 is an honest, blind comparison.

## How to label

1. Open `analysis/genai/hand_labels.csv` in Excel (keep it as CSV when saving).
2. For each row, type one class name from the table below into `hand_label`, spelled
   exactly as shown (copy and paste is safest).
3. Choose the class for the drug's main use in Medicare patients. `example_brands` is
   there to help; look up anything unfamiliar (for example on MedlinePlus or
   DailyMed).
4. If a drug fits two classes, pick the more common use and write the alternative in
   `notes`.
5. Do not open `outputs_public/genai_drug_classes.csv` or the classification cache
   until every row is labeled.

The acceptance threshold is fixed in advance at **85% accuracy**. If the model falls short, the classes are not used and the README reports that honestly.

## Classes

| Class | Includes |
|---|---|
| Cardiovascular | blood pressure, heart failure, angina, arrhythmia, diuretics |
| Lipid lowering | statins, ezetimibe, PCSK9 inhibitors, fibrates, omega-3 prescription |
| Anticoagulant and antiplatelet | warfarin, DOACs such as apixaban, heparins, clopidogrel |
| Diabetes | insulins, metformin, GLP-1, SGLT2, DPP-4, sulfonylureas, diabetes supplies are NOT here |
| Endocrine and hormones | thyroid, osteoporosis, corticosteroids taken by mouth, sex hormones, contraceptives, growth hormone |
| Respiratory and allergy | asthma and COPD inhalers, montelukast, antihistamines, nasal steroids |
| Mental health | antidepressants, antipsychotics, anxiolytics, sedative hypnotics, ADHD stimulants, lithium |
| Neurology | anticonvulsants, Parkinson's, dementia, migraine, multiple sclerosis, muscle relaxants |
| Pain and anesthesia | opioid analgesics, NSAIDs, acetaminophen combinations, gout, local anesthetics |
| Substance use disorder | buprenorphine and naloxone, naltrexone, varenicline, nicotine replacement |
| Anti-infective | antibiotics, antivirals including HIV and hepatitis, antifungals, antiparasitics |
| Vaccine | any vaccine or immune globulin given for prevention |
| Cancer | chemotherapy, targeted cancer drugs, hormone therapy for cancer |
| Immunology | biologics and small molecules for rheumatoid arthritis, psoriasis, IBD; transplant immunosuppressants |
| Gastrointestinal | acid reducers, antiemetics, laxatives, antidiarrheals, pancreatic enzymes, ursodiol |
| Kidney and urology | overactive bladder, BPH, erectile dysfunction, phosphate binders, kidney disease drugs |
| Hematology | iron, anemia, clotting factors, sickle cell, platelet and blood cell disorders |
| Ophthalmic | eye drops and eye ointments of any kind |
| Dermatologic | skin creams, ointments, topical steroids, acne, topical antifungals |
| Nutrition and electrolytes | vitamins, minerals, potassium, electrolytes, prenatal vitamins |
| Medical supplies | needles, syringes, pen needles, test strips, lancets, alcohol pads |
| Other | anything that clearly fits none of the classes above |
