"""Clinical validation statistics for the synthetic chest X-ray triage tool: CIs, significance, calibration, local threshold tuning, workload."""
import json, numpy as np, pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
rng = np.random.default_rng(3)
df = pd.read_csv("data/cases.csv"); T = 0.5
def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); a = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return ((c - a) / d, (c + a) / d)
def perf(d, thr=T):
    pos, neg = d[d.disease == 1], d[d.disease == 0]
    tp, fn = int((pos.score >= thr).sum()), int((pos.score < thr).sum()); fp, tn = int((neg.score >= thr).sum()), int((neg.score < thr).sum())
    s = wilson(tp, tp + fn)
    return dict(n=len(d), pos=len(pos), sens=100 * tp / max(1, tp + fn), sens_lo=100 * s[0], sens_hi=100 * s[1], spec=100 * tn / max(1, tn + fp),
                ppv=100 * tp / max(1, tp + fp), npv=100 * tn / max(1, tn + fn), auc=roc_auc_score(d.disease, d.score) if d.disease.nunique() > 1 else np.nan,
                alert_rate=100 * (tp + fp) / len(d), missed=fn)
R = {"threshold": T, "overall": perf(df), "subgroups": {}, "tests": {}, "calibration": {}, "tuning": [], "scale": {}}
for attr in ("sex", "age_band", "site"):
    for g in sorted(df[attr].unique()): R["subgroups"][f"{attr}|{g}"] = perf(df[df[attr] == g])
def sens_test(a, b):  # Fisher exact on positives: detected vs missed
    pa, pb = df[a].query("disease==1"), df[b].query("disease==1")
    t = [[int((pa.score >= T).sum()), int((pa.score < T).sum())], [int((pb.score >= T).sum()), int((pb.score < T).sum())]]
    return float(stats.fisher_exact(t)[1])
R["tests"] = {"Hospital B vs Hospital A": sens_test(df.site == "Hospital B (old scanner)", df.site == "Hospital A (new scanner)"),
              "Rural clinic vs Hospital A": sens_test(df.site == "Rural clinic", df.site == "Hospital A (new scanner)"),
              "Age 80 plus vs 18-44": sens_test(df.age_band == "80 plus", df.age_band == "18-44"), "Female vs Male": sens_test(df.sex == "Female", df.sex == "Male")}
# calibration
lg = np.log(df.score / (1 - df.score)).values.reshape(-1, 1); m = LogisticRegression(C=1e6).fit(lg, df.disease)
bins = np.linspace(0, 1, 11); idx = np.digitize(df.score, bins[1:-1]); ece = 0; rows = []
for b in range(10):
    s = df[idx == b]
    if len(s): ece += len(s) / len(df) * abs(s.score.mean() - s.disease.mean()); rows.append(dict(bin=f"{bins[b]:.1f}-{bins[b+1]:.1f}", n=len(s), predicted=100 * s.score.mean(), observed=100 * s.disease.mean()))
R["calibration"] = dict(brier=brier_score_loss(df.disease, df.score), ece=100 * ece, slope=float(m.coef_[0][0]), intercept=float(m.intercept_[0]), bins=rows)
# local threshold tuning with a holdout (tune on half, evaluate on the other half)
df["half"] = rng.random(len(df)) < 0.5
for name, mask in [("Hospital A (new scanner)", df.site == "Hospital A (new scanner)"), ("Hospital B (old scanner)", df.site == "Hospital B (old scanner)"), ("Rural clinic", df.site == "Rural clinic"), ("Age 80 plus", df.age_band == "80 plus")]:
    tune, test = df[mask & df.half], df[mask & ~df.half]
    cand = np.linspace(0.02, 0.9, 89); best = None
    for t in cand[::-1]:
        if perf(tune, t)["sens"] >= 85: best = t; break
    base, tuned = perf(test, T), (perf(test, best) if best else None)
    R["tuning"].append(dict(group=name, threshold=best, base=base, tuned=tuned))
# annual impact projection
vol = 60000; R["scale"] = dict(volume=vol, prevalence=100 * df.disease.mean(), missed_per_year=round(vol * R["overall"]["missed"] / len(df)),
        flagged_per_year=round(vol * R["overall"]["alert_rate"] / 100))
json.dump(R, open("data/clinical_stats.json", "w"), indent=1, default=float)
o = R["overall"]; print({k: round(v, 1) for k, v in o.items()}); print(R["calibration"]["slope"], R["calibration"]["ece"], R["calibration"]["brier"]); print(R["tests"]); print(R["scale"])
for k, v in R["subgroups"].items(): print(k, round(v["sens"], 1), round(v["sens_lo"], 1), round(v["sens_hi"], 1))
for t in R["tuning"]: print(t["group"], t["threshold"], round(t["base"]["sens"], 1), t["tuned"] and (round(t["tuned"]["sens"], 1), round(t["tuned"]["spec"], 1), round(t["tuned"]["ppv"], 1), round(t["tuned"]["alert_rate"], 1)), "base alert", round(t["base"]["alert_rate"], 1), "base ppv", round(t["base"]["ppv"], 1))
