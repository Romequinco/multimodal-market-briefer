"""Visión local con Qwen2.5-VL-3B-Instruct (Hugging Face ``transformers``).

Carril A. Implementa ``VisionProvider.describe``. Inspirado en el **notebook 3 de clase
(VQA con Qwen)**: misma receta de ``AutoProcessor`` + ``Qwen2_5_VLForConditionalGeneration``
+ ``qwen_vl_utils.process_vision_info``. Requiere ``requirements-local.txt`` y, en la práctica,
GPU (en CPU es muy lento). Modelo: ``BRIEFER_QWEN_VL_MODEL``. Coste por llamada: 0 €.
"""

from __future__ import annotations

from briefer.config import Settings
from briefer.providers.base import VisionProvider


class QwenVLLocal(VisionProvider):
    """VLM local; el modelo se carga una vez (perezoso) y se reutiliza."""

    provider_name = "qwen_local"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.model = settings.briefer_qwen_vl_model
        self._model = None
        self._processor = None

    def _load(self) -> None:
        """Carga modelo y procesador en el dispositivo configurado."""
        # TODO:
        # - import torch; from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        # - device: settings.briefer_local_device ("auto" -> cuda si torch.cuda.is_available()).
        # - Qwen2_5_VLForConditionalGeneration.from_pretrained(self.model, torch_dtype="auto",
        #   device_map="auto"); AutoProcessor.from_pretrained(self.model).
        # - Si no hay GPU, avisar en log del tiempo esperado (decenas de segundos por imagen).
        raise NotImplementedError("QwenVLLocal._load: pendiente (carril A, opcional)")

    def describe(self, image: bytes, prompt: str) -> str:
        """Pregunta visual sobre la imagen (VQA) como en el notebook 3."""
        # TODO:
        # 1. self._load() si hace falta; abrir la imagen con PIL.Image.open(io.BytesIO(image)).
        # 2. messages = [{"role": "user", "content": [{"type": "image", "image": pil},
        #    {"type": "text", "text": prompt}]}].
        # 3. text = processor.apply_chat_template(messages, tokenize=False,
        #    add_generation_prompt=True); image_inputs, video_inputs = process_vision_info(messages).
        # 4. inputs = processor(text=[text], images=image_inputs, return_tensors="pt").to(device);
        #    generate(max_new_tokens=512); recortar los tokens de entrada y batch_decode.
        # Casos borde: imágenes enormes -> limitar max_pixels en el processor; OOM en GPU.
        raise NotImplementedError("QwenVLLocal.describe: pendiente (carril A, opcional)")
