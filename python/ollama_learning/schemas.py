"""Pydantic schemas for structured outputs from Ollama."""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


# Audio/Podcast Schemas
class Speaker(BaseModel):
    """Speaker definition for podcast."""
    id: str = Field(..., description="Unique speaker identifier")
    voice: str = Field(..., description="Voice model name")


class PodcastSegment(BaseModel):
    """Single dialogue segment in podcast."""
    speaker: str = Field(..., description="Speaker ID")
    text: str = Field(..., description="Dialogue text")
    emotion: Optional[str] = Field(None, description="Emotion/tone (e.g., curious, enthusiastic)")
    pause_after_ms: int = Field(300, description="Pause duration in milliseconds")


class PodcastOutline(BaseModel):
    """Complete podcast outline with structured dialogue."""
    title: str = Field(..., description="Podcast title")
    speakers: List[Speaker] = Field(..., description="Speaker definitions")
    segments: List[PodcastSegment] = Field(..., description="Dialogue segments")


# Slide Deck Schemas
class Slide(BaseModel):
    """Single slide in presentation."""
    title: str = Field(..., description="Slide title")
    subtitle: Optional[str] = Field(None, description="Slide subtitle")
    bullets: List[str] = Field(default_factory=list, description="Bullet points")
    speaker_notes: str = Field("", description="Speaker notes")
    image_query: Optional[str] = Field(None, description="Query for image generation")
    source_ids: List[str] = Field(default_factory=list, description="Source references")


class Presentation(BaseModel):
    """Complete slide deck presentation."""
    title: str = Field(..., description="Presentation title")
    slides: List[Slide] = Field(..., description="All slides")


# Mind Map Schemas
class MindMapNode(BaseModel):
    """Single node in mind map."""
    name: str = Field(..., description="Node name")
    children: List['MindMapNode'] = Field(default_factory=list, description="Child nodes")
    
    # Allow forward reference
    model_config = {"extra": "ignore"}


MindMapNode.model_rebuild()


class MindMap(BaseModel):
    """Complete mind map structure."""
    name: str = Field(..., description="Root node name")
    children: List[MindMapNode] = Field(default_factory=list, description="Top-level nodes")


# Report Schemas
class Citation(BaseModel):
    """Citation reference."""
    source_id: str = Field(..., description="Source document ID")
    page: Optional[int] = Field(None, description="Page number")
    chunk_id: Optional[str] = Field(None, description="Specific chunk ID")


class Claim(BaseModel):
    """Claim with supporting citations."""
    claim: str = Field(..., description="The claim or statement")
    citations: List[Citation] = Field(default_factory=list, description="Supporting citations")


class ReportSection(BaseModel):
    """Single section of a report."""
    title: str = Field(..., description="Section title")
    content: str = Field(..., description="Section content")
    claims: List[Claim] = Field(default_factory=list, description="Key claims with citations")


class Report(BaseModel):
    """Complete structured report."""
    title: str = Field(..., description="Report title")
    executive_summary: str = Field(..., description="Executive summary")
    sections: List[ReportSection] = Field(default_factory=list, description="Report sections")
    conclusions: str = Field(..., description="Conclusions")


# Flashcard Schemas
class FlashcardType(str):
    """Flashcard type enumeration."""
    BASIC = "basic"
    CLOZE = "cloze"
    DEFINITION = "definition"
    CONCEPT = "concept"


class Flashcard(BaseModel):
    """Single flashcard."""
    type: Literal["basic", "cloze", "definition", "concept"] = Field(..., description="Card type")
    front: str = Field(..., description="Front of card (question)")
    back: str = Field(..., description="Back of card (answer)")
    tags: List[str] = Field(default_factory=list, description="Study tags")
    source_ids: List[str] = Field(default_factory=list, description="Source references")


class FlashcardSet(BaseModel):
    """Complete set of flashcards."""
    title: str = Field(..., description="Flashcard set title")
    description: str = Field(..., description="Set description")
    cards: List[Flashcard] = Field(..., description="All flashcards")


# Quiz Schemas
class QuizQuestion(BaseModel):
    """Single quiz question."""
    question: str = Field(..., description="Question text")
    options: List[str] = Field(..., description="Answer options (4-6 choices)")
    correct: int = Field(..., description="Index of correct answer (0-based)")
    explanation: str = Field(..., description="Explanation of correct answer")
    difficulty: Literal["recall", "understanding", "application", "analysis", "expert"] = Field(
        "understanding", description="Question difficulty level"
    )
    sources: List[str] = Field(default_factory=list, description="Source references")


class Quiz(BaseModel):
    """Complete quiz."""
    title: str = Field(..., description="Quiz title")
    description: str = Field(..., description="Quiz description")
    questions: List[QuizQuestion] = Field(..., description="All questions")


# Data Table Schemas
class StudyField(BaseModel):
    """Definition of a field to extract."""
    name: str = Field(..., description="Field name")
    description: str = Field(..., description="Field description")
    example: Optional[str] = Field(None, description="Example value")


class ExtractedData(BaseModel):
    """Extracted data from documents."""
    field_name: str = Field(..., description="Field name")
    value: str = Field(..., description="Extracted value")
    source_id: str = Field(..., description="Source document ID")
    page: Optional[int] = Field(None, description="Page number")


class DataTable(BaseModel):
    """Complete data table."""
    title: str = Field(..., description="Table title")
    fields: List[StudyField] = Field(..., description="Field definitions")
    data: List[Dict[str, str]] = Field(..., description="Extracted data rows")


# Infographic Schemas
class InfographicSection(BaseModel):
    """Single section of infographic."""
    type: Literal["stat", "flow", "chart", "quote", "comparison", "svg"] = Field(..., description="Section type")
    title: Optional[str] = Field(None, description="Section title")
    value: Optional[str] = Field(
        None, description="Stat value, quote text, or (for svg) inline markup or a file path"
    )
    label: Optional[str] = Field(None, description="Label, caption, or description")
    items: List[str] = Field(default_factory=list, description="List items for flow/comparison")
    panel: Optional[str] = Field(
        None, description="Panel this section belongs to; sections sharing a name render together"
    )
    span: Literal["full", "half"] = Field(
        "full", description="Width within its panel: 'half' pairs two sections side by side"
    )


class Infographic(BaseModel):
    """Complete infographic specification."""
    title: str = Field(..., description="Infographic title")
    subtitle: Optional[str] = Field(None, description="Optional subtitle or source attribution")
    sections: List[InfographicSection] = Field(..., description="All sections")


# Video Schemas
class VideoScene(BaseModel):
    """Single scene in video."""
    scene: int = Field(..., description="Scene number")
    duration: int = Field(..., description="Duration in seconds")
    narration: str = Field(..., description="Narration text")
    visual_type: Literal["slide", "diagram", "image", "animation", "chart"] = Field(
        ..., description="Visual type"
    )
    visual_title: Optional[str] = Field(None, description="Visual title")
    visual_items: List[str] = Field(default_factory=list, description="Visual content items")


class VideoStoryboard(BaseModel):
    """Complete video storyboard."""
    title: str = Field(..., description="Video title")
    scenes: List[VideoScene] = Field(..., description="All scenes")