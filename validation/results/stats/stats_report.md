# ReviewAid v3.0.0 validation — auto-generated statistics report


================ DeepSeek-V2-Lite 16B (screening, N=1968) ================
[G] conservative: sensitivity 36.0% [32.6, 39.5] (n=731) | specificity 55.1% [52.3, 57.8] (n=1237)
[G] sensitivity_first: sensitivity 36.0% [32.6, 39.5] (n=731) | specificity 55.1% [52.3, 57.8] (n=1237)
[G] sensitivity, cluster bootstrap by review: 36.1% [30.5, 42.6]
[G] policy tau=0.8: auto 133, referred 1835 (WSS 6.8%), errors in auto: 39.8% [31.9, 48.3] (n=133)
[G] policy missed includes at tau: 53
[G] WSS@95 (tau, value): (None, nan) | WSS@100: (None, nan)
[B] calibration N=198: RAW Brier 0.642, ECE 0.662, AUC 0.571 -> FINAL Brier 0.221, ECE 0.192, AUC 0.658
[B] tier accuracy: tier1_deterministic: 60.2% [51.7, 68.1] (n=133); tier1_deterministic_score: 49.5% [47.1, 51.9] (n=1637); tier1_override: 26.6% [20.8, 33.3] (n=188); tier2_llm_selfassess: 40.0% [16.8, 68.7] (n=10)
[C] override-as-detector: P(err|flag)=72.7% [66.1, 78.5], P(err|no-flag)=nan% [nan, nan], detector AUC=0.694, fisher p=1 (n_flagged=198/198)
[F] conformal: no threshold reached the target bound (no threshold reached the target bound on calibration reviews)
[A] latency s/paper: median 7.5, mean 9.3; parse_ok 100.0%
[D] extraction N=2184: ungrounded fields 0.7% [0.6, 0.9] (n=8736), negation-blocked 151
[D] effect direction: acc 7.6% [5.2, 10.9] (n=342) (n=342)

================ Command-A (screening, N=1968) ================
[G] conservative: sensitivity 76.2% [73.0, 79.1] (n=731) | specificity 36.3% [33.7, 39.0] (n=1237)
[G] sensitivity_first: sensitivity 76.2% [73.0, 79.1] (n=731) | specificity 36.1% [33.5, 38.9] (n=1237)
[G] sensitivity, cluster bootstrap by review: 76.0% [65.8, 85.3]
[G] policy tau=0.8: auto 133, referred 1835 (WSS 6.8%), errors in auto: 39.8% [31.9, 48.3] (n=133)
[G] policy missed includes at tau: 53
[G] WSS@95 (tau, value): (None, nan) | WSS@100: (None, nan)
[B] calibration N=1835: RAW Brier 0.436, ECE 0.432, AUC 0.774 -> FINAL Brier 0.391, ECE 0.375, AUC 0.534
[B] tier accuracy: tier1_deterministic: 60.2% [51.7, 68.1] (n=133); tier1_override: 50.4% [48.1, 52.6] (n=1835)
[C] override-as-detector: P(err|flag)=49.6% [47.4, 51.9], P(err|no-flag)=nan% [nan, nan], detector AUC=0.540, fisher p=1 (n_flagged=1835/1835)
[F] conformal: no threshold reached the target bound (no threshold reached the target bound on calibration reviews)
[A] latency s/paper: median 6.3, mean 8.6; parse_ok 100.0%
[D] extraction N=2184: ungrounded fields 0.4% [0.3, 0.6] (n=8736), negation-blocked 833
[D] effect direction: acc 8.3% [7.2, 9.5] (n=2177) (n=2177)

================ Llama3.2-3B (local) (screening, N=1968) ================
[G] conservative: sensitivity 85.5% [82.8, 87.9] (n=731) | specificity 12.3% [10.6, 14.2] (n=1237)
[G] sensitivity_first: sensitivity 85.5% [82.8, 87.9] (n=731) | specificity 12.3% [10.6, 14.2] (n=1237)
[G] sensitivity, cluster bootstrap by review: 85.4% [79.9, 90.0]
[G] policy tau=0.8: auto 133, referred 1835 (WSS 6.8%), errors in auto: 39.8% [31.9, 48.3] (n=133)
[G] policy missed includes at tau: 53
[G] WSS@95 (tau, value): (None, nan) | WSS@100: (None, nan)
[B] calibration N=1818: RAW Brier 0.485, ECE 0.475, AUC 0.487 -> FINAL Brier 0.277, ECE 0.228, AUC 0.640
[B] tier accuracy: tier1_deterministic: 60.2% [51.7, 68.1] (n=133); tier1_deterministic_score: 47.1% [26.2, 69.0] (n=17); tier1_override: 36.6% [34.3, 39.0] (n=1598); tier2_llm_selfassess: 47.3% [40.8, 53.9] (n=220)
[C] override-as-detector: P(err|flag)=62.1% [59.8, 64.3], P(err|no-flag)=nan% [nan, nan], detector AUC=0.656, fisher p=1 (n_flagged=1818/1818)
[F] conformal: no threshold reached the target bound (no threshold reached the target bound on calibration reviews)
[A] latency s/paper: median 16.2, mean 17.1; parse_ok 100.0%
[D] extraction N=2184: ungrounded fields 5.1% [4.6, 5.6] (n=8736), negation-blocked 467
[D] effect direction: acc 14.2% [12.8, 15.8] (n=2122) (n=2122)

[E] capability -> workload:
    DeepSeek-V2-Lite 16B: referral 93.2%, auto-processed error 39.85% [31.93, 48.34], WSS 6.8%
    Command-A: referral 93.2%, auto-processed error 39.85% [31.93, 48.34], WSS 6.8%
    Llama3.2-3B (local): referral 93.2%, auto-processed error 39.85% [31.93, 48.34], WSS 6.8%
    ollamads_vs_cohere: diff 0.00 pp, within +-3 pp margin: True
    ollama_vs_ollamads: diff 0.00 pp, within +-3 pp margin: True
    ollama_vs_cohere: diff 0.00 pp, within +-3 pp margin: True

[H] adjudicated audit (human verdicts on the published gold labels):
    verdicts by stratum (yes = gold correct, no = gold wrong):
      concordant_sample: yes=88
      false_negative: yes=535
      false_positive: yes=1144
    DeepSeek-V2-Lite 16B: gold overturned for 0.0% [0.0, 0.2] (n=1767) of adjudicated papers
    ollamads: accuracy raw 48.0% [45.8, 50.2] -> adjudicated 48.0% [45.8, 50.2]; 0 decisions reclassified
    ollamads: sensitivity raw 36.0% [32.6, 39.5] -> adjudicated 36.0% [32.6, 39.5]; specificity raw 55.1% [52.3, 57.8] -> adjudicated 55.1% [52.3, 57.8]
    Command-A: gold overturned for 0.0% [0.0, 0.2] (n=1767) of adjudicated papers
    cohere: accuracy raw 51.0% [48.8, 53.2] -> adjudicated 51.0% [48.8, 53.2]; 0 decisions reclassified
    cohere: sensitivity raw 76.2% [73.0, 79.1] -> adjudicated 76.2% [73.0, 79.1]; specificity raw 36.3% [33.7, 39.0] -> adjudicated 36.3% [33.7, 39.0]
    Llama3.2-3B (local): gold overturned for 0.0% [0.0, 0.2] (n=1767) of adjudicated papers
    ollama: accuracy raw 39.5% [37.3, 41.7] -> adjudicated 39.5% [37.3, 41.7]; 0 decisions reclassified
    ollama: sensitivity raw 85.5% [82.8, 87.9] -> adjudicated 85.5% [82.8, 87.9]; specificity raw 12.3% [10.6, 14.2] -> adjudicated 12.3% [10.6, 14.2]
