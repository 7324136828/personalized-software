"""Generate audio podcasts from documents using Ollama and Kokoro."""

import json
import logging
from pathlib import Path
from typing import Optional, List
import sys

# Add parent directory to path to import podcast module
sys.path.insert(0, str(Path(__file__).parent.parent))

from .client_interface import BaseLLMClient
from .rag_system import RAGSystem
from .schemas import PodcastOutline

LOG = logging.getLogger(__name__)


class AudioGenerator:
    """Generate podcast scripts using RAG and Ollama."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_system: Optional[RAGSystem]
    ):
        self.llm_client = llm_client
        self.rag = rag_system
    
    def generate_podcast_outline(
        self,
        topic: str,
        source_id: Optional[str] = None,
        duration_minutes: int = 10,
        speakers: Optional[List[dict]] = None,
        style: str = "educational"
    ) -> PodcastOutline:
        """Generate a podcast outline with structured dialogue."""
        
        # Default speakers if not provided
        if speakers is None:
            speakers = [
                {"id": "host", "voice": "af_heart"},
                {"id": "expert", "voice": "am_michael"}
            ]
        
        # Retrieve relevant context
        LOG.info(f"Retrieving context for topic: {topic}")
        context_chunks = (
            self.rag.retrieve(topic, top_k=20, source_id=source_id)
            if self.rag is not None
            else []
        )
        
        if not context_chunks:
            LOG.warning("No relevant context found, generating without RAG")
            context_text = "No specific context available."
        else:
            context_text = "\n\n".join([
                f"[{chunk.filename}]: {chunk.text}"
                for chunk in context_chunks
            ])
        
        # Estimate segments based on duration
        estimated_segments = max(5, duration_minutes * 2)  # ~2 segments per minute
        
        # Build prompt
        prompt = f"""Generate a podcast script on: {topic}

Relevant context from source documents:
{context_text}

Podcast style: {style}
Target duration: {duration_minutes} minutes
Estimated segments: {estimated_segments}

Speakers:
{json.dumps(speakers, indent=2)}

Create an engaging, conversational podcast with:
- Natural dialogue between speakers
- Clear explanations of complex topics
- Logical flow from introduction to conclusion
- Appropriate pauses and transitions
- Emotional cues for voice variety

For each segment:
- Specify which speaker is talking
- Write natural, conversational dialogue
- Include emotional direction (curious, enthusiastic, thoughtful, etc.)
- Specify pause duration after each segment (in milliseconds)
- Keep segments to 30-90 seconds when spoken

The podcast should be informative yet conversational, like a discussion between knowledgeable hosts.
"""
        
        # Define JSON schema
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "speakers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "voice": {"type": "string"}
                        },
                        "required": ["id", "voice"]
                    }
                },
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "speaker": {"type": "string"},
                            "text": {"type": "string"},
                            "emotion": {"type": "string"},
                            "pause_after_ms": {"type": "integer"}
                        },
                        "required": ["speaker", "text"]
                    }
                }
            },
            "required": ["title", "speakers", "segments"]
        }
        
        try:
            response = self.llm_client.generate_structured(
                prompt=prompt,
                schema=schema,
                temperature=0.8
            )
            
            podcast_data = response if isinstance(response, dict) else json.loads(response)
            return PodcastOutline(**podcast_data)
            
        except Exception as e:
            LOG.error(f"Failed to generate podcast outline: {e}")
            raise
    
    def convert_to_podcast_json(
        self,
        outline: PodcastOutline,
        output_path: Path
    ):
        """Convert podcast outline to Kokoro podcast JSON format."""
        
        # Map speakers to cast format
        cast = []
        speaker_voice_map = {}
        for index, speaker in enumerate(outline.speakers):
            display_name = speaker.id.replace("_", " ").title()
            cast.append({
                "speaker_id": speaker.id,
                "host_id": f"HOST_{chr(65 + index)}",
                "name": display_name,
                "voice_file": speaker.voice,
                "style": "Conversational and clear."
            })
            speaker_voice_map[speaker.id] = speaker.voice
        
        # Create script structure
        script = []
        current_segment = []
        segment_name = "Segment 1"
        segment_count = 1
        
        for i, segment in enumerate(outline.segments):
            emotion = (segment.emotion or "").lower()
            cue = next(
                (name for name in ("calm", "upbeat", "dramatic", "reflective") if name in emotion),
                "",
            )
            scene = {
                "speaker_id": segment.speaker,
                "dialogue": segment.text,
                "directions": f"[{cue}]" if cue else ""
            }
            current_segment.append(scene)
            if segment.pause_after_ms:
                current_segment.append({
                    "speaker_id": segment.speaker,
                    "dialogue": "",
                    "directions": f"[pause={min(max(segment.pause_after_ms, 0), 60000)}]",
                })
            
            # Start new segment every 4-5 scenes
            if len(current_segment) >= 5 or i == len(outline.segments) - 1:
                script.append({
                    "segment_name": segment_name,
                    "scenes": current_segment
                })
                current_segment = []
                segment_count += 1
                segment_name = f"Segment {segment_count}"
        
        # Create final podcast JSON
        podcast_json = {
            "episode_title": outline.title,
            "podcast_show": "AI Generated Podcast",
            "cast": cast,
            "script": script
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(podcast_json, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        LOG.info(f"Saved podcast JSON to {output_path}")
        return output_path
    
    def generate_audio(
        self,
        topic: str,
        output_path: Path,
        source_id: Optional[str] = None,
        duration_minutes: int = 10,
        speakers: Optional[List[dict]] = None,
        style: str = "educational",
        audio_format: str = "mp3",
        device: str = "auto",
    ):
        """Complete pipeline: generate outline, convert to JSON, and create audio."""
        
        # Generate outline
        outline = self.generate_podcast_outline(
            topic, source_id, duration_minutes, speakers, style
        )
        
        # Convert to podcast JSON
        json_path = output_path.with_suffix(".json")
        self.convert_to_podcast_json(outline, json_path)
        
        # Generate audio using existing podcast.py
        try:
            from podcast import main as podcast_main
            import sys
            
            # Prepare arguments for podcast generation
            original_argv = sys.argv
            sys.argv = [
                "podcast.py",
                "--input", str(json_path),
                "--output", str(output_path),
                "--format", audio_format,
                "--device", device,
            ]
            
            LOG.info("Generating audio with Kokoro...")
            try:
                result = podcast_main()
            finally:
                sys.argv = original_argv
            
            if result == 0:
                LOG.info(f"Successfully generated audio: {output_path}")
            else:
                LOG.error("Audio generation failed")
                
        except ImportError as e:
            LOG.error(f"Failed to import podcast module: {e}")
            LOG.info("Podcast JSON saved. Generate audio manually with: python podcast.py --input <json_path>")
        
        return output_path


def main():
    """CLI for audio generation."""
    import argparse
    from pathlib import Path
    from .client_interface import create_client
    
    parser = argparse.ArgumentParser(description="Generate audio podcasts using LLM")
    parser.add_argument("--input", type=Path, required=True, help="Input folder with documents")
    parser.add_argument("--topic", type=str, required=True, help="Podcast topic")
    parser.add_argument("--output", type=Path, required=True, help="Output audio file path")
    parser.add_argument("--duration", type=int, default=10, help="Target duration in minutes")
    parser.add_argument("--style", type=str, default="educational", help="Podcast style")
    parser.add_argument("--format", choices=["mp3", "wav"], default="mp3", help="Audio format")
    parser.add_argument("--provider", choices=["ollama", "openai", "claude"], default="ollama", help="LLM provider")
    parser.add_argument("--model", type=str, default="qwen2.5", help="Model to use")
    parser.add_argument("--embedding-model", type=str, default=None, help="Embedding model (provider-specific)")
    parser.add_argument("--api-key", type=str, default=None, help="API key for OpenAI/Claude")
    parser.add_argument("--json-only", action="store_true", help="Only generate JSON, not audio")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto", help="Kokoro device")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # Initialize client
    client_kwargs = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    if args.embedding_model:
        client_kwargs["embedding_model"] = args.embedding_model
    
    llm_client = create_client(args.provider, args.model, **client_kwargs)
    
    # Initialize RAG (skip for Claude since it doesn't have embeddings)
    if args.provider == "claude":
        LOG.warning("Claude doesn't support embeddings. RAG will be disabled.")
        rag = None
    else:
        rag = RAGSystem(llm_client)
    
    # Ingest documents (only if RAG is available)
    if rag:
        LOG.info(f"Ingesting documents from {args.input}")
        for file_path in args.input.glob("*.txt"):
            LOG.info(f"Processing {file_path.name}")
            rag.add_document_from_file(file_path)
    else:
        LOG.info("Skipping document ingestion (no RAG available)")
    
    # Generate podcast
    generator = AudioGenerator(llm_client, rag)
    
    if args.json_only:
        # Only generate JSON
        outline = generator.generate_podcast_outline(
            args.topic, duration_minutes=args.duration, style=args.style
        )
        json_path = args.output.with_suffix(".json")
        generator.convert_to_podcast_json(outline, json_path)
    else:
        # Generate complete audio
        generator.generate_audio(
            args.topic, args.output, duration_minutes=args.duration, style=args.style,
            audio_format=args.format, device=args.device
        )


if __name__ == "__main__":
    main()
