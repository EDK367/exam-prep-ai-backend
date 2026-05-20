"""
AI prompt templates for content generation.
Centralized to enable easy tuning and A/B testing.
"""

PROMPTS = {
    "exam_generation": """Eres un generador experto de exámenes académicos.

OBJETIVO:
Crear un examen basado ÚNICAMENTE en el contenido relevante del texto proporcionado.

TEXTO:
{text}

INSTRUCCIONES IMPORTANTES:

1. ANALIZA el texto y FILTRA:
   - Ignora reglamentos, normas institucionales, introducciones, dedicatorias, índices o contenido no académico.
   - Quédate SOLO con contenido educativo clave (conceptos, definiciones, procesos, datos importantes).

2. LENGUAJE:
   - Usa el mismo estilo, terminología y nivel técnico del texto original.
   - No simplifiques demasiado ni inventes contenido externo.

3. PREGUNTAS:
   - Genera exactamente {question_count} preguntas.
   - Dificultad: {difficulty}
   - Mezcla tipos:
     - Opción múltiple (4 opciones) → type: "multiple_choice"
     - Verdadero/Falso → type: "true_false"
   - Evita preguntas obvias o triviales.
   - Asegúrate de que evalúen comprensión real.

4. RESPUESTAS:
   - Distribuye correctamente las respuestas (no todas en la misma posición).
   - Evita patrones repetitivos.
   - Las opciones incorrectas deben ser plausibles.
   - Incluye una breve explicación de por qué la respuesta correcta es correcta.

5. FORMATO (OBLIGATORIO):
Devuelve SOLO JSON válido, sin texto adicional.

Estructura EXACTA:
{{
    "title": "Título del examen basado en el tema principal",
    "questions": [
        {{
            "question": "Pregunta clara",
            "type": "multiple_choice",
            "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
            "correct_answer": "Texto EXACTO de la respuesta correcta",
            "explanation": "Breve explicación"
        }}
    ]
}}

RESTRICCIONES:
- NO agregues explicaciones fuera del JSON
- NO agregues texto fuera del JSON
- NO uses comillas inválidas
- NO dejes campos vacíos""",

    "flashcard_generation": """Eres un experto en educación y técnicas de estudio.

TEXTO:
{text}

INSTRUCCIONES:
1. Genera exactamente {count} flashcards basadas en el contenido del texto.
2. Cada flashcard debe tener:
   - "front": Una pregunta clara o concepto clave
   - "back": La respuesta o definición completa
   - "category": Categoría temática
3. Las flashcards deben cubrir los conceptos más importantes.
4. Usa el mismo idioma y terminología del texto original.

FORMATO (SOLO JSON):
{{
    "flashcards": [
        {{
            "front": "¿Qué es...?",
            "back": "Es...",
            "category": "Categoría"
        }}
    ]
}}

Devuelve SOLO el JSON, sin texto adicional.""",

    "summary_generation": """Eres un experto en síntesis académica.

TEXTO:
{text}

INSTRUCCIONES:
1. Genera un resumen estructurado del texto.
2. Incluye:
   - "title": Título del tema
   - "summary": Resumen general (2-3 párrafos)
   - "key_points": Lista de puntos clave (mínimo 5)
   - "concepts": Lista de conceptos importantes con definiciones breves
   - "conclusion": Conclusión en 1-2 oraciones

FORMATO (SOLO JSON):
{{
    "title": "Título",
    "summary": "Resumen...",
    "key_points": ["Punto 1", "Punto 2"],
    "concepts": [
        {{"term": "Concepto", "definition": "Definición"}}
    ],
    "conclusion": "Conclusión..."
}}

Devuelve SOLO el JSON, sin texto adicional.""",

    "explanation_generation": """Eres un tutor experto paciente y claro.

PREGUNTA:
{question}

CONTEXTO DEL MATERIAL:
{context}

INSTRUCCIONES:
1. Explica la respuesta de manera detallada y comprensible.
2. Usa ejemplos si es posible.
3. Conecta con conceptos del material.

FORMATO (SOLO JSON):
{{
    "explanation": "Explicación detallada...",
    "key_concepts": ["Concepto 1", "Concepto 2"],
    "example": "Ejemplo práctico si aplica"
}}

Devuelve SOLO el JSON, sin texto adicional.""",
}
