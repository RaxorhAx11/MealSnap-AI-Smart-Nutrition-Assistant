import easyocr
from typing import List
import os


try:
    from PIL import Image

    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.LANCZOS

except ImportError:
    pass


class OCRReader:
    """
    OCR reader using EasyOCR for text extraction from images.
    EasyOCR models are loaded only when first used.
    """

    def __init__(self, languages: List[str] = ["en"], gpu: bool = False):
        self.languages = languages
        self.gpu = gpu
        self.reader = None

    def _get_reader(self):
        """
        Lazy-load EasyOCR reader.
        Models are downloaded only on first OCR request.
        """
        if self.reader is None:
            self.reader = easyocr.Reader(
                self.languages,
                gpu=self.gpu
            )

        return self.reader

    def extract_text(self, image_path: str) -> List[str]:
        """
        Extract text from a processed image.
        """

        if not os.path.exists(image_path):
            raise FileNotFoundError(
                f"Image file not found: {image_path}"
            )

        try:
            reader = self._get_reader()

            results = reader.readtext(image_path)

            text_lines = []

            for (bbox, text, confidence) in results:
                if confidence > 0.5:
                    text_lines.append(text.strip())

            return text_lines

        except Exception as e:
            raise ValueError(
                f"Error processing image with OCR: {str(e)}"
            )

    def extract_text_with_confidence(self, image_path: str) -> List[dict]:
        """
        Extract text with confidence scores.
        """

        if not os.path.exists(image_path):
            raise FileNotFoundError(
                f"Image file not found: {image_path}"
            )

        try:
            reader = self._get_reader()

            results = reader.readtext(image_path)

            text_data = []

            for (bbox, text, confidence) in results:
                if confidence > 0.5:
                    text_data.append({
                        "text": text.strip(),
                        "confidence": round(confidence, 3)
                    })

            return text_data

        except Exception as e:
            raise ValueError(
                f"Error processing image with OCR: {str(e)}"
            )


def extract_text_from_image(
    image_path: str,
    languages: List[str] = ["en"]
) -> List[str]:
    """
    Convenience function for one-off OCR extraction.
    """

    ocr_reader = OCRReader(
        languages=languages
    )

    return ocr_reader.extract_text(
        image_path
    )
