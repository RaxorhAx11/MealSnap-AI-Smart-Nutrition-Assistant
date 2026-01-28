import easyocr
from typing import List, Optional
import os

# Fix for Pillow 10+ compatibility with EasyOCR
# ANTIALIAS was removed in Pillow 10.0.0, but EasyOCR still uses it
try:
    from PIL import Image
    # Add ANTIALIAS back if it doesn't exist (for Pillow 10+)
    if not hasattr(Image, 'ANTIALIAS'):
        Image.ANTIALIAS = Image.LANCZOS
except ImportError:
    pass


class OCRReader:
    """
    OCR reader using EasyOCR for text extraction from images.
    Modular and reusable class for OCR operations.
    """
    
    def __init__(self, languages: List[str] = ['en'], gpu: bool = False):
        """
        Initialize EasyOCR reader.
        
        Args:
            languages: List of language codes to support (default: ['en'] for English)
            gpu: Whether to use GPU acceleration (default: False for CPU)
        
        Note: First initialization may download language models, which takes time.
        """
        self.reader = easyocr.Reader(languages, gpu=gpu)
    
    def extract_text(self, image_path: str) -> List[str]:
        """
        Extract text from a processed image.
        
        Args:
            image_path: Path to the processed image file
        
        Returns:
            List of detected text lines (strings)
        
        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If image cannot be read or processed
        """
        # Validate image file exists
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        try:
            # Read text from image using EasyOCR
            # readtext() returns a list of tuples: (bbox, text, confidence)
            # We only need the text part (index 1)
            results = self.reader.readtext(image_path)
            
            # Extract text lines from results
            # Filter out low-confidence detections (confidence < 0.5)
            text_lines = []
            for (bbox, text, confidence) in results:
                if confidence > 0.5:  # Filter low-confidence detections
                    text_lines.append(text.strip())
            
            return text_lines
        
        except Exception as e:
            raise ValueError(f"Error processing image with OCR: {str(e)}")
    
    def extract_text_with_confidence(self, image_path: str) -> List[dict]:
        """
        Extract text with confidence scores from a processed image.
        
        Args:
            image_path: Path to the processed image file
        
        Returns:
            List of dictionaries containing 'text' and 'confidence' for each detected line
        """
        # Validate image file exists
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        try:
            # Read text from image
            results = self.reader.readtext(image_path)
            
            # Extract text lines with confidence scores
            text_data = []
            for (bbox, text, confidence) in results:
                if confidence > 0.5:  # Filter low-confidence detections
                    text_data.append({
                        'text': text.strip(),
                        'confidence': round(confidence, 3)  # Round to 3 decimal places
                    })
            
            return text_data
        
        except Exception as e:
            raise ValueError(f"Error processing image with OCR: {str(e)}")


def extract_text_from_image(image_path: str, languages: List[str] = ['en']) -> List[str]:
    """
    Convenience function for quick text extraction.
    Creates a new OCR reader instance and extracts text.
    
    For better performance with multiple images, use OCRReader class instead.
    
    Args:
        image_path: Path to the processed image file
        languages: List of language codes (default: ['en'] for English)
    
    Returns:
        List of detected text lines (strings)
    """
    ocr_reader = OCRReader(languages=languages)
    return ocr_reader.extract_text(image_path)
