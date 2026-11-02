"""Performance and subgroup review of a (synthetic) AI chest X-ray triage tool. Standard library only."""
import csv, json, random, math
random.seed(7)
N, PREV, THRESH = 8000, 0.08, 0.5

def sigmoid(x): return 1 / (1 + math.exp(-x))
def make():
    rows = []
    for i in range(N):
        sex = random.choice(["Female", "Male"])
        age = random.choices(["18-44", "45-64", "65-79", "80 plus"], [0.30, 0.35, 0.25, 0.10])[0]
        site = random.choices(["Hospital A (new scanner)", "Hospital B (old scanner)", "Rural clinic"], [0.5, 0.3, 0.2])[0]
        dz = 1 if random.random() < PREV * (1.6 if age in ("65-79", "80 plus") else 0.8) else 0
        # signal strength: the model works well on its training population, worse elsewhere
        d = 2.6
        if site.startswith("Hospital B"): d -= 0.9
        if site == "Rural clinic": d -= 0.6
        if age == "80 plus": d -= 0.7
        if sex == "Female": d -= 0.2
        logit = -1.2 + d * dz + random.gauss(0, 1.0)
        rows.append(dict(id=i, sex=sex, age_band=age, site=site, disease=dz, score=round(sigmoid(logit), 4)))
    return rows

def auc(rows):
    pos = [r["score"] for r in rows if r["disease"]]; neg = [r["score"] for r in rows if not r["disease"]]
    pairs = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]: j += 1
        avg = (i + 1 + j) / 2
        rank_sum += avg * sum(p[1] for p in pairs[i:j]); i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))

def metrics(rows):
    tp = sum(r["disease"] and r["score"] >= THRESH for r in rows); fn = sum(r["disease"] and r["score"] < THRESH for r in rows)
    fp = sum((not r["disease"]) and r["score"] >= THRESH for r in rows); tn = sum((not r["disease"]) and r["score"] < THRESH for r in rows)
    return dict(n=len(rows), sens=round(100 * tp / max(1, tp + fn), 1), spec=round(100 * tn / max(1, tn + fp), 1),
                ppv=round(100 * tp / max(1, tp + fp), 1), auc=round(auc(rows), 3), missed=fn, prevalence=round(100 * (tp + fn) / len(rows), 1))

rows = make()
with open("data/cases.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
overall = metrics(rows)
sub = {}
for attr in ("sex", "age_band", "site"):
    for g in sorted({r[attr] for r in rows}):
        sub[f"{attr}: {g}"] = metrics([r for r in rows if r[attr] == g])
# calibration: predicted risk bins vs observed
cal = []
for lo in [0, .2, .4, .6, .8]:
    b = [r for r in rows if lo <= r["score"] < lo + .2 + (0.001 if lo == .8 else 0)]
    if b: cal.append(dict(bin=f"{lo:.1f}-{lo+.2:.1f}", n=len(b), predicted=round(100 * sum(r["score"] for r in b) / len(b), 1), observed=round(100 * sum(r["disease"] for r in b) / len(b), 1)))
json.dump(dict(overall=overall, subgroups=sub, calibration=cal), open("data/review_results.json", "w"), indent=1)
print(overall)

best = max(v["sens"] for v in sub.values())
def st(v): return "good" if v >= 85 else "warn" if v >= 75 else "bad"
tbl = [[k, v["n"], v["sens"], v["spec"], v["ppv"], v["auc"], "PASS" if v["sens"] >= 85 else "WARN" if v["sens"] >= 75 else "FAIL"] for k, v in sub.items()]
worst = min(sub.items(), key=lambda kv: kv[1]["sens"])
spec = {"title": "AI Chest X-Ray Triage Tool: Clinical Governance Review", "subtitle": f"{N:,} synthetic cases, disease prevalence about {overall['prevalence']}%, decision threshold {THRESH}. Minimum acceptable sensitivity per subgroup: 85%.",
 "kpis": [{"label": "Overall sensitivity", "value": f"{overall['sens']}%", "status": st(overall["sens"]), "note": "below the 85% minimum even before subgroups"},
          {"label": "Worst subgroup sensitivity", "value": f"{worst[1]['sens']}%", "status": st(worst[1]["sens"]), "note": worst[0]},
          {"label": "Positive predictive value", "value": f"{overall['ppv']}%", "status": "warn", "note": "most alerts are false at this prevalence"},
          {"label": "Missed cases", "value": overall["missed"], "status": "bad", "note": f"of {round(N*overall['prevalence']/100)} true cases"}],
 "verdict": {"status": "warn", "label": "Recommendation: do not approve for triage. Limited pilot only.", "text": "Sensitivity collapses on the old scanner (56.6%), in patients 80 plus (48.3%) and at the rural clinic (65.7%). Risk scores are also overconfident: a 40 to 60% score corresponds to 12% real disease. Allow a second-reader pilot at the validated site only, never as a rule-out tool."},
 "charts": [{"title": "Sensitivity by subgroup (%)", "unit": "%", "max": 100, "threshold": {"value": 85, "label": "85% minimum"}, "items": [{"label": k.split(": ")[1], "value": v["sens"], "status": st(v["sens"])} for k, v in sub.items()]},
            {"title": "Calibration: predicted vs observed disease rate (%)", "unit": "%", "max": 100, "items": [x for c in cal for x in ({"label": f"Risk {c['bin']} predicted", "value": c["predicted"], "status": "info"}, {"label": f"Risk {c['bin']} observed", "value": c["observed"], "status": "warn" if abs(c["predicted"]-c["observed"]) > 10 else "good"})]}],
 "tables": [{"title": "Subgroup performance", "columns": ["Subgroup", "N", "Sensitivity %", "Specificity %", "PPV %", "AUC", "Gate"], "rows": tbl}]}
json.dump(spec, open("data/dashboard_spec.json", "w"), indent=1)
