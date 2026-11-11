import json
import os
import time
import requests
from app.core.config import settings
from app.modules.ai.services.split_text import split_text

class ExamGeneratorService:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate_exam_from_text(self, text: str):
        prompt = f"""
        Eres un generador experto de exámenes académicos.

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
           - Genera entre las preguntas que consideres necesarias para una buena evaluación del texto no menor a 6 preguntas.
           - Mezcla tipos:
             - Opción múltiple (4 opciones)
             - Verdadero/Falso (solo cuando tenga sentido)
           - Evita preguntas obvias o triviales.
           - Asegúrate de que evalúen comprensión real.

        4. RESPUESTAS:
           - Distribuye correctamente las respuestas (no todas en la misma posición).
           - Evita patrones repetitivos.
           - Las opciones incorrectas deben ser plausibles.

        5. FORMATO (OBLIGATORIO):
        Devuelve SOLO JSON válido, sin texto adicional.

        Estructura EXACTA:
        {{
            "title": "Título del examen basado en el tema principal",
            "questions": [
                {{
                    "question": "Pregunta clara",
                    "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
                    "correct_answer": "Texto EXACTO de la respuesta correcta"
                }}
            ]
        }}

        RESTRICCIONES:
        - NO agregues explicaciones
        - NO agregues texto fuera del JSON
        - NO uses comillas inválidas
        - NO dejes campos vacíos
        """

        response = requests.post(
            self.api_url,
            headers=self.headers,
            json={
                "model": "deepseek/deepseek-v4-flash:free",
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            },
            timeout=30
        )

        data = response.json()

        if "error" in data:
            raise Exception(f"OpenRouter error: {data['error']}")

        try:
            content = data["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            json_text = content[start:end]
            return json.loads(json_text)
        except Exception as e:
            raise Exception(f"Error parseando JSON: {str(e)}")

    def generate_exam_from_chunks(self, full_text: str):
        chunks = split_text(full_text, chunk_size=3000)
        all_questions = []
        title = "Examen generado automáticamente"

        for i, chunk in enumerate(chunks):
            try:
                result = self.generate_exam_from_text(chunk)
                if i == 0 and "title" in result:
                    title = result["title"]
                if "questions" in result:
                    all_questions.extend(result["questions"])
                time.sleep(3)
            except Exception as e:
                print(f"Error en chunk {i}: {e}")
                continue

        return {
            "title": title,
            "questions": all_questions
        }