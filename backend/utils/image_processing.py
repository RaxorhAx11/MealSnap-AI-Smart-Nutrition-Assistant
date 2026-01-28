import cv2
import os
from pathlib import Path


def preprocess_receipt_image(image_path: str, output_dir: str = "processed") -> str:
    """
    Preprocess receipt image for better OCR results.
    
    Steps:
    1. Convert to grayscale - reduces color channels, simplifies processing
    2. Apply noise removal - removes unwanted artifacts and noise
    3. Apply thresholding - converts to binary (black/white) for better text recognition
    
    Args:
        image_path: Path to the input image file
        output_dir: Directory to save processed image (default: "processed")
    
    Returns:
        Path to the saved processed image
    
    Raises:
        FileNotFoundError: If input image doesn't exist
        ValueError: If image cannot be read
    """
    # Check if input image exists
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")
    
    # Create output directory (and parents) if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Read the image from the file path
    # cv2.imread() returns a numpy array representing the image
    image = cv2.imread(image_path)
    
    # Check if image was loaded successfully
    if image is None:
        raise ValueError(f"Could not read image from: {image_path}")
    
    # Step 1: Convert to grayscale
    # Grayscale conversion reduces the image from 3 color channels (BGR) to 1 channel
    # This simplifies processing and reduces computational load
    # Common method: weighted average of RGB values (0.299*R + 0.587*G + 0.114*B)
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Step 2: Apply noise removal
    # Gaussian blur removes high-frequency noise (small random variations)
    # Kernel size (5,5) determines blur intensity - must be odd numbers
    # sigmaX=0 lets OpenCV calculate optimal sigma based on kernel size
    denoised = cv2.GaussianBlur(grayscale, (5, 5), 0)
    
    # Alternative: Median blur (good for salt-and-pepper noise)
    # denoised = cv2.medianBlur(grayscale, 5)
    
    # Step 3: Apply thresholding
    # Thresholding converts grayscale image to binary (black and white only)
    # ADAPTIVE_THRESH_GAUSSIAN_C: Uses Gaussian-weighted sum of neighborhood values
    # THRESH_BINARY_INV: Inverts the result (white text on black background)
    # 11: Size of pixel neighborhood used to calculate threshold value (must be odd)
    # 2: Constant subtracted from mean (fine-tuning parameter)
    # This adaptive method works better than simple thresholding for varying lighting
    threshold = cv2.adaptiveThreshold(
        denoised,
        255,  # Maximum value assigned to pixels exceeding threshold
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,  # Adaptive method
        cv2.THRESH_BINARY_INV,  # Threshold type (inverted: white text on black)
        11,  # Block size for calculating threshold
        2  # Constant subtracted from mean
    )
    
    # Alternative: Simple thresholding (works well if lighting is consistent)
    # _, threshold = cv2.threshold(denoised, 127, 255, cv2.THRESH_BINARY_INV)
    
    # Generate output filename
    # Get original filename without extension
    original_filename = Path(image_path).stem
    output_path = os.path.join(output_dir, f"{original_filename}_processed.jpg")
    
    # Save the processed image
    # cv2.imwrite() saves the image to the specified path
    cv2.imwrite(output_path, threshold)
    
    return output_path
