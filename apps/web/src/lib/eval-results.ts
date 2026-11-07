// Generated from evals/results/final-2026-11-07 (the sealed eval result). Do not edit by hand:
// every number here comes from that run's results.json and case snapshot.

export type SystemId = "baseline" | "specialist";
export interface Ratio {
  n: number;
  d: number;
  value: number | null;
}
export interface CaseRun {
  passed: boolean;
  firstAction: string;
  actionCorrect: boolean;
  secondTurnCorrect: boolean | null;
  recall: Ratio;
  precision: Ratio;
  samplePrecision: Ratio;
  sampleRecall: Ratio;
  subsetsExact: Ratio;
  wrong: number;
  ineligible: number;
  fabricated: number;
  questions: string[];
  seconds: number;
  inputTokens: number;
}
export interface EvalCase {
  id: string;
  title: string;
  prompt: string;
  expected: string;
  alsoAcceptable: string[];
  probes: string;
  positives: number;
  baseline: CaseRun;
  specialist: CaseRun;
}
export interface SystemSummary {
  passed: Ratio;
  actionAccuracy: Ratio;
  shouldAsk: Ratio;
  falseAsk: Ratio;
  secondTurn: Ratio;
  recall: Ratio;
  precision: Ratio;
  samplePrecision: Ratio;
  sampleRecall: Ratio;
  subsetsExact: Ratio;
  ineligible: number;
  fabricated: number;
  inputTokensPerRun: number;
  secondsPerRun: number;
  webSearchesPerRun: number;
  webFetchesPerRun: number;
  geoQueriesPerRun: number;
}
export interface EvalResults {
  meta: {
    runId: string;
    startedAt: string;
    model: string;
    effort: string;
    repeats: number;
    cases: number;
    codeRevision: string;
    reviewed: boolean;
    unjudged: number;
  };
  summary: Record<SystemId, SystemSummary>;
  cases: EvalCase[];
}

export const EVAL_RESULTS: EvalResults = {
  meta: {
    runId: "all12-r2",
    startedAt: "2026-11-07T15:04:10+00:00",
    model: "claude-opus-5-5",
    effort: "medium",
    repeats: 1,
    cases: 12,
    codeRevision: "4032f8cb3e85",
    reviewed: false,
    unjudged: 7,
  },
  summary: {
    baseline: {
      passed: {
        n: 5,
        d: 12,
        value: 0.4166666666666667,
      },
      actionAccuracy: {
        n: 7,
        d: 12,
        value: 0.5833333333333334,
      },
      shouldAsk: {
        n: 4,
        d: 4,
        value: 1.0,
      },
      falseAsk: {
        n: 5,
        d: 5,
        value: 1.0,
      },
      secondTurn: {
        n: 8,
        d: 8,
        value: 1.0,
      },
      recall: {
        n: 15,
        d: 24,
        value: 0.625,
      },
      precision: {
        n: 19,
        d: 23,
        value: 0.8260869565217391,
      },
      samplePrecision: {
        n: 0,
        d: 0,
        value: null,
      },
      sampleRecall: {
        n: 0,
        d: 1479,
        value: 0.0,
      },
      subsetsExact: {
        n: 0,
        d: 15,
        value: 0.0,
      },
      ineligible: 3,
      fabricated: 0,
      inputTokensPerRun: 292708,
      secondsPerRun: 122,
      webSearchesPerRun: 15.1,
      webFetchesPerRun: 13.4,
      geoQueriesPerRun: 0,
    },
    specialist: {
      passed: {
        n: 11,
        d: 12,
        value: 0.9166666666666666,
      },
      actionAccuracy: {
        n: 11,
        d: 12,
        value: 0.9166666666666666,
      },
      shouldAsk: {
        n: 4,
        d: 4,
        value: 1.0,
      },
      falseAsk: {
        n: 1,
        d: 5,
        value: 0.2,
      },
      secondTurn: {
        n: 4,
        d: 4,
        value: 1.0,
      },
      recall: {
        n: 23,
        d: 24,
        value: 0.9583333333333334,
      },
      precision: {
        n: 29,
        d: 29,
        value: 1.0,
      },
      samplePrecision: {
        n: 1651,
        d: 1651,
        value: 1.0,
      },
      sampleRecall: {
        n: 1651,
        d: 1675,
        value: 0.9856716417910448,
      },
      subsetsExact: {
        n: 22,
        d: 23,
        value: 0.9565217391304348,
      },
      ineligible: 0,
      fabricated: 0,
      inputTokensPerRun: 80992,
      secondsPerRun: 42,
      webSearchesPerRun: 0,
      webFetchesPerRun: 0,
      geoQueriesPerRun: 11.8,
    },
  },
  cases: [
    {
      id: "pdac_organoids_drug_vs_untreated",
      title: "PDAC organoids, drug vs untreated",
      prompt:
        "Which genes change when patient-derived pancreatic cancer organoids are treated with a drug in culture (at any dose or time point), compared with the same organoids left untreated?",
      expected: "proceed",
      alsoAcceptable: [],
      probes:
        "A title that promises organoids over cell-line samples; treated in the patient is not treated in culture.",
      positives: 2,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 1,
          d: 2,
          value: 0.5,
        },
        precision: {
          n: 1,
          d: 2,
          value: 0.5,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 16,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 1,
          value: 0.0,
        },
        wrong: 1,
        ineligible: 1,
        fabricated: 0,
        questions: [
          "Which drug or drug class do you mean? 'A drug' could match many separate GEO series, each testing a different compound, and pooling them would mix unrelated biology.",
          "What counts as the untreated control?",
          "Should the organoids come only from primary PDAC tissue (surgical resection or EUS-FNA biopsy), or are these also acceptable: PDX-derived organoids, organoids from metastases or ascites, organoids grown with fibroblasts or immune cells, and other pancreatic tumour types (e.g. neuroendocrine)?",
          "If one series includes several doses or time points, should all treated samples be pooled into one case arm, or should you pick one dose/time (e.g. the longest exposure or the IC50 dose)?",
        ],
        seconds: 176,
        inputTokens: 329673,
      },
      specialist: {
        passed: true,
        firstAction: "proceed",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        precision: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        samplePrecision: {
          n: 48,
          d: 48,
          value: 1.0,
        },
        sampleRecall: {
          n: 48,
          d: 48,
          value: 1.0,
        },
        subsetsExact: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 42,
        inputTokens: 101529,
      },
    },
    {
      id: "kras_inhibitor_pancreatic_cells",
      title: "KRAS inhibitor vs vehicle, pancreatic cancer cells",
      prompt:
        "Which genes change when human pancreatic cancer cell lines are treated in culture with a direct KRAS inhibitor (such as MRTX1133, sotorasib or a pan-KRAS inhibitor) compared with vehicle at the same time point?",
      expected: "proceed",
      alsoAcceptable: [],
      probes:
        "Both answers are pancreatic subsets of multi-tissue series; xenografts, SOS1/MEK inhibitors, lung lines and a missing-counts arm are traps.",
      positives: 2,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 0,
          d: 2,
          value: 0.0,
        },
        precision: {
          n: 0,
          d: 1,
          value: 0.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 1,
        ineligible: 1,
        fabricated: 0,
        questions: [
          "Should RAS(ON) multi-selective tri-complex inhibitors (RMC-6236/daraxonrasib, RMC-7977) count as a 'direct KRAS inhibitor', or only KRAS-selective drugs (MRTX1133, sotorasib, adagrasib, BI-2865-type pan-KRAS)?",
          "Should the case arm be limited to one KRAS allele and drug, or pool all direct KRAS inhibitors across cell lines?",
          "Which treatment duration should be used when a series has more than one time point?",
        ],
        seconds: 280,
        inputTokens: 928246,
      },
      specialist: {
        passed: true,
        firstAction: "proceed",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        precision: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        samplePrecision: {
          n: 30,
          d: 30,
          value: 1.0,
        },
        sampleRecall: {
          n: 30,
          d: 30,
          value: 1.0,
        },
        subsetsExact: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 43,
        inputTokens: 55373,
      },
    },
    {
      id: "kras_inhibitor_resistant_pancreatic_cells",
      title: "KRAS-inhibitor-resistant vs parental lines",
      prompt:
        "Which genes differ between human pancreatic cancer cell lines that acquired resistance to a KRAS inhibitor and their parental lines?",
      expected: "proceed",
      alsoAcceptable: [],
      probes: "Same pool, different winner; mouse lines are mixed into the human series.",
      positives: 1,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 1,
          d: 1,
          value: 1.0,
        },
        precision: {
          n: 1,
          d: 1,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 12,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 1,
          value: 0.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which drug classes count as a 'KRAS inhibitor' for the resistant arm?",
          "Should each resistant line be compared only with its own parental line (one analysis per cell line), or should several cell lines be pooled into one resistant-vs-parental contrast?",
        ],
        seconds: 196,
        inputTokens: 462934,
      },
      specialist: {
        passed: true,
        firstAction: "proceed",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 1,
          d: 1,
          value: 1.0,
        },
        precision: {
          n: 1,
          d: 1,
          value: 1.0,
        },
        samplePrecision: {
          n: 12,
          d: 12,
          value: 1.0,
        },
        sampleRecall: {
          n: 12,
          d: 12,
          value: 1.0,
        },
        subsetsExact: {
          n: 1,
          d: 1,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 36,
        inputTokens: 58752,
      },
    },
    {
      id: "hepatoblastoma_vs_nontumor_liver",
      title: "Hepatoblastoma vs non-tumor liver",
      prompt:
        "Which genes differ between hepatoblastoma tumors and non-tumor liver tissue from children?",
      expected: "proceed",
      alsoAcceptable: [],
      probes: "Pediatric tissue only, not HepG2-type cell lines or adult liver cancer.",
      positives: 6,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 4,
          d: 6,
          value: 0.6666666666666666,
        },
        precision: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 158,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 4,
          value: 0.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Should the control arm be only non-tumour liver adjacent to the tumour from the same children, or can it also be normal liver from other donors (possibly adults)?",
          "Should tumours taken after neoadjuvant chemotherapy count, or only treatment-naive tumours?",
        ],
        seconds: 170,
        inputTokens: 441736,
      },
      specialist: {
        passed: true,
        firstAction: "proceed",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        precision: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        samplePrecision: {
          n: 209,
          d: 209,
          value: 1.0,
        },
        sampleRecall: {
          n: 209,
          d: 209,
          value: 1.0,
        },
        subsetsExact: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 33,
        inputTokens: 38597,
      },
    },
    {
      id: "pediatric_crohn_ileum_vs_control",
      title: "Pediatric Crohn's ileum vs non-IBD",
      prompt:
        "Which genes differ in ileal biopsies between children with Crohn's disease and non-IBD controls?",
      expected: "proceed",
      alsoAcceptable: [],
      probes: "Pediatric vs adult cohorts, ulcerative colitis mixed in, overlapping cohorts.",
      positives: 5,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 4,
          d: 5,
          value: 0.8,
        },
        precision: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 1119,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 4,
          value: 0.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Should the Crohn's arm include only children whose ileum is involved, or every child with Crohn's who had an ileal biopsy, including those with colon-only disease?",
          "The RISK series probably share patients. Should we use one series (for example GSE57945) or several together with batch correction and duplicate patients removed?",
        ],
        seconds: 141,
        inputTokens: 244728,
      },
      specialist: {
        passed: false,
        firstAction: "ask",
        actionCorrect: false,
        secondTurnCorrect: true,
        recall: {
          n: 4,
          d: 5,
          value: 0.8,
        },
        precision: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        samplePrecision: {
          n: 1119,
          d: 1119,
          value: 1.0,
        },
        sampleRecall: {
          n: 1119,
          d: 1119,
          value: 1.0,
        },
        subsetsExact: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Should the Crohn's arm include all pediatric CD patients, or only those with ileal involvement (iCD), leaving out colon-only CD (cCD)?",
        ],
        seconds: 62,
        inputTokens: 99227,
      },
    },
    {
      id: "kras_inhibitor_pdac_organoids",
      title: "KRAS inhibitor in PDAC organoids",
      prompt:
        "Which genes change when patient-derived pancreatic cancer organoids are treated with a KRAS inhibitor versus vehicle?",
      expected: "no_results",
      alsoAcceptable: ["ask"],
      probes:
        "In scope but no such series exists; cell lines are not organoids. Asking is also accepted.",
      positives: 0,
      baseline: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which class of KRAS inhibitor should count as the treatment?",
          "Should only short-term treatment of drug-naive organoids count, or also organoids made resistant by long-term exposure?",
          "If too few organoid series exist, can other model types be used as a fallback?",
        ],
        seconds: 176,
        inputTokens: 469723,
      },
      specialist: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "I found no GEO series with raw counts that profiles patient-derived pancreatic cancer organoids treated with a KRAS inhibitor versus vehicle. Would you accept pancreatic cancer cell lines grown in 2D instead?",
        ],
        seconds: 76,
        inputTokens: 121293,
      },
    },
    {
      id: "liver_cancer_broad",
      title: '"liver cancer"',
      prompt: "liver cancer",
      expected: "ask",
      alsoAcceptable: [],
      probes: "Must ask which liver cancer; the answer leads to the hepatoblastoma pool.",
      positives: 6,
      baseline: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 4,
          d: 6,
          value: 0.6666666666666666,
        },
        precision: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 158,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 4,
          value: 0.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which type of liver cancer do you mean?",
          "Which two groups should be compared?",
          "If you mean HCC tissue, should the samples be limited to one cause of disease?",
          "Is there a specific gene or pathway you want to look at?",
        ],
        seconds: 135,
        inputTokens: 249463,
      },
      specialist: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        precision: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        samplePrecision: {
          n: 209,
          d: 209,
          value: 1.0,
        },
        sampleRecall: {
          n: 209,
          d: 209,
          value: 1.0,
        },
        subsetsExact: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which type of liver cancer do you mean?",
          "What should the two groups be?",
          "Do you have a preference for patient population (adult vs pediatric, or ethnicity/etiology)?",
        ],
        seconds: 52,
        inputTokens: 136573,
      },
    },
    {
      id: "pancreatic_cancer_broad",
      title: '"pancreatic cancer"',
      prompt: "pancreatic cancer",
      expected: "ask",
      alsoAcceptable: [],
      probes: "A bare topic must be narrowed; the answer leads to the organoid pool.",
      positives: 2,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 1,
          d: 2,
          value: 0.5,
        },
        precision: {
          n: 1,
          d: 2,
          value: 0.5,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 16,
          value: 0.0,
        },
        subsetsExact: {
          n: 0,
          d: 1,
          value: 0.0,
        },
        wrong: 1,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which two groups do you want to compare?",
          "Which type of sample should both arms be?",
          "Should this be limited to pancreatic ductal adenocarcinoma, or include other pancreatic tumors?",
          "If the controls are 'normal' tissue, which kind?",
          "Do you have specific genes or pathways of interest?",
        ],
        seconds: 127,
        inputTokens: 325833,
      },
      specialist: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: true,
        recall: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        precision: {
          n: 2,
          d: 2,
          value: 1.0,
        },
        samplePrecision: {
          n: 24,
          d: 24,
          value: 1.0,
        },
        sampleRecall: {
          n: 24,
          d: 48,
          value: 0.5,
        },
        subsetsExact: {
          n: 1,
          d: 2,
          value: 0.5,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "What comparison do you want to make?",
          "Which tumor type do you mean?",
          "Which kind of samples do you want?",
          "Do you have a particular gene, drug or pathway in mind?",
        ],
        seconds: 67,
        inputTokens: 166448,
      },
    },
    {
      id: "hcc_tumor_vs_adjacent",
      title: "HCC tumor vs adjacent liver",
      prompt: "Which genes differ between HCC tumor and adjacent non-tumor liver?",
      expected: "ask",
      alsoAcceptable: [],
      probes:
        "More than ten series qualify and the analysis takes ten, so it should ask how to narrow.",
      positives: 17,
      baseline: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 4,
          d: 4,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Should the analysis be limited to one underlying liver disease (etiology)?",
          "Do you need strictly paired tumor/adjacent samples from the same patients?",
          "What counts as the control tissue?",
          "Which 10 or fewer series should be used, or should the largest paired cohorts be prioritized?",
        ],
        seconds: 34,
        inputTokens: 36256,
      },
      specialist: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 6,
          d: 6,
          value: 1.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Should the analysis be limited to one HCC cause or patient population, or should it pool all of them?",
          "Should tumors from patients with venous invasion (PVTT), recurrence or immunotherapy be included, or only standard resected primary tumors?",
        ],
        seconds: 60,
        inputTokens: 89826,
      },
    },
    {
      id: "lung_cancer_broad",
      title: '"lung cancer"',
      prompt: "lung cancer",
      expected: "ask",
      alsoAcceptable: [],
      probes: "Must ask which lung cancer.",
      positives: 0,
      baseline: {
        passed: false,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 1,
          value: 0.0,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 1,
        ineligible: 1,
        fabricated: 0,
        questions: [
          "Which two groups do you want to compare?",
          "Which lung cancer type?",
          "What kind of sample material?",
          "For tumor vs. normal, do the samples need to be paired (tumor and normal from the same patient)?",
          "Is there a specific gene or pathway you want to look at?",
        ],
        seconds: 19,
        inputTokens: 7953,
      },
      specialist: {
        passed: true,
        firstAction: "ask",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Which lung cancer type do you mean?",
          "What should the comparison be?",
          "Is there a gene, drug or pathway you are interested in?",
        ],
        seconds: 26,
        inputTokens: 95010,
      },
    },
    {
      id: "mouse_nash_liver",
      title: "Mouse NASH liver",
      prompt:
        "Which liver genes change in mice fed a NASH-inducing diet compared with chow-fed mice?",
      expected: "decline",
      alsoAcceptable: [],
      probes: "Another organism: out of scope.",
      positives: 0,
      baseline: {
        passed: true,
        firstAction: "decline",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 4,
        inputTokens: 7981,
      },
      specialist: {
        passed: true,
        firstAction: "decline",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 4,
        inputTokens: 4639,
      },
    },
    {
      id: "colorectal_methylation",
      title: "Colorectal tumor methylation",
      prompt:
        "Which genes are differentially methylated between colorectal tumors and normal colon?",
      expected: "decline",
      alsoAcceptable: [],
      probes: "DNA methylation, not gene expression: out of scope.",
      positives: 0,
      baseline: {
        passed: true,
        firstAction: "decline",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [
          "Do you want differential DNA methylation itself, or the expression of genes (possibly methylation-silenced ones) in colorectal tumor vs. normal colon?",
        ],
        seconds: 8,
        inputTokens: 7973,
      },
      specialist: {
        passed: true,
        firstAction: "decline",
        actionCorrect: true,
        secondTurnCorrect: null,
        recall: {
          n: 0,
          d: 0,
          value: null,
        },
        precision: {
          n: 0,
          d: 0,
          value: null,
        },
        samplePrecision: {
          n: 0,
          d: 0,
          value: null,
        },
        sampleRecall: {
          n: 0,
          d: 0,
          value: null,
        },
        subsetsExact: {
          n: 0,
          d: 0,
          value: null,
        },
        wrong: 0,
        ineligible: 0,
        fabricated: 0,
        questions: [],
        seconds: 6,
        inputTokens: 4631,
      },
    },
  ],
};
