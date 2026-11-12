"""
AI-powered content generation service.
Generates exams, flashcards, summaries, and explanations from document chunks.
"""
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BitacoraStatus
from app.core.exceptions import AIServiceError, PlanLimitExceededError, AIRateLimitError
from app.modules.ai.client import ai_client, AIResponse
from app.modules.ai.prompts import PROMPTS
from app.modules.ai.semantic_generator import SemanticExamGenerator
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
        db: Optional[AsyncSession],
        user_id: UUID,
        text: str,
        *,
        question_count: int = 10,
        difficulty: str = "medium",
        model: str = "liquid/lfm-2.5-2.6b:free",
        max_tokens_budget: Optional[int] = None,
        concept_mode: bool = False,
        multiple_answers: bool = False,
    ) -> dict:
        """Generate a complete exam from text content, guaranteeing the exact requested question count."""

        # Check budget if applicable and db is available
        if max_tokens_budget and db is not None:
            budget = await bitacora_service.check_token_budget(
                db, user_id, max_tokens_budget
            )
            if not budget["is_within_budget"]:
                raise PlanLimitExceededError(
                    "tokens", budget["total_tokens"], max_tokens_budget
                )

        prompt_base = PROMPTS["exam_generation"]
        if concept_mode:
            prompt_base += "\n- Para 'concept_mode', incluye preguntas de redacción conceptual con 'type': 'open_question' donde 'question' pida al estudiante redactar o explicar un concepto técnico clave (ej: 'Explique qué es...'), 'correct_answer' sea la respuesta modelo o esperada explicativa completa, y 'options' sea []."
        if multiple_answers:
            prompt_base += "\n- Para 'multiple_answers', incluye opciones múltiples con tipo 'multiple_choice' donde 'correct_answer' sea un array (lista) de las respuestas correctas, ejemplo: [\"Opción A\", \"Opción C\"]."
            
        prompt = prompt_base.format(
            text=text[:4000],  # Keep prompt compact for free tier context
            question_count=question_count,
            difficulty=difficulty,
        )

        all_questions = []
        exam_title = "Examen generado automáticamente"
        last_ai_response = None

        try:
            parsed, ai_response = await ai_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
            )
            last_ai_response = ai_response

            # Log usage if session provided
            if db is not None:
                await bitacora_service.log_from_ai_response(
                    db, user_id, ai_response, request_type="exam_generation"
                )

            res = self._validate_exam_response(parsed)
            if res.get("title"):
                exam_title = res["title"]
            if res.get("questions"):
                all_questions.extend(res["questions"])

        except (AIServiceError, Exception) as exc:
            logger.warning("ai_exam_generation_fallback", error=str(exc))
            if db is not None:
                await bitacora_service.log_failure(
                    db,
                    user_id,
                    model=model,
                    error_message=str(exc),
                    request_type="exam_generation",
                )

        # Guarantee requested question count using semantic generator if needed
        if len(all_questions) < question_count:
            needed = question_count - len(all_questions)
            logger.info("completing_exam_questions_semantically", needed=needed, target=question_count)
            fallback_qs = SemanticExamGenerator.generate_questions(
                [text],
                question_count=needed,
                difficulty=difficulty,
                concept_mode=concept_mode,
                multiple_answers=multiple_answers,
                existing_questions=all_questions,
            )
            all_questions.extend(fallback_qs)

        return {
            "title": exam_title,
            "questions": all_questions[:question_count],
            "ai_response": last_ai_response,
        }

    async def generate_exam_from_chunks(
        self,
        db: AsyncSession,
        user_id: UUID,
        chunks: list[str],
        *,
        question_count: int = 10,
        difficulty: str = "medium",
        model: str = "liquid/lfm-2.5-2.6b:free",
        max_tokens_budget: Optional[int] = None,
        concept_mode: bool = False,
        multiple_answers: bool = False,
    ) -> dict:
        """
        Generate exam from multiple text chunks, combining results concurrently with
        controlled concurrency and guaranteed delivery of exact question count.
        """
        import asyncio

        # Check budget once before concurrent calls
        if max_tokens_budget and db is not None:
            budget = await bitacora_service.check_token_budget(
                db, user_id, max_tokens_budget
            )
            if not budget["is_within_budget"]:
                raise PlanLimitExceededError(
                    "tokens", budget["total_tokens"], max_tokens_budget
                )

        all_questions = []
        title = "Examen generado automáticamente"
        
        # Sample chunks evenly across the document (up to 6 chunks for large question counts)
        max_chunks_to_sample = min(len(chunks), max(4, (question_count + 3) // 3))
        if len(chunks) > max_chunks_to_sample:
            step = len(chunks) / float(max_chunks_to_sample)
            indices = sorted(set(int(i * step) for i in range(max_chunks_to_sample)))
            selected_chunks = [chunks[i] for i in indices]
        else:
            selected_chunks = chunks

        questions_per_chunk = max(3, (question_count + len(selected_chunks) - 1) // len(selected_chunks))

        # Use a semaphore of 2 to avoid bursting OpenRouter free tier concurrency limits
        semaphore = asyncio.Semaphore(2)

        async def _generate_single_chunk(chunk: str):
            async with semaphore:
                return await self.generate_exam(
                    None,
                    user_id,
                    chunk,
                    question_count=questions_per_chunk,
                    difficulty=difficulty,
                    model=model,
                    max_tokens_budget=max_tokens_budget,
                    concept_mode=concept_mode,
                    multiple_answers=multiple_answers,
                )

        tasks = [_generate_single_chunk(chunk) for chunk in selected_chunks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning("chunk_exam_generation_failed", chunk_index=i, error=str(res))
                continue
            if not title or title == "Examen generado automáticamente":
                if res.get("title"):
                    title = res["title"]
            if "questions" in res and isinstance(res["questions"], list):
                all_questions.extend(res["questions"])

            # Sequentially log usage to bitacora with db session
            if db is not None and res.get("ai_response"):
                try:
                    await bitacora_service.log_from_ai_response(
                        db, user_id, res["ai_response"], request_type="exam_generation"
                    )
                except Exception as b_err:
                    logger.warning("bitacora_log_error", error=str(b_err))

        # Check if we reached the requested question count
        if len(all_questions) < question_count:
            needed = question_count - len(all_questions)
            logger.info(
                "completing_exam_questions_with_semantic_generator",
                current_count=len(all_questions),
                target_count=question_count,
                needed=needed,
            )
            fallback_questions = SemanticExamGenerator.generate_questions(
                chunks,
                question_count=needed,
                difficulty=difficulty,
                concept_mode=concept_mode,
                multiple_answers=multiple_answers,
                existing_questions=all_questions,
            )
            all_questions.extend(fallback_questions)

        if not all_questions:
            # Final fallback guarantee
            all_questions = SemanticExamGenerator.generate_questions(
                chunks,
                question_count=question_count,
                difficulty=difficulty,
                concept_mode=concept_mode,
                multiple_answers=multiple_answers,
            )

        return {"title": title, "questions": all_questions[:question_count]}

    # ── Flashcard Generation ─────────────────────────────────────────────

    async def generate_flashcards(
        self,
        db: AsyncSession,
        user_id: UUID,
        text: str,
        *,
        count: int = 15,
        model: str = "liquid/lfm-2.5-2.6b:free",
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
        model: str = "liquid/lfm-2.5-2.6b:free",
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
        model: str = "liquid/lfm-2.5-2.6b:free",
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
        model: str = "liquid/lfm-2.5-2.6b:free",
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

            if "options" in q and isinstance(q["options"], list):
                validated_q["options"] = [str(o) for o in q["options"]]
            elif validated_q["type"] == "open_question":
                validated_q["options"] = []
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
