"""
Test service — orchestrates test creation, AI generation, submission, and scoring.
"""
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TestStatus, DocumentStatus
from app.core.exceptions import ValidationError, NotFoundError, PlanLimitExceededError
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
        model: str = "deepseek/deepseek-v4-flash:free",
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

        # Plan limits validation for hard mode
        if plan_name.lower() == "free" and question_count > 10:
            raise PlanLimitExceededError("questions", question_count, 10)
            
        if hard_mode:
            if plan_name.lower() in ["free", "pro"]:
                raise PlanLimitExceededError("hard_mode", 1, 0)
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
                raise ValidationError("AI generated no questions")

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
        Submit all answers for a test and calculate score.
        answers: [{ question_id, response_text }]
        """
        test = await test_repo.verify_ownership(db, test_id, user_id)
        test_with_q = await test_repo.get_with_questions(db, test_id)

        if not test_with_q or not test_with_q.questions:
            raise ValidationError("Test has no questions")

        total = len(test_with_q.questions)

        import asyncio
        
        # Build question lookup
        question_map = {str(q.id): q for q in test_with_q.questions}

        # Gather concept tasks for concurrent execution to prevent timeouts
        concept_tasks = []
        concept_indices = []
        
        for i, answer in enumerate(answers):
            q_id = str(answer["question_id"])
            if q_id not in question_map:
                continue
            question = question_map[q_id]
            user_answer = answer["response_text"]
            
            if question.questions_type == "open_question":
                concept_tasks.append(
                    content_generation_service.evaluate_concept_answer(
                        None, user_id, 
                        question.content.get("question", ""),
                        str(user_answer),
                        str(question.content.get("correct_answer", ""))
                    )
                )
                concept_indices.append(i)
                
        concept_results_map = {}
        if concept_tasks:
            # We use gather to evaluate all concept questions in parallel (safe because db is None)
            concept_results = await asyncio.gather(*concept_tasks)
            
            # Now sequentially perform database logging using the db session
            from app.modules.shared.bitacora_service import bitacora_service
            for res in concept_results:
                try:
                    if res.get("ai_response") is not None:
                        await bitacora_service.log_from_ai_response(
                            db, user_id, res["ai_response"], request_type="evaluation_generation"
                        )
                    elif res.get("error") is not None:
                        await bitacora_service.log_failure(
                            db, user_id,
                            model="deepseek/deepseek-v4-flash:free",
                            error_message=res["error"],
                            request_type="evaluation_generation"
                        )
                except Exception as log_exc:
                    logger.error("failed_to_log_usage_to_bitacora", error=str(log_exc))

            concept_results_map = {idx: res for idx, res in zip(concept_indices, concept_results)}

        # Grade each answer
        graded_responses = []
        # Calculate score dynamically
        total_points = 0.0
        earned_points = 0.0
        
        for i, answer in enumerate(answers):
            q_id = str(answer["question_id"])
            if q_id not in question_map:
                continue

            question = question_map[q_id]
            user_answer = answer["response_text"]
            
            # Use AI grading for concept mode (open_question)
            if question.questions_type == "open_question":
                eval_result = concept_results_map[i]
                is_correct = eval_result["is_correct"]
                score_val = eval_result["score"]
                # Save the explanation back to the content so the user can see it
                if not question.content:
                    question.content = {}
                
                # SQLAlchemy JSON mutations sometimes require reassignment to trigger update
                new_content = dict(question.content)
                new_content["explanation"] = eval_result["explanation"]
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

        # Calculate score
        score_percent = (earned_points / total_points * 100) if total_points > 0 else 0
        
        correct = sum(1 for r in graded_responses if r["is_correct"])

        # Update test
        await test_repo.update(db, test, {"score": score_percent})
        test = await test_repo.update_status(db, test_id, TestStatus.COMPLETED)

        logger.info(
            "test_submitted",
            test_id=str(test_id),
            score=score_percent,
            correct=correct,
            total=total,
        )

        return {
            "test_id": test.id,
            "title": test.title,
            "total_questions": total,
            "correct_answers": correct,
            "incorrect_answers": total - correct,
            "unanswered": total - len(graded_responses),
            "score_percent": round(score_percent, 1),
            "passed": score_percent >= 60.0,
            "passing_score": 60.0,
        }

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
        for q in test_detail.questions:
            user_resp = q.user_responses[0] if q.user_responses else None
            is_correct = user_resp.is_correct if user_resp else None
            if is_correct:
                correct_count += 1

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
        score = (correct_count / total * 100) if total > 0 else 0

        return {
            "test_id": test.id,
            "title": test.title,
            "total_questions": total,
            "correct_answers": correct_count,
            "incorrect_answers": total - correct_count,
            "unanswered": sum(1 for q in questions_with_answers if q["is_correct"] is None),
            "score_percent": round(score, 1),
            "passed": score >= 60.0,
            "passing_score": 60.0,
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

    # ── Grading ──────────────────────────────────────────────────────────

    @staticmethod
    def _grade_answer(question, user_answer) -> bool:
        """Grade a single answer against the question's correct answer."""
        content = question.content
        if not content:
            return False

        correct = content.get("correct_answer", "")
        q_type = question.questions_type or "multiple_choice"

        if q_type == "true_false":
            user_str = str(user_answer).lower().strip()
            correct_str = str(correct).lower().strip()
            truthy_vals = {"true", "verdadero", "t", "v", "yes", "si", "sí", "1"}
            falsy_vals = {"false", "falso", "f", "no", "0"}
            
            if user_str in truthy_vals and correct_str in truthy_vals:
                return True
            if user_str in falsy_vals and correct_str in falsy_vals:
                return True
                
            return user_str == correct_str

        if q_type == "multiple_choice":
            if isinstance(correct, list):
                if isinstance(user_answer, list) and "options" in content:
                    options = content["options"]
                    # user_answer is list of indices
                    selected = [options[i] for i in user_answer if isinstance(i, int) and 0 <= i < len(options)]
                    # Exact match of selections vs correct
                    return set(selected) == set(correct)
                return False

            if isinstance(user_answer, int) and "options" in content:
                options = content["options"]
                if 0 <= user_answer < len(options):
                    return options[user_answer] == correct
            return str(user_answer).strip().lower() == str(correct).strip().lower()

        # open_question — simple string match (could integrate AI grading)
        return str(user_answer).strip().lower() == str(correct).strip().lower()


test_service = TestService()
