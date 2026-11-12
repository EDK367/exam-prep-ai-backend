"""
Test service — orchestrates test creation, AI generation, submission, and scoring.
"""
from typing import Optional, Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TestStatus, DocumentStatus
from app.core.exceptions import ValidationError, NotFoundError, PlanLimitExceededError, AIServiceError
from app.modules.ai.content_service import content_generation_service
from app.modules.documents.repository import document_repo, chunk_repo
from app.modules.tests.models import Test
from app.modules.tests.repository import (
    test_repo,
    question_repo,
    user_response_repo,
)

logger = structlog.get_logger(__name__)


class TestService:
    """
    High-level test operations:
    - Create test from document
    - Generate questions via AI
    - Submit answers
    - Score and evaluate
    """

    # ── Create & Generate ────────────────────────────────────────────────

    async def create_test_from_document(
        self,
        db: AsyncSession,
        user_id: UUID,
        document_id: UUID,
        *,
        title: Optional[str] = None,
        question_count: int = 10,
        difficulty: str = "medium",
        template_id: Optional[UUID] = None,
        max_tests: int = 100,
        max_tokens: Optional[int] = None,
        model: str = "liquid/lfm-2.5-2.6b:free",
        plan_name: str = "Free",
        hard_mode: bool = False,
        concept_mode: bool = False,
        multiple_answers: bool = False,
        no_go_back: bool = False,
    ) -> Test:
        """
        Create a test from a processed document:
        1. Verify document is chunked/completed
        2. Check test limits
        3. Create test record
        4. Generate questions via AI
        5. Save questions
        6. Update test status
        """
        # Verify document ownership and status
        doc = await document_repo.verify_ownership(db, document_id, user_id)
        doc_status = DocumentStatus(doc.status)
        if doc_status not in (DocumentStatus.CHUNKED, DocumentStatus.COMPLETED):
            raise ValidationError(
                f"Document must be processed before generating a test. "
                f"Current status: {doc_status.value}"
            )

        # Check test limit
        current_test_count = await test_repo.count_by_user(db, user_id)
        if current_test_count >= max_tests:
            raise PlanLimitExceededError("tests", current_test_count, max_tests)

        # Plan limits validation for questions and features
        plan_lower = plan_name.lower()
        if plan_lower == "free":
            if question_count > 10:
                raise PlanLimitExceededError("questions", question_count, 10, "El plan FREE permite hasta 10 preguntas por examen.")
            if hard_mode:
                raise PlanLimitExceededError("hard_mode", 1, 0, "El Modo Difícil está disponible únicamente en planes PLUS y PRO.")
            if concept_mode:
                raise PlanLimitExceededError("concept_mode", 1, 0, "Las Preguntas Abiertas con evaluación IA requieren plan PLUS o PRO.")
            if multiple_answers:
                raise PlanLimitExceededError("multiple_answers", 1, 0, "Las respuestas múltiples requieren plan PLUS o PRO.")
        elif plan_lower == "plus":
            if question_count > 30:
                raise PlanLimitExceededError("questions", question_count, 30, "El plan PLUS permite hasta 30 preguntas por examen.")
        elif question_count > 50:
            raise PlanLimitExceededError("questions", question_count, 50, "El plan PRO permite hasta 50 preguntas por examen.")

        if hard_mode:
            # Enforce min 10 questions for hard mode
            question_count = max(10, question_count)
            
        # Create test record
        test_config = {
            "hard_mode": hard_mode,
            "concept_mode": concept_mode,
            "multiple_answers": multiple_answers,
            "no_go_back": no_go_back,
        }
        
        test = Test(
            title=title or f"Examen: {doc.filename}",
            user_id=user_id,
            document_id=document_id,
            test_template_id=template_id,
            status=TestStatus.DRAFT.value,
            config=test_config,
        )
        test = await test_repo.create(db, test)

        # Transition to generating
        test = await test_repo.update_status(db, test.id, TestStatus.GENERATING)

        try:
            # Get document chunks
            chunks = await chunk_repo.get_by_document(db, document_id)
            chunk_texts = [c.content for c in chunks]

            # Generate exam via AI
            kwargs = {
                "question_count": question_count,
                "difficulty": difficulty,
                "model": model,
                "max_tokens_budget": max_tokens,
                "concept_mode": concept_mode,
                "multiple_answers": multiple_answers,
            }
            if len(chunk_texts) == 1:
                exam_data = await content_generation_service.generate_exam(
                    db, user_id, chunk_texts[0], **kwargs
                )
            else:
                exam_data = await content_generation_service.generate_exam_from_chunks(
                    db, user_id, chunk_texts, **kwargs
                )

            # Update title if AI provided one
            if exam_data.get("title"):
                await test_repo.update(db, test, {"title": exam_data["title"]})

            # Save questions
            questions = exam_data.get("questions", [])
            if not questions:
                raise AIServiceError("El servicio de IA no devolvió preguntas válidas para este documento.")

            await question_repo.bulk_create(db, test.id, questions)

            # Mark as ready
            test = await test_repo.update_status(db, test.id, TestStatus.READY)

            logger.info(
                "test_created",
                test_id=str(test.id),
                questions=len(questions),
            )

            return test

        except PlanLimitExceededError:
            await test_repo.update_status(
                db, test.id, TestStatus.FAILED,
                error_message="Token limit exceeded",
            )
            raise
        except Exception as exc:
            logger.error(
                "test_generation_failed",
                test_id=str(test.id),
                error=str(exc),
            )
            await test_repo.update_status(
                db, test.id, TestStatus.FAILED,
                error_message=str(exc),
            )
            raise

    # ── Start Test ───────────────────────────────────────────────────────

    async def start_test(
        self, db: AsyncSession, test_id: UUID, user_id: UUID
    ) -> Test:
        """Mark a test as in_progress."""
        test = await test_repo.verify_ownership(db, test_id, user_id)
        return await test_repo.update_status(db, test_id, TestStatus.IN_PROGRESS)

    # ── Submit Answers ───────────────────────────────────────────────────

    async def submit_test(
        self,
        db: AsyncSession,
        test_id: UUID,
        user_id: UUID,
        answers: list[dict],
    ) -> dict:
        """
        Submit all answers for a test and calculate score immediately for objective questions.
        Open-ended questions (concept_mode) are scheduled for asynchronous AI evaluation in the background,
        allowing the user to immediately view the results of their objective questions without waiting.
        answers: [{ question_id, response_text }]
        """
        import asyncio
        test = await test_repo.verify_ownership(db, test_id, user_id)
        test_with_q = await test_repo.get_with_questions(db, test_id)

        if not test_with_q or not test_with_q.questions:
            raise ValidationError("Test has no questions")

        total = len(test_with_q.questions)
        question_map = {str(q.id): q for q in test_with_q.questions}

        pending_concept_items = []
        graded_responses = []
        total_points = 0.0
        earned_points = 0.0

        for answer in answers:
            q_id = str(answer["question_id"])
            if q_id not in question_map:
                continue

            question = question_map[q_id]
            user_answer = answer["response_text"]
            has_text = user_answer is not None and str(user_answer).strip() != ""

            if question.questions_type == "open_question":
                if has_text:
                    # Pending AI evaluation
                    is_correct = None
                    score_val = 0.0
                    pending_concept_items.append({
                        "question_id": question.id,
                        "user_answer": str(user_answer).strip(),
                        "question_text": question.content.get("question", "") if question.content else "",
                        "expected_answer": str(question.content.get("correct_answer", "")) if question.content else "",
                    })
                else:
                    # Left blank
                    is_correct = False
                    score_val = 0.0
                    if not question.content:
                        question.content = {}
                    new_content = dict(question.content)
                    new_content["explanation"] = "No se proporcionó respuesta para esta pregunta abierta."
                    question.content = new_content
            else:
                is_correct = self._grade_answer(question, user_answer)
                score_val = 1.0 if is_correct else 0.0

            total_points += 1.0
            earned_points += score_val

            graded_responses.append({
                "question_id": question.id,
                "response_text": user_answer,
                "is_correct": is_correct,
            })

        # Save responses
        await user_response_repo.bulk_create(db, graded_responses)

        # Preliminary score based on completed answers
        score_percent = (earned_points / total_points * 100.0) if total_points > 0 else 0.0
        correct = sum(1 for r in graded_responses if r["is_correct"] is True)

        # Update test
        await test_repo.update(db, test, {"score": round(score_percent, 1)})
        test = await test_repo.update_status(db, test_id, TestStatus.COMPLETED)

        # Launch background AI evaluation for open questions if any exist
        if pending_concept_items:
            asyncio.create_task(
                self._evaluate_open_questions_in_background(test_id, user_id, pending_concept_items)
            )

        logger.info(
            "test_submitted",
            test_id=str(test_id),
            score=round(score_percent, 1),
            correct=correct,
            total=total,
            pending_ai_eval=len(pending_concept_items),
        )

        return {
            "test_id": test.id,
            "title": test.title,
            "total_questions": total,
            "correct_answers": correct,
            "incorrect_answers": total - correct - len(pending_concept_items),
            "unanswered": sum(1 for r in graded_responses if r["response_text"] is None or str(r["response_text"]).strip() == ""),
            "score_percent": round(score_percent, 1),
            "passed": score_percent >= 60.0,
            "passing_score": 60.0,
            "has_pending_evaluations": len(pending_concept_items) > 0,
        }

    async def _evaluate_open_questions_in_background(
        self,
        test_id: UUID,
        user_id: UUID,
        pending_items: list[dict],
    ) -> None:
        """
        Background task to evaluate open-ended questions using AI without blocking the user.
        Uses an isolated AsyncSessionLocal database session.
        """
        import asyncio
        from app.db.session import AsyncSessionLocal
        from app.modules.shared.bitacora_service import bitacora_service

        logger.info("bg_evaluating_open_questions_start", test_id=str(test_id), count=len(pending_items))

        tasks = []
        for item in pending_items:
            tasks.append(
                content_generation_service.evaluate_concept_answer(
                    None,
                    user_id,
                    item["question_text"],
                    item["user_answer"],
                    item["expected_answer"]
                )
            )

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error("bg_eval_gather_failed", error=str(e))
            results = [e] * len(pending_items)

        async with AsyncSessionLocal() as db:
            try:
                for item, res in zip(pending_items, results):
                    qid = item["question_id"]
                    if isinstance(res, Exception):
                        is_correct = False
                        score_val = 0.0
                        explanation = f"Evaluación no disponible: {str(res)}"
                    else:
                        is_correct = bool(res.get("is_correct", False))
                        score_val = float(res.get("score", 0.0))
                        explanation = str(res.get("explanation", ""))

                        try:
                            if res.get("ai_response"):
                                await bitacora_service.log_from_ai_response(
                                    db, user_id, res["ai_response"], request_type="evaluation_generation"
                                )
                        except Exception as b_err:
                            logger.error("bitacora_log_error", error=str(b_err))

                    # Update UserResponse in DB
                    user_resps = await user_response_repo.get_by_question(db, qid)
                    for ur in user_resps:
                        ur.is_correct = is_correct

                    # Update Question explanation in content JSON
                    q = await question_repo.get_by_id(db, qid)
                    if q:
                        new_content = dict(q.content or {})
                        new_content["explanation"] = explanation
                        q.content = new_content

                await db.commit()

                # Recalculate test overall score
                test_with_q = await test_repo.get_with_questions_and_responses(db, test_id)
                if test_with_q and test_with_q.questions:
                    total_q = len(test_with_q.questions)
                    correct_count = 0
                    for q in test_with_q.questions:
                        if q.user_responses and q.user_responses[0].is_correct is True:
                            correct_count += 1
                    final_score = (correct_count / total_q * 100.0) if total_q > 0 else 0.0
                    await test_repo.update(db, test_with_q, {"score": round(final_score, 1)})
                    await db.commit()
                    logger.info("bg_evaluating_open_questions_finished", test_id=str(test_id), final_score=final_score)
            except Exception as exc:
                await db.rollback()
                logger.error("bg_eval_persist_failed", test_id=str(test_id), error=str(exc))

    # ── Get Results ──────────────────────────────────────────────────────

    async def get_test_results(
        self, db: AsyncSession, test_id: UUID, user_id: UUID
    ) -> dict:
        """Get detailed test results with questions and answers."""
        test = await test_repo.verify_ownership(db, test_id, user_id)
        test_detail = await test_repo.get_with_questions_and_responses(db, test_id)

        if not test_detail:
            raise NotFoundError("Test", str(test_id))

        questions_with_answers = []
        correct_count = 0
        has_pending = False
        for q in test_detail.questions:
            user_resp = q.user_responses[0] if q.user_responses else None
            is_correct = user_resp.is_correct if user_resp else None
            if is_correct is True:
                correct_count += 1
            elif is_correct is None and user_resp is not None and user_resp.response_text and str(user_resp.response_text).strip():
                has_pending = True

            questions_with_answers.append({
                "id": q.id,
                "questions_type": q.questions_type,
                "points": q.points,
                "content": q.content,
                "user_answer": user_resp.response_text if user_resp else None,
                "is_correct": is_correct,
                "explanation": q.content.get("explanation") if q.content else None,
                "created_at": q.created_at,
            })

        total = len(test_detail.questions)
        score = test.score if test.score is not None else ((correct_count / total * 100.0) if total > 0 else 0.0)

        return {
            "test_id": test.id,
            "title": test.title,
            "total_questions": total,
            "correct_answers": correct_count,
            "incorrect_answers": total - correct_count - (1 if has_pending else 0),
            "unanswered": sum(1 for q in questions_with_answers if q["user_answer"] is None or str(q["user_answer"]).strip() == ""),
            "score_percent": round(score, 1),
            "passed": score >= 60.0,
            "passing_score": 60.0,
            "has_pending_evaluations": has_pending,
            "questions": questions_with_answers,
        }

    # ── Query ────────────────────────────────────────────────────────────

    async def list_tests(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        status: Optional[TestStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        return await test_repo.get_by_user(
            db, user_id, status=status, page=page, page_size=page_size
        )

    async def get_test_detail(
        self, db: AsyncSession, test_id: UUID, user_id: UUID
    ) -> Test:
        await test_repo.verify_ownership(db, test_id, user_id)
        test = await test_repo.get_with_questions(db, test_id)
        if not test:
            raise NotFoundError("Test", str(test_id))
        return test

    async def delete_test(
        self, db: AsyncSession, test_id: UUID, user_id: UUID
    ) -> None:
        test = await test_repo.verify_ownership(db, test_id, user_id)
        await test_repo.delete(db, test)

    async def retake_test(self, db: AsyncSession, test_id: UUID, user_id: UUID) -> Test:
        """Clear responses and reset a test so it can be taken again."""
        test = await test_repo.verify_ownership(db, test_id, user_id)
        
        test_with_q = await test_repo.get_with_questions_and_responses(db, test_id)
        if test_with_q:
            for q in test_with_q.questions:
                for resp in q.user_responses:
                    await db.delete(resp)
                    
        await test_repo.update(db, test, {"score": None})
        test = await test_repo.update_status(db, test_id, TestStatus.READY)
        return test

    # ── Grading & Normalization ──────────────────────────────────────────

    @staticmethod
    def _to_boolean(val: Any, options: Optional[list] = None) -> Optional[bool]:
        """Convert any user or AI answer variant into a boolean True/False."""
        if isinstance(val, bool):
            return val
        if val is None:
            return None
        if isinstance(val, int) and options and 0 <= val < len(options):
            return TestService._to_boolean(options[val])
            
        import re
        s = str(val).strip().lower()
        clean = re.sub(r'^[a-d0-9][\)\.\:\-]\s*|\([a-d0-9]\)\s*', '', s).strip().rstrip('.;,')
        truthy_words = {"verdadero", "true", "v", "t", "cierto", "correcto", "si", "sí", "yes"}
        falsy_words = {"falso", "false", "f", "incorrecto", "no"}

        if clean in truthy_words or s in truthy_words:
            return True
        if clean in falsy_words or s in falsy_words:
            return False

        if options and len(options) >= 2:
            if s in {"a", "opción a", "opcion a", "0"}:
                return TestService._to_boolean(options[0])
            elif s in {"b", "opción b", "opcion b", "1"}:
                return TestService._to_boolean(options[1])

        if s == "1":
            return True
        if s == "0":
            return False

        return None

    @staticmethod
    def _normalize_text(val: Any) -> str:
        """Normalize answer text by stripping option prefixes and extra punctuation."""
        if val is None:
            return ""
        import re
        s = str(val).strip().lower()
        # Strip option prefixes like "a) ", "b. ", "1: ", "(c) "
        s = re.sub(r'^[a-d0-9][\)\.\:\-]\s*|\([a-d0-9]\)\s*', '', s).strip()
        s = s.rstrip('.;,')
        s = re.sub(r'\s+', ' ', s)
        return s

    @classmethod
    def _grade_answer(cls, question, user_answer) -> bool:
        """Grade a single answer against the question's correct answer."""
        content = question.content
        if not content:
            return False

        correct = content.get("correct_answer", "")
        q_type = question.questions_type or "multiple_choice"
        options = content.get("options", [])

        if q_type == "true_false":
            user_bool = cls._to_boolean(user_answer, options)
            correct_bool = cls._to_boolean(correct, options)
            if user_bool is not None and correct_bool is not None:
                return user_bool == correct_bool
            return cls._normalize_text(user_answer) == cls._normalize_text(correct)

        if q_type == "multiple_choice":
            # 1. Multiple answers mode (correct is list of answers)
            if isinstance(correct, list):
                correct_norm_set = {cls._normalize_text(c) for c in correct}
                if isinstance(user_answer, list):
                    user_items = []
                    for item in user_answer:
                        if isinstance(item, int) and options and 0 <= item < len(options):
                            user_items.append(options[item])
                        else:
                            user_items.append(item)
                    user_norm_set = {cls._normalize_text(u) for u in user_items}
                    return user_norm_set == correct_norm_set
                return False

            # 2. Integer index
            if isinstance(user_answer, int) and options and 0 <= user_answer < len(options):
                user_text = options[user_answer]
                return cls._normalize_text(user_text) == cls._normalize_text(correct)

            # 3. Single letter option e.g. "a", "b", "c", "d"
            user_str = str(user_answer).strip().lower()
            if len(user_str) == 1 and user_str in "abcd" and options:
                idx = ord(user_str) - ord("a")
                if 0 <= idx < len(options):
                    return cls._normalize_text(options[idx]) == cls._normalize_text(correct)

            # 4. Direct match or normalized text comparison
            if str(user_answer).strip().lower() == str(correct).strip().lower():
                return True
            return cls._normalize_text(user_answer) == cls._normalize_text(correct)

        # open_question fallback
        return cls._normalize_text(user_answer) == cls._normalize_text(correct)


test_service = TestService()
