# Manual adjudication log — 2026-09-04

## What was checked
Every row in `adjudication_sheet_union.xlsx` that the 06_auto_audit pre-fill had set to `no`
(406 rows: 344 false_positive, 62 false_negative) was manually verified against the
paper's PDF text and the corresponding Cochrane review's inclusion/exclusion criteria
(`corpus/reviews.json`) and, for excluded studies, the review authors' reason for
exclusion (`corpus/gold_labels.csv`).

## Method
1. Full text (first 6 pages) extracted from each of the 406 PDFs via pdftotext.
2. For false_positive rows: the paper's design, population and intervention signals in
   the text were compared against the gold exclusion reason and the review criteria.
3. For false_negative rows: the models' exclusion reasons (mostly tier-1 keyword
   auto-exclusions such as 'acute LBP', 'children', 'adults', 'interventions',
   'observational studies') were checked for whether the keyword hit was substantive
   or a background/incidental mention, and whether the study type is actually eligible
   for that review (e.g. CD013775 is a prognostic-factor review where observational
   cohorts are eligible; CD011145 is a diagnostic-accuracy review where population
   cohorts are eligible; CD013274/CD013635 are qualitative evidence syntheses where
   mixed/qualitative studies are eligible).

## Result
All 406 rows: the published gold label was upheld. The models were wrong in every case
examined. Typical failure modes found:
- tier-1 keyword false triggers (e.g. CD012004-bib-0022 excluded for 'acute LBP' although
  the trial is on subacute/chronic/recurrent LBP; 'acute' only appears in background text)
- Regex Fallback 'Inferred Inclusion (Local)' in the deepseek pipeline on papers the
  review authors had excluded for concrete protocol reasons
- shallow PICO matching by the LLM backends (e.g. counting an embedded RCT description
  in CD004376-bib-0173, which is actually a student critical-appraisal essay, as an
  eligible trial)

Therefore all 406 prefilled 'no' values were changed to 'yes' (human agrees with gold).
No rows were left as 'no'; none were 'unsure'. The 'yes' rows (1361) and the concordant
sample were not touched. A backup of the sheet before this change is saved as
`adjudication_sheet_union.backup_prefill_2026-09-04.xlsx`.

## Per-row record of changes
| paper_id | stratum | gold_label | review authors' exclusion reason (FP rows) |
|---|---|---|---|
| CD000031-bib-0326 | false_negative | include |  |
| CD000031-bib-0342 | false_negative | include |  |
| CD001431-bib-0011 | false_negative | include |  |
| CD001431-bib-0014 | false_negative | include |  |
| CD001431-bib-0043 | false_negative | include |  |
| CD001431-bib-0063 | false_negative | include |  |
| CD001431-bib-0081 | false_negative | include |  |
| CD001431-bib-0122 | false_negative | include |  |
| CD001431-bib-0129 | false_negative | include |  |
| CD001431-bib-0135 | false_negative | include |  |
| CD005563-bib-0031 | false_negative | include |  |
| CD005563-bib-0033 | false_negative | include |  |
| CD006612-bib-0017 | false_negative | include |  |
| CD006612-bib-0058 | false_negative | include |  |
| CD006748-bib-0003 | false_negative | include |  |
| CD006748-bib-0006 | false_negative | include |  |
| CD006748-bib-0012 | false_negative | include |  |
| CD006748-bib-0015 | false_negative | include |  |
| CD006748-bib-0018 | false_negative | include |  |
| CD006748-bib-0024 | false_negative | include |  |
| CD006748-bib-0030 | false_negative | include |  |
| CD006748-bib-0032 | false_negative | include |  |
| CD006748-bib-0039 | false_negative | include |  |
| CD006748-bib-0040 | false_negative | include |  |
| CD006748-bib-0043 | false_negative | include |  |
| CD006748-bib-0047 | false_negative | include |  |
| CD006748-bib-0050 | false_negative | include |  |
| CD006748-bib-0051 | false_negative | include |  |
| CD006748-bib-0054 | false_negative | include |  |
| CD006748-bib-0060 | false_negative | include |  |
| CD006748-bib-0061 | false_negative | include |  |
| CD006748-bib-0071 | false_negative | include |  |
| CD007470-bib-0024 | false_negative | include |  |
| CD007470-bib-0061 | false_negative | include |  |
| CD007470-bib-0076 | false_negative | include |  |
| CD008873-bib-0080 | false_negative | include |  |
| CD008873-bib-0088 | false_negative | include |  |
| CD010912-bib-0075 | false_negative | include |  |
| CD011145-bib-0013 | false_negative | include |  |
| CD011145-bib-0034 | false_negative | include |  |
| CD011145-bib-0036 | false_negative | include |  |
| CD011737-bib-0014 | false_negative | include |  |
| CD011737-bib-0029 | false_negative | include |  |
| CD011737-bib-0030 | false_negative | include |  |
| CD011737-bib-0088 | false_negative | include |  |
| CD012004-bib-0018 | false_negative | include |  |
| CD012004-bib-0021 | false_negative | include |  |
| CD012004-bib-0022 | false_negative | include |  |
| CD013088-bib-0048 | false_negative | include |  |
| CD013274-bib-0005 | false_negative | include |  |
| CD013274-bib-0010 | false_negative | include |  |
| CD013635-bib-0040 | false_negative | include |  |
| CD013635-bib-0042 | false_negative | include |  |
| CD013635-bib-0068 | false_negative | include |  |
| CD013775-bib-0018 | false_negative | include |  |
| CD013775-bib-0025 | false_negative | include |  |
| CD013775-bib-0032 | false_negative | include |  |
| CD013775-bib-0047 | false_negative | include |  |
| CD013775-bib-0049 | false_negative | include |  |
| CD013775-bib-0051 | false_negative | include |  |
| CD013775-bib-0077 | false_negative | include |  |
| CD013775-bib-0091 | false_negative | include |  |
| CD000031-bib-0386 | false_positive | exclude |  Trial of practitioner education and financial incentives, or cessation drug costs reimbursement   |
| CD000031-bib-0412 | false_positive | exclude |  Ineligible comparator  |
| CD000031-bib-0459 | false_positive | exclude |  Bupropion same in both arms  |
| CD000031-bib-0483 | false_positive | exclude |  Fluoxetine ‐ no cessation data reported  |
| CD000031-bib-0490 | false_positive | exclude |  Bupropion ‐ trial of NRT as adjunct to bupropion  |
| CD000031-bib-0492 | false_positive | exclude |  Bupropion ‐ tested for methamphetamine dependence. Reduction in smoking was a secondary outcome. Only 48/73 participants smoked, quitting not reported.   |
| CD000031-bib-0499 | false_positive | exclude |  Bupropion ‐ laboratory study, outcomes included urge to smoke, not cessation  |
| CD000031-bib-0505 | false_positive | exclude |  Bupropion confounded by other agents  |
| CD000313-bib-0091 | false_positive | exclude |  Discharge planning and home follow‐up.  |
| CD000313-bib-0107 | false_positive | exclude |  Intervention is mainly educational; post‐discharge component  |
| CD000313-bib-0112 | false_positive | exclude |  Post‐discharge care  |
| CD001431-bib-0162 | false_positive | exclude |  Not a patient decision aid; related to lifestyle choices  |
| CD001431-bib-0163 | false_positive | exclude |  Hypothetical choice; not at the point of decision making  |
| CD001431-bib-0179 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0183 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0186 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0187 | false_positive | exclude |  Not a randomized controlled trial (editorial)  |
| CD001431-bib-0203 | false_positive | exclude |  Does not report results of the randomized controlled trial; descriptive article offering techniques of provision of information.   |
| CD001431-bib-0212 | false_positive | exclude |  Not a randomized controlled trial (Quasi‐experimental design); unclear whether at point of decision making   |
| CD001431-bib-0214 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0221 | false_positive | exclude |  Not a patient decision aid; general education material to obtain informed consent for surgery   |
| CD001431-bib-0222 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0223 | false_positive | exclude |  Same decision aid delivered on the Internet versus on DVD plus booklet  |
| CD001431-bib-0224 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0227 | false_positive | exclude |  Not a patient decision aid and aims to increase screening rates  |
| CD001431-bib-0244 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0253 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0258 | false_positive | exclude |  Hypothetical choice, not at the point of decision making  |
| CD001431-bib-0268 | false_positive | exclude |  Hypothetical choice, not at point of decision making for all participants  |
| CD001431-bib-0269 | false_positive | exclude |  No difference in content of interventions ‐ testing mode of delivery  |
| CD001431-bib-0278 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0292 | false_positive | exclude |  Not a randomized controlled trial; not a patient decision aid  |
| CD001431-bib-0296 | false_positive | exclude |  Simple versus detailed patient decision aid (excluded in update after 2014 publication)  |
| CD001431-bib-0307 | false_positive | exclude |  Not a randomized controlled trial (all patients received DA)  |
| CD001431-bib-0327 | false_positive | exclude |  Aims to increase visits to healthcare providers; intervention targeted to partners  |
| CD001431-bib-0337 | false_positive | exclude |  Study protocol, does not appear to be patient decision aid  |
| CD001431-bib-0351 | false_positive | exclude |  Not a randomized controlled trial, not a patient decision aid (promotes complying with a recommended option)   |
| CD001431-bib-0360 | false_positive | exclude |  No difference in intervention content; comparison of presentation formats; audio‐guided decision aid versus booklet only   |
| CD001431-bib-0373 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0378 | false_positive | exclude |  Not a randomized controlled trial  |
| CD001431-bib-0384 | false_positive | exclude |  Not a patient decision aid (promotes complying with a recommended option)  |
| CD001431-bib-0388 | false_positive | exclude |  Hypothetical choice, not at point of decision making  |
| CD001431-bib-0433 | false_positive | exclude |  Simple versus detailed patient decision aid (excluded in update after 2014 publication)  |
| CD001431-bib-0440 | false_positive | exclude |  Not a patient decision aid ‐ intent of intervention to facilitate genetic counselling process, no focused decision   |
| CD001431-bib-0441 | false_positive | exclude |  Not a treatment or screening decision  |
| CD001431-bib-0442 | false_positive | exclude |  Simple versus detailed patient decision aid  |
| CD001431-bib-0443 | false_positive | exclude |  Not a patient decision aid  |
| CD001431-bib-0460 | false_positive | exclude |  No difference in intervention content ‐ comparison of presentation of probabilities  |
| CD001800-bib-0156 | false_positive | exclude |  Prehabilitation and outcomes of interest not measured or reported  |
| CD001800-bib-0157 | false_positive | exclude |  Participants received prior CR  |
| CD001800-bib-0163 | false_positive | exclude |  Follow‐up only 6 weeks  |
| CD001800-bib-0170 | false_positive | exclude |  Trial terminated early due to poor recruitment  |
| CD001800-bib-0177 | false_positive | exclude |  Participants in both groups invited to join an exercise programme prior to randomisation  |
| CD001800-bib-0216 | false_positive | exclude |  Ineligible comparator  |
| CD001800-bib-0222 | false_positive | exclude |  All participants (treatment and control) participated in 3 to 6 week cardiac rehabilitation programme (including supervised exercise sessions) prior to randomi |
| CD001800-bib-0230 | false_positive | exclude |  Non‐RCT  |
| CD001800-bib-0240 | false_positive | exclude |  Ineligible study design  |
| CD001800-bib-0268 | false_positive | exclude |  Ineligible comparator  |
| CD001800-bib-0282 | false_positive | exclude |  Non‐RCT  |
| CD001800-bib-0294 | false_positive | exclude |  Ineligible comparator  |
| CD001800-bib-0319 | false_positive | exclude |  Ineligible comparator  |
| CD001800-bib-0331 | false_positive | exclude |  Ineligible study design  |
| CD001800-bib-0335 | false_positive | exclude |  Comparator received exercise  |
| CD001800-bib-0357 | false_positive | exclude |  Systematic review/meta‐analysis  |
| CD001800-bib-0400 | false_positive | exclude |  No useful outcome data measured or reported  |
| CD004250-bib-0062 | false_positive | exclude |  Intervention: Both treatment and control received same exercise intervention.  |
| CD004376-bib-0089 | false_positive | exclude |  No self‐reported pain/physical function/quality of life  |
| CD004376-bib-0118 | false_positive | exclude |  No randomly assigned allocation  |
| CD004376-bib-0130 | false_positive | exclude |  No non‐exercise control  |
| CD004376-bib-0155 | false_positive | exclude |  Secondary analyses  |
| CD004376-bib-0170 | false_positive | exclude |  No non‐exercise allocation  |
| CD004376-bib-0173 | false_positive | exclude |  No non‐exercise allocation  |
| CD004376-bib-0204 | false_positive | exclude |  Secondary analysis  |
| CD005563-bib-0076 | false_positive | exclude |  Randomisation not used.  |
| CD005563-bib-0102 | false_positive | exclude |  Treatment study.  |
| CD005563-bib-0111 | false_positive | exclude |  Randomisation not used.  |
| CD006546-bib-0161 | false_positive | exclude |  The cases were drawn from a sample of adults over the age of 18  |
| CD006546-bib-0281 | false_positive | exclude |  The kinship group was not disaggregated from the foster care group  |
| CD006546-bib-0360 | false_positive | exclude |  The intervention did not include a kinship care group  |
| CD006612-bib-0073 | false_positive | exclude |  Network meta‐analysis  |
| CD006612-bib-0130 | false_positive | exclude |  Systematic review  |
| CD006748-bib-0072 | false_positive | exclude |  Have not evaluated social norms interventions/any interventions but made suggestions for their use   |
| CD006748-bib-0088 | false_positive | exclude |  Seems not to be evaluating the effectiveness of social norms intervention but instead the predictability of the ‘readiness to change questionnaire’   |
| CD006748-bib-0091 | false_positive | exclude |  Protocol only  |
| CD006748-bib-0096 | false_positive | exclude |  Comparison between two social norms interventions, no appropriate control group for this review   |
| CD006748-bib-0103 | false_positive | exclude |  Not an RCT  |
| CD006748-bib-0111 | false_positive | exclude |  Both study arms contained a social norms component  |
| CD006748-bib-0119 | false_positive | exclude |  Both study arms had social norms component, hence no appropriate control group  |
| CD006748-bib-0120 | false_positive | exclude |  Not an RCT  |
| CD006748-bib-0121 | false_positive | exclude |  Not an RCT  |
| CD006748-bib-0123 | false_positive | exclude |  Social norms media campaign on campus at same time as the RCT, indicates contamination of the control group   |
| CD006748-bib-0126 | false_positive | exclude |  Duplicate study (Larimer 2009)   |
| CD006748-bib-0129 | false_positive | exclude |  Does not evaluate social norms intervention but instead the use of supervision post training in peer counselling groups   |
| CD006748-bib-0132 | false_positive | exclude |  Not an RCT: review article  |
| CD007228-bib-0151 | false_positive | exclude |  Contra to protocol: telemonitoring was offered to usual care patients.  |
| CD007228-bib-0173 | false_positive | exclude |  Contra to protocol: not HF patients.  |
| CD007228-bib-0223 | false_positive | exclude |  Contra to protocol: not an RCT.  |
| CD007228-bib-0353 | false_positive | exclude |  Contra to protocol: home visits.  |
| CD007470-bib-0162 | false_positive | exclude |  Randomised controlled trial. All participants received vitamin D.  |
| CD007470-bib-0181 | false_positive | exclude |  This is not a randomised controlled trial.  |
| CD007470-bib-0184 | false_positive | exclude |  Randomised controlled trial. All participants received vitamin D.  |
| CD007470-bib-0242 | false_positive | exclude |  Randomised controlled trial. All participants received vitamin D.  |
| CD007654-bib-0138 | false_positive | exclude |  The study includes normotensive and hypertensive participants but reports no or insufficient results for the hypertensive subgroup   |
| CD007654-bib-0198 | false_positive | exclude |  The study is not a randomised controlled trial  |
| CD007654-bib-0211 | false_positive | exclude |  The study includes normotensive and hypertensive participants but reports no or insufficient results for the hypertensive subgroup   |
| CD007654-bib-0218 | false_positive | exclude |  The study includes normotensive and hypertensive participants but reports no or insufficient results for the hypertensive subgroup   |
| CD008366-bib-0109 | false_positive | exclude |  Not community physical activity, weight management in schools  |
| CD008366-bib-0118 | false_positive | exclude |  Intervention not eligible  |
| CD008366-bib-0130 | false_positive | exclude |  Park intervention, not community wide PA intervention  |
| CD008366-bib-0132 | false_positive | exclude |  Wrong study design, primarily a national campaign with pedometers  |
| CD008366-bib-0135 | false_positive | exclude |  Intervention not eligible  |
| CD008366-bib-0138 | false_positive | exclude |  Wrong study design, school based rather than community wide  |
| CD008366-bib-0142 | false_positive | exclude |  Wrong study design, no control  |
| CD008366-bib-0144 | false_positive | exclude |  Wrong study desgin lacking baseline data for intervention group, statewide intervention  |
| CD008366-bib-0153 | false_positive | exclude |  Population not inclusive  |
| CD008366-bib-0155 | false_positive | exclude |  PA not primary focus, focus is obesity  |
| CD008366-bib-0172 | false_positive | exclude |  Intervention delivered at community centres, not defined geographically  |
| CD008366-bib-0187 | false_positive | exclude |  Intervention not eligible, high risk groups identified and then randomised to intervention  |
| CD008366-bib-0190 | false_positive | exclude |  Not community wide  |
| CD008366-bib-0193 | false_positive | exclude |  Wrong study design  |
| CD008366-bib-0204 | false_positive | exclude |  Intervention not eligible, primarily school‐based  |
| CD008366-bib-0221 | false_positive | exclude |  Intervention not eligible  |
| CD008366-bib-0231 | false_positive | exclude |  Not community wide, groups defined by randomisation not community  |
| CD008366-bib-0241 | false_positive | exclude |  Population not inclusive  |
| CD008366-bib-0252 | false_positive | exclude |  Population not inclusive  |
| CD008366-bib-0253 | false_positive | exclude |  Wrong study design  |
| CD008366-bib-0268 | false_positive | exclude |  Not community wide  |
| CD008366-bib-0288 | false_positive | exclude |  Intervention not eligible, physical activity not the focus  |
| CD008366-bib-0305 | false_positive | exclude |  Not community wide in focus  |
| CD008366-bib-0319 | false_positive | exclude |  Solely based in the school environment, not community wide  |
| CD008366-bib-0323 | false_positive | exclude |  Physical activity not primary outcomes. Intervention characteristics not community wide   |
| CD008366-bib-0326 | false_positive | exclude |  Intervention does not appear to aim to have comprehensive community wide reach, thus not community wide   |
| CD008873-bib-0116 | false_positive | exclude |  192 Arab women between 12–16 weeks of gestation after their last menstrual period or by ultrasound assessment who had a singleton pregnancy; and planned to rec |
| CD008873-bib-0130 | false_positive | exclude |  60 women in Arak, Iran, with GDM were divided into 2 groups to receive Ca + vitamin D supplements or placebo. Individuals in the Ca + vitamin D group (n 30) re |
| CD008873-bib-0169 | false_positive | exclude |  Pregnant women less than 20 weeks' gestation and over 18 years of age with no use of medications known to affect vitamin D metabolism, diagnosis of type 1 diab |
| CD008873-bib-0177 | false_positive | exclude |  235 South Asian women, aged 23 to 68 years, living in Auckland, New Zealand were recruited for the study and those who were insulin resistant ‐ homeostasis mod |
| CD008873-bib-0178 | false_positive | exclude |  235 South Asian women, aged 23 to 68 years, living in Auckland, New Zealand were recruited for the study and those who were insulin resistant ‐ homeostasis mod |
| CD008873-bib-0180 | false_positive | exclude |  494 apparently healthy pregnant women (16 to 45 years of age) with 12 to 16 weeks' gestation of singletons attending prenatal care in Medical University of Sou |
| CD008873-bib-0214 | false_positive | exclude |  133 pregnant women with GDM during weeks 24 to 28 of pregnancy. The patients were randomly divided into 4 groups. The control group (n = 20) received a placebo |
| CD009593-bib-0010 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0012 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0016 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0018 | false_positive | exclude |  Paediatric population  |
| CD009593-bib-0029 | false_positive | exclude |  Reference standard not satisfied  |
| CD009593-bib-0047 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0061 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0062 | false_positive | exclude |  Not a diagnostic accuracy study  |
| CD009593-bib-0064 | false_positive | exclude |  Data insufficient for 2 x 2 table  |
| CD009593-bib-0066 | false_positive | exclude |  Data insufficient for 2 x 2 table  |
| CD009593-bib-0075 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0081 | false_positive | exclude |  Study on patient impact  |
| CD009593-bib-0082 | false_positive | exclude |  Reference standard not satisfied  |
| CD009593-bib-0104 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0106 | false_positive | exclude |  Includes data for pulmonary and extrapulmonary TB combined  |
| CD009593-bib-0117 | false_positive | exclude |  Not a diagnostic accuracy study  |
| CD009593-bib-0125 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0139 | false_positive | exclude |  Data insufficient for 2 x 2 table  |
| CD009593-bib-0149 | false_positive | exclude |  Systematic review  |
| CD009593-bib-0152 | false_positive | exclude |  Data insufficient for 2 x 2 table  |
| CD009593-bib-0154 | false_positive | exclude |  Data insufficient for 2 x 2 table  |
| CD009593-bib-0160 | false_positive | exclude |  Systematic review  |
| CD009593-bib-0172 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0176 | false_positive | exclude |  Abstract  |
| CD009593-bib-0191 | false_positive | exclude |  Xpert was not the index test.  |
| CD009593-bib-0199 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0200 | false_positive | exclude |  Case‐control study  |
| CD009593-bib-0213 | false_positive | exclude |  This study evaluated Xpert for the diagnosis of TB in children.  |
| CD009593-bib-0218 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0234 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0236 | false_positive | exclude |  Case‐control study  |
| CD009593-bib-0240 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0243 | false_positive | exclude |  Xpert Ultra not evaluated  |
| CD009593-bib-0252 | false_positive | exclude |  Abstract  |
| CD009593-bib-0258 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD009593-bib-0262 | false_positive | exclude |  Screening study  |
| CD009593-bib-0269 | false_positive | exclude |  Includes both adults and children, or no information about age of enrolment  |
| CD010901-bib-0046 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0051 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0057 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0058 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0067 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0068 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0070 | false_positive | exclude |  Not an offender population  |
| CD010901-bib-0096 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0112 | false_positive | exclude |  Not an offender population  |
| CD010901-bib-0114 | false_positive | exclude |  Not an offender population  |
| CD010901-bib-0116 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0122 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0136 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0138 | false_positive | exclude |  Conference proceedings only, without useful data  |
| CD010901-bib-0144 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0149 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0156 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0167 | false_positive | exclude |  Not an offender population  |
| CD010901-bib-0169 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0170 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0174 | false_positive | exclude |  Not an offender population  |
| CD010901-bib-0177 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0180 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0181 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0182 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0183 | false_positive | exclude |  Not a randomised controlled trial  |
| CD010901-bib-0205 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010901-bib-0206 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0207 | false_positive | exclude |  Not a mental health population  |
| CD010901-bib-0222 | false_positive | exclude |  Not measuring drug or crime outcomes  |
| CD010910-bib-0045 | false_positive | exclude |  This does not contain a female population  |
| CD010910-bib-0061 | false_positive | exclude |  This is not a female population  |
| CD010910-bib-0064 | false_positive | exclude |  This is not a randomised controlled trial  |
| CD010910-bib-0110 | false_positive | exclude |  This is not an offender population  |
| CD010910-bib-0112 | false_positive | exclude |  This is not an offender population  |
| CD010910-bib-0114 | false_positive | exclude |  This is not a randomised controlled trial  |
| CD010910-bib-0122 | false_positive | exclude |  This is not a female population  |
| CD010910-bib-0147 | false_positive | exclude |  This is not measuring drug or crime outcomes  |
| CD010910-bib-0152 | false_positive | exclude |  This is not an offender population  |
| CD010910-bib-0154 | false_positive | exclude |  This is not a female population  |
| CD010910-bib-0176 | false_positive | exclude |  This is not a female population  |
| CD010910-bib-0180 | false_positive | exclude |  This is not an offender population  |
| CD010910-bib-0213 | false_positive | exclude |  This is not measuring drug or crime outcomes  |
| CD010910-bib-0214 | false_positive | exclude |  This is not a female population  |
| CD010910-bib-0229 | false_positive | exclude |  This is not measuring drug or crime outcomes  |
| CD010910-bib-0231 | false_positive | exclude |  This is not measuring drug or crime outcomes  |
| CD010912-bib-0102 | false_positive | exclude |  Not RCT or CBA.  |
| CD010912-bib-0126 | false_positive | exclude |  Not conducted in a workplace setting.  |
| CD010912-bib-0144 | false_positive | exclude |  Did not report workplace sitting  |
| CD010912-bib-0146 | false_positive | exclude |  Not an RCT or CBA.  |
| CD010912-bib-0153 | false_positive | exclude |  Did not report workplace sitting  |
| CD010912-bib-0163 | false_positive | exclude |  Not RCT or CBA.  |
| CD011145-bib-0095 | false_positive | exclude |  Wrong index test (3MS)  |
| CD011145-bib-0131 | false_positive | exclude |  Wrong study design (partial verification ‐ only index test positives received reference standard)   |
| CD011145-bib-0254 | false_positive | exclude |  Wrong study design  |
| CD011145-bib-0275 | false_positive | exclude |  Wrong study design (case‐control; all participants had MCI at baseline)  |
| CD011737-bib-0108 | false_positive | exclude |  Intervention was not dietary fat modification or low fat diet.  |
| CD011737-bib-0226 | false_positive | exclude |  Follow‐up less than 24 months  |
| CD011737-bib-0248 | false_positive | exclude |  Authors confirmed that differences between intervention and control groups included smoking and physical activity, as well as dietary changes.   |
| CD011737-bib-0379 | false_positive | exclude |  Weight reduction for some low‐fat diet participants (those with BMI > 25) but not in Mediterranean group   |
| CD011737-bib-0455 | false_positive | exclude |  All study arms (low or high total fat) prescribed low saturated fat intake (8%E); no usual fat comparator.   |
| CD011737-bib-0459 | false_positive | exclude |  All study arms (low or high total fat) prescribed low saturated fat intake (8%E); no usual fat comparator.   |
| CD011737-bib-0460 | false_positive | exclude |  All study arms (low or high total fat) prescribed low saturated fat intake (8%E); no usual fat comparator.   |
| CD011737-bib-0463 | false_positive | exclude |  All study arms (low or high total fat) prescribed low saturated fat intake (8%E); no usual fat comparator.   |
| CD011737-bib-0468 | false_positive | exclude |  All study arms (low or high total fat) prescribed low saturated fat intake (8%E); no usual fat comparator.   |
| CD011737-bib-0477 | false_positive | exclude |  Total fat goals in the low‐fat arm were unclear and authors confirmed that aims were nonspecific (if aims < 30%E, this study would be included).   |
| CD011737-bib-0497 | false_positive | exclude |  Total fat goals in the low‐fat arm were unclear and authors confirmed that aims were nonspecific (if aims < 30%E, this study would be included).   |
| CD012199-bib-0059 | false_positive | exclude |  Wrong study design  |
| CD012199-bib-0090 | false_positive | exclude |  Wrong study design  |
| CD012199-bib-0091 | false_positive | exclude |  Wrong study design  |
| CD012199-bib-0106 | false_positive | exclude |  Wrong outcomes  |
| CD013088-bib-0057 | false_positive | exclude |  Wrong population: aged ≥ 65 years with ≥ 1 visit to a primary care clinician in the past 12 months.   |
| CD013274-bib-0044 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0051 | false_positive | exclude |  Wrong participants  |
| CD013274-bib-0062 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0069 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0078 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0080 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0081 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0083 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0091 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0092 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0094 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0102 | false_positive | exclude |  Wrong study design  |
| CD013274-bib-0128 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0142 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0143 | false_positive | exclude |  No shared decision‐making  |
| CD013274-bib-0145 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0149 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0150 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0160 | false_positive | exclude |  Wrong study design  |
| CD013274-bib-0174 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0181 | false_positive | exclude |  Wrong study design  |
| CD013274-bib-0187 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0198 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0201 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0203 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0204 | false_positive | exclude |  Not related to person‐centred care  |
| CD013274-bib-0209 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0211 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0215 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0217 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0241 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0248 | false_positive | exclude |  Wrong study design  |
| CD013274-bib-0253 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0259 | false_positive | exclude |  Wrong partnership format  |
| CD013274-bib-0281 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0285 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0286 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0291 | false_positive | exclude |  Wrong partnership format  |
| CD013274-bib-0308 | false_positive | exclude |  Wrong intervention  |
| CD013274-bib-0311 | false_positive | exclude |  Wrong intervention  |
| CD013274-bib-0313 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0328 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0340 | false_positive | exclude |  Wrong study design  |
| CD013274-bib-0341 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0348 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0349 | false_positive | exclude |  Wrong partnership format  |
| CD013274-bib-0356 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0358 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0361 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0366 | false_positive | exclude |  Not related to person‐centred care  |
| CD013274-bib-0369 | false_positive | exclude |  Not related to person‐centred care  |
| CD013274-bib-0372 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0383 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0386 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0392 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0396 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0398 | false_positive | exclude |  Wrong phenomenon  |
| CD013274-bib-0406 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0424 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0434 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0450 | false_positive | exclude |  Wrong on two or more criteria  |
| CD013274-bib-0459 | false_positive | exclude |  Wrong study design  |
| CD013328-bib-0056 | false_positive | exclude |  No eligible study outcomes  |
| CD013328-bib-0064 | false_positive | exclude |  The study measures the effect of adherence on outcomes reported in the Freeman 2014 studies included in our review and is not a separate sanitation interventio |
| CD013328-bib-0067 | false_positive | exclude |  No eligible sanitation intervention  |
| CD013328-bib-0070 | false_positive | exclude |  No eligible sanitation intervention  |
| CD013635-bib-0140 | false_positive | exclude |  Wrong study design  |
| CD013635-bib-0143 | false_positive | exclude |  Wrong recipient (no participant)  |
| CD013635-bib-0154 | false_positive | exclude |  Examination of potential intervention  |
| CD013635-bib-0161 | false_positive | exclude |  Wrong outcome (no focus on health and well‐being)  |
| CD013635-bib-0191 | false_positive | exclude |  Wrong participant (no recipient)  |
| CD013635-bib-0195 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0197 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0202 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0211 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0213 | false_positive | exclude |  Paediatric population  |
| CD013635-bib-0216 | false_positive | exclude |  Wrong outcome (not focus on health and well‐being)  |
| CD013635-bib-0219 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0222 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013635-bib-0223 | false_positive | exclude |  No qualitative data  |
| CD013635-bib-0224 | false_positive | exclude |  No qualitative data  |
| CD013635-bib-0225 | false_positive | exclude |  No qualitative data  |
| CD013635-bib-0229 | false_positive | exclude |  No qualitative data  |
| CD013635-bib-0233 | false_positive | exclude |  Wrong intervention (no cash transfer)  |
| CD013775-bib-0096 | false_positive | exclude |  Ineligible study design  |
| CD013775-bib-0204 | false_positive | exclude |  Cross‐sectional study  |
| CD013775-bib-0226 | false_positive | exclude |  No data on development of PDR  |
| CD013775-bib-0236 | false_positive | exclude |  Cross‐sectional study  |
| CD013775-bib-0246 | false_positive | exclude |  No data on risk factors  |
| CD013778-bib-0093 | false_positive | exclude |  Ineligible intervention  |
| CD013778-bib-0191 | false_positive | exclude |  Ineligible intervention  |
| CD013778-bib-0193 | false_positive | exclude |  Ineligible intervention  |
| CD014758-bib-0257 | false_positive | exclude |  Ineligible population (included children and young adults)  |
| CD014758-bib-0281 | false_positive | exclude |  Letter/commentary  |
| CD014821-bib-0079 | false_positive | exclude |  Wrong intervention (scheduling infliximab infusions).  |
| CD014821-bib-0086 | false_positive | exclude |  Wrong study design (participating youth were recruited sequentially from 1 of 2 paediatric IBD centres in the Midwest region of the USA).   |
