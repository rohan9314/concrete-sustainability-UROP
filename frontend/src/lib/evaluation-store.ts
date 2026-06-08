import type { TechnologyEvaluation } from "@/types/technologyEvaluation";

let currentEvaluation: TechnologyEvaluation | null = null;

export function setEvaluation(evaluation: TechnologyEvaluation) {
  currentEvaluation = evaluation;
}

export function getEvaluation(): TechnologyEvaluation | null {
  return currentEvaluation;
}
