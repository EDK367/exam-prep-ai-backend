"""
AI-powered content generation service.
Generates exams, flashcards, summaries, and explanations from document chunks.
"""
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BitacoraStatus
from app.core.exceptions import AIServiceError, PlanLimitExceededError
from app.modules.ai.client import ai_client, AIResponse
from app.modules.ai.prompts import PROMPTS
from app.modules.shared.bitacora_service import bitacora_service

logger = structlog.get_logger(__name__)


class ContentGenerationService:
    """
    Generates educational content from document text using AI.
    All methods log token usage to Bitacora.
    """

    # ── Exam Generation ──────────────────────────────────────────────────

    async def generate_exam(
        self,
        db: AsyncSession,
        user_id: UUID,
        text: str,
        *,
        question_count: int = 10,
        difficulty: str = "medium",
        model: str = "deepseek/deepseek-v4-flash:free",
        max_tokens_budget: Optional[int] = None,
        concept_mode: bool = False,
        multiple_answers: bool = False,
    ) -> dict:
        """Generate a complete exam from text content."""

        # Check budget if applicable
        if max_tokens_budget:
            budget = await bitacora_service.check_token_budget(
                db, user_id, max_tokens_budget
            )
            if not budget["is_within_budget"]:
                raise PlanLimitExceededError(
                    "tokens", budget["total_tokens"], max_tokens_budget
                )

        prompt_base = PROMPTS["exam_generation"]
        if concept_mode:
            prompt_base += "\n- Para 'concept_mode', incluye preguntas de tipo 'open_question' donde 'correct_answer' sea la idea principal."
        if multiple_answers:
            prompt_base += "\n- Para 'multiple_answers', incluye opciones múltiples con tipo 'multiple_choice' donde 'correct_answer' sea un array (lista) de las respuestas correctas, ejemplo: [\"Opción A\", \"Opción C\"]."
            
        prompt = prompt_base.format(
            text=text,
            question_count=question_count,
            difficulty=difficulty,
        )

        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
            )

            # Log usage
            await bitacora_service.log_from_ai_response(
                db, user_id, ai_response, request_type="exam_generation"
            )

            return self._validate_exam_response(parsed)

        except AIServiceError as exc:
            await bitacora_service.log_failure(
                db,
                user_id,
                model=model,
                error_message=str(exc),
                request_type="exam_generation",
            )
            raise

    async def generate_exam_from_chunks(
        self,
        db: AsyncSession,
        user_id: UUID,
        chunks: list[str],
        *,
        question_count: int = 10,
        difficulty: str = "medium",
        model: str = "deepseek/deepseek-v4-flash:free",
        max_tokens_budget: Optional[int] = None,
        concept_mode: bool = False,
        multiple_answers: bool = False,
    ) -> dict:
        """Generate exam from multiple text chunks, combining results."""
        all_questions = []
        title = "Examen generado automáticamente"
        questions_per_chunk = max(2, question_count // len(chunks))

        for i, chunk in enumerate(chunks):
            try:
                result = await self.generate_exam(
                    db,
                    user_id,
                    chunk,
                    question_count=questions_per_chunk,
                    difficulty=difficulty,
                    model=model,
                    max_tokens_budget=max_tokens_budget,
                    concept_mode=concept_mode,
                    multiple_answers=multiple_answers,
                )
                if i == 0 and "title" in result:
                    title = result["title"]
                if "questions" in result:
                    all_questions.extend(result["questions"])
            except PlanLimitExceededError:
                raise
            except Exception as exc:
                logger.warning(
                    "chunk_exam_generation_failed",
                    chunk_index=i,
                    error=str(exc),
                )
                continue

        return {"title": title, "questions": all_questions[:question_count]}

    # ── Flashcard Generation ─────────────────────────────────────────────

    async def generate_flashcards(
        self,
        db: AsyncSession,
        user_id: UUID,
        text: str,
        *,
        count: int = 15,
        model: str = "deepseek/deepseek-v4-flash:free",
    ) -> dict:
        """Generate flashcards from text content."""
        prompt = PROMPTS["flashcard_generation"].format(text=text, count=count)

        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
            )

            await bitacora_service.log_from_ai_response(
                db, user_id, ai_response, request_type="flashcard_generation"
            )

            return self._validate_flashcard_response(parsed)

        except AIServiceError as exc:
            await bitacora_service.log_failure(
                db, user_id, model=model, error_message=str(exc),
                request_type="flashcard_generation",
            )
            raise

    # ── Summary Generation ───────────────────────────────────────────────

    async def generate_summary(
        self,
        db: AsyncSession,
        user_id: UUID,
        text: str,
        *,
        model: str = "deepseek/deepseek-v4-flash:free",
    ) -> dict:
        """Generate a structured summary from text content."""
        prompt = PROMPTS["summary_generation"].format(text=text)

        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.2,
            )

            await bitacora_service.log_from_ai_response(
                db, user_id, ai_response, request_type="summary_generation"
            )

            return parsed

        except AIServiceError as exc:
            await bitacora_service.log_failure(
                db, user_id, model=model, error_message=str(exc),
                request_type="summary_generation",
            )
            raise

    # ── Explanation Generation ───────────────────────────────────────────

    async def generate_explanation(
        self,
        db: AsyncSession,
        user_id: UUID,
        question: str,
        context: str,
        *,
        model: str = "deepseek/deepseek-v4-flash:free",
    ) -> dict:
        """Generate a detailed explanation for a question."""
        prompt = PROMPTS["explanation_generation"].format(
            question=question, context=context
        )

        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.2,
            )

            await bitacora_service.log_from_ai_response(
                db, user_id, ai_response, request_type="explanation_generation"
            )

            return parsed

        except AIServiceError as exc:
            await bitacora_service.log_failure(
                db, user_id, model=model, error_message=str(exc),
                request_type="explanation_generation",
            )
            raise

    # ── Concept Mode Evaluation ──────────────────────────────────────────

    async def evaluate_concept_answer(
        self,
        db: Optional[AsyncSession],
        user_id: UUID,
        question: str,
        user_answer: str,
        correct_answer: str,
        *,
        model: str = "deepseek/deepseek-v4-flash:free",
    ) -> dict:
        """Evaluate an open concept question response."""
        prompt = f"""Eres un profesor evaluando una respuesta abierta.
        
PREGUNTA: {question}
RESPUESTA ESPERADA: {correct_answer}
RESPUESTA DEL ESTUDIANTE: {user_answer}

INSTRUCCIONES:
1. Evalúa si la respuesta del estudiante captura la idea principal de la respuesta esperada.
2. Asigna un puntaje de 0.0 a 1.0 (1.0 = perfecta, 0.5 = parcialmente correcta, 0.0 = incorrecta).
3. Proporciona una breve explicación de la calificación.

FORMATO (SOLO JSON):
{{
    "score": 0.8,
    "is_correct": true,  // true si el score es >= 0.6
    "explanation": "Buena comprensión, pero faltó mencionar X."
}}
"""
        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.1,
            )

            if db is not None:
                await bitacora_service.log_from_ai_response(
                    db, user_id, ai_response, request_type="evaluation_generation"
                )

            return {
                "score": float(parsed.get("score", 0.0)),
                "is_correct": bool(parsed.get("is_correct", False)),
                "explanation": str(parsed.get("explanation", "")),
                "ai_response": ai_response,
            }

        except AIServiceError as exc:
            if db is not None:
                await bitacora_service.log_failure(
                    db, user_id, model=model, error_message=str(exc),
                    request_type="evaluation_generation",
                )
            return {
                "score": 0.0,
                "is_correct": False,
                "explanation": "Error evaluating response.",
                "ai_response": None,
                "error": str(exc),
            }

    # ── Response Validation ──────────────────────────────────────────────

    @staticmethod
    def _validate_exam_response(data: dict) -> dict:
        """Validate and normalize exam JSON structure."""
        if "questions" not in data:
            raise AIServiceError("AI response missing 'questions' field")

        questions = data["questions"]
        if not isinstance(questions, list) or len(questions) == 0:
            raise AIServiceError("AI response has empty or invalid questions")

        validated_questions = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            if "question" not in q:
                continue

            validated_q = {
                "question": str(q["question"]),
                "type": q.get("type", "multiple_choice"),
            }

            if "options" in q:
                validated_q["options"] = [str(o) for o in q["options"]]
            if "correct_answer" in q:
                if isinstance(q["correct_answer"], list):
                    validated_q["correct_answer"] = [str(a) for a in q["correct_answer"]]
                else:
                    validated_q["correct_answer"] = str(q["correct_answer"])
            if "explanation" in q:
                validated_q["explanation"] = str(q["explanation"])

            validated_questions.append(validated_q)

        return {
            "title": data.get("title", "Examen generado"),
            "questions": validated_questions,
        }

    @staticmethod
    def _validate_flashcard_response(data: dict) -> dict:
        """Validate and normalize flashcard JSON structure."""
        if "flashcards" not in data:
            raise AIServiceError("AI response missing 'flashcards' field")

        flashcards = data["flashcards"]
        validated = []
        for fc in flashcards:
            if isinstance(fc, dict) and "front" in fc and "back" in fc:
                validated.append({
                    "front": str(fc["front"]),
                    "back": str(fc["back"]),
                    "category": fc.get("category", ""),
                })

        return {"flashcards": validated}


content_generation_service = ContentGenerationService()
