/**
 * TypeScript ports of the pydantic models in
 * python/ollama_learning/schemas.py. Field names match exactly so the same
 * JSON files feed both the tkinter launchers and this app.
 */

export type Kind =
  | "quizzes"
  | "mindmaps"
  | "flashcards"
  | "reports"
  | "slides"
  | "datatables"
  | "infographics";

export interface ManifestEntry {
  file: string;
  stem: string;
  title: string;
  sidecars: string[];
}

export interface Manifest {
  generatedAt: string;
  kinds: Record<Kind, ManifestEntry[]>;
}

// -- Quiz ------------------------------------------------------------------

export const DIFFICULTIES = [
  "recall",
  "understanding",
  "application",
  "analysis",
  "expert",
] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export interface QuizQuestion {
  question: string;
  options: string[];
  correct: number;
  explanation: string;
  difficulty: Difficulty;
  sources: string[];
}

export interface Quiz {
  title: string;
  description: string;
  questions: QuizQuestion[];
}

// -- Mind map --------------------------------------------------------------

export interface MindMapNode {
  name: string;
  children: MindMapNode[];
}

export type MindMap = MindMapNode;

// -- Flashcards ------------------------------------------------------------

export const CARD_TYPES = ["basic", "cloze", "definition", "concept"] as const;
export type CardType = (typeof CARD_TYPES)[number];

export interface Flashcard {
  type: CardType;
  front: string;
  back: string;
  tags: string[];
  source_ids: string[];
}

export interface FlashcardSet {
  title: string;
  description: string;
  cards: Flashcard[];
}

// -- Reports ---------------------------------------------------------------

export interface Citation {
  source_id: string;
  page: number | null;
  chunk_id: string | null;
}

export interface Claim {
  claim: string;
  citations: Citation[];
}

export interface ReportSection {
  title: string;
  content: string;
  claims: Claim[];
}

export interface Report {
  title: string;
  executive_summary: string;
  sections: ReportSection[];
  conclusions: string;
}

// -- Slides ----------------------------------------------------------------

export interface Slide {
  title: string;
  subtitle: string | null;
  bullets: string[];
  speaker_notes: string;
  image_query: string | null;
  source_ids: string[];
}

export interface Presentation {
  title: string;
  slides: Slide[];
}

// -- Data tables -----------------------------------------------------------

export interface StudyField {
  name: string;
  description: string;
  example: string | null;
}

export interface DataTable {
  title: string;
  fields: StudyField[];
  data: Record<string, string>[];
}

// -- Infographics ----------------------------------------------------------

export const SECTION_TYPES = [
  "stat",
  "flow",
  "chart",
  "quote",
  "comparison",
  "svg",
] as const;
export type SectionType = (typeof SECTION_TYPES)[number];

export interface InfographicSection {
  type: SectionType;
  title: string | null;
  value: string | null;
  label: string | null;
  items: string[];
  panel: string | null;
  span: "full" | "half";
}

export interface Infographic {
  title: string;
  subtitle: string | null;
  sections: InfographicSection[];
}
