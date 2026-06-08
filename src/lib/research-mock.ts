export type Confidence = "High" | "Medium" | "Low";
export type SourceType = "internet" | "scientific_paper";

export interface Source {
  title: string;
  url: string;
}

export interface Answer {
  question: string;
  answer: string;
  confidence: Confidence;
  source_type_used: SourceType[];
  sources: Source[];
}

export interface ResearchReport {
  technology: string;
  questions_file: string;
  executive_summary: string;
  answers: Answer[];
  retrieval_summary: {
    internet_sources_found: number;
    scientific_paper_sources_found: number;
    edison_enabled: boolean;
  };
}

export const QUESTION_SETS = [
  {
    id: "general_evaluation",
    label: "General Evaluation",
    description: "Broad technology assessment including maturity, scalability, and commercial readiness.",
  },
  {
    id: "general_decarbonization",
    label: "General Decarbonization",
    description: "CO₂ reduction potential, abatement cost, and lifecycle emissions impact.",
  },
  {
    id: "carbon_capture",
    label: "Carbon Capture",
    description: "Capture mechanism, capture rate, CAPEX/OPEX, and integration with cement plants.",
  },
  {
    id: "scms",
    label: "Supplementary Cementitious Materials (SCMs)",
    description: "Material composition, clinker substitution rate, performance, and supply availability.",
  },
  {
    id: "alternative_cement",
    label: "Alternative Cement",
    description: "Novel chemistry, performance vs. OPC, standards compliance, and adoption barriers.",
  },
] as const;

export const EXAMPLE_TOPICS = [
  "Calcium Looping",
  "LC3 Cement",
  "Fly Ash",
  "Carbon Upcycling",
  "Direct Separation",
  "Fortera",
  "Sublime Systems",
];

export function buildMockReport(technology: string, questionSetId: string): ResearchReport {
  const set = QUESTION_SETS.find((s) => s.id === questionSetId) ?? QUESTION_SETS[2];
  const baseAnswers: Answer[] = [
    {
      question: "What is the capital cost (CAPEX)?",
      answer:
        "Reported CAPEX for first-of-a-kind deployments at cement plants ranges between $350–$520 per tonne of annual CO₂ capacity, with significant learning-curve reductions projected by 2030. Cost is dominated by sorbent calciner construction and high-temperature heat integration.",
      confidence: "Medium",
      source_type_used: ["internet", "scientific_paper"],
      sources: [
        { title: "IEAGHG Technical Report 2022-04: Calcium Looping for Cement", url: "https://ieaghg.org/publications" },
        { title: "Hills et al., Environmental Science & Technology, 2021", url: "https://pubs.acs.org/est" },
      ],
    },
    {
      question: "What is the operating cost (OPEX)?",
      answer:
        "OPEX is estimated at $42–$68 per tonne CO₂ captured, driven primarily by fuel for the calciner, makeup sorbent, and electricity for ancillary equipment. Heat integration with the existing kiln meaningfully reduces marginal cost.",
      confidence: "Medium",
      source_type_used: ["scientific_paper"],
      sources: [
        { title: "Atsonios et al., International Journal of Greenhouse Gas Control, 2023", url: "https://www.sciencedirect.com/journal/international-journal-of-greenhouse-gas-control" },
      ],
    },
    {
      question: "What is the CO₂ capture rate?",
      answer:
        "Pilot and demonstration projects report capture efficiencies of 90–95% under steady-state operation. Performance degradation from sorbent deactivation is mitigated through purge-and-makeup strategies.",
      confidence: "High",
      source_type_used: ["internet", "scientific_paper"],
      sources: [
        { title: "CEMCAP Project Final Results", url: "https://www.sintef.no/projectweb/cemcap/" },
        { title: "Arias et al., Applied Energy, 2020", url: "https://www.sciencedirect.com/journal/applied-energy" },
      ],
    },
    {
      question: "What is the technology readiness level (TRL)?",
      answer:
        "Currently TRL 6–7. Several pilots at 1–2 MWth scale have been operated, and a 30 MWth demonstration is planned at the HeidelbergCement Hannover plant under the LEILAC consortium.",
      confidence: "High",
      source_type_used: ["internet"],
      sources: [
        { title: "LEILAC Project Overview", url: "https://www.project-leilac.eu/" },
      ],
    },
    {
      question: "What integration challenges exist with existing cement plants?",
      answer:
        "Not Found",
      confidence: "Low",
      source_type_used: [],
      sources: [],
    },
    {
      question: "Who are the principal developers and commercial backers?",
      answer:
        "Key developers include CSIC-INCAR (Spain), Politecnico di Milano, and industrial partners HeidelbergCement, Cemex, and Calix. Public funding has come from Horizon 2020 and the EU Innovation Fund.",
      confidence: "High",
      source_type_used: ["internet"],
      sources: [
        { title: "EU Innovation Fund Project Portfolio", url: "https://cinea.ec.europa.eu/programmes/innovation-fund_en" },
        { title: "Calix Investor Presentation 2024", url: "https://calix.global/" },
      ],
    },
  ];

  return {
    technology,
    questions_file: set.id,
    executive_summary:
      `${technology} is a post-combustion CO₂ capture approach particularly well suited to the cement industry because it leverages calcium-based sorbents chemically similar to feedstocks already present in clinker production. In a typical configuration, a carbonator captures CO₂ from flue gas at 600–700 °C, and the resulting CaCO₃ is regenerated in an oxy-fired calciner, producing a concentrated CO₂ stream ready for compression and transport.\n\n` +
      `Relative to amine-based capture, ${technology.toLowerCase()} avoids solvent degradation and recovers high-grade heat that can be integrated back into the clinker process. Demonstrated capture rates of 90% or greater have been achieved at pilot scale, and several engineering studies project levelized costs below $70 per tonne CO₂ at commercial scale.\n\n` +
      `The technology is currently at TRL 6–7, with multi-megawatt pilots operating in Europe and a 30 MWth demonstration scheduled within the next 24 months. Commercial deployment will depend on resolving sorbent attrition, scaling oxy-combustion infrastructure, and securing CO₂ transport and storage offtake.\n\n` +
      `Principal industrial proponents include HeidelbergCement, Cemex, and Calix, with academic leadership from CSIC-INCAR and Politecnico di Milano. Public funding through the EU Innovation Fund has substantially de-risked early deployments.\n\n` +
      `Overall, this is among the most technically credible near-term decarbonization pathways for cement, though final cost competitiveness will hinge on energy prices, carbon prices, and the realization of learning effects across the first generation of commercial plants.`,
    answers: baseAnswers,
    retrieval_summary: {
      internet_sources_found: 8,
      scientific_paper_sources_found: questionSetId === "alternative_cement" ? 0 : 14,
      edison_enabled: questionSetId !== "alternative_cement",
    },
  };
}
