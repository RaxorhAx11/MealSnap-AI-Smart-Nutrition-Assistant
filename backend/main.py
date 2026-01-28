from fastapi import APIRouter, FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
import uvicorn
import os
import re
import json
import jwt
from pathlib import Path
from datetime import datetime, timezone
from datetime import date as date_type, timedelta
from utils.image_processing import preprocess_receipt_image
from db.database import init_db
from db.database import get_db
from db.models import NutritionSummaryEntry, User, WeightEntry, ConfirmedItemEntry, MealPlanEntry
from deps import CurrentUser, get_current_user
from utils import (
    normalize_food_name,
    match_food_name,
    get_food_nutrition,
    convert_to_grams,
    calculate_food_nutrition,
    calculate_nutrition_from_quantity_string,
    hash_password,
    verify_password,
)
from meal_plan.rules import categorize_food_items
from meal_plan.planner import generate_weekly_meal_plan, generate_daily_meal_plan
from ocr import OCRReader
from sqlalchemy import or_, select, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

# Initialize FastAPI app
app = FastAPI(
    title="Receipt OCR API",
    description="API for receipt OCR processing",
    version="1.0.0"
)


@app.on_event("startup")
def _startup() -> None:
    # Create SQLite tables if they don't exist yet.
    init_db()

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Initialize OCR reader (shared instance for efficiency)
# First initialization may take time to download models
ocr_reader = OCRReader(languages=['en'], gpu=False)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Auth routes
# -----------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["auth"])

# JWT config: HS256, 30min expiry. Set JWT_SECRET_KEY in production.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 30


def _create_access_token(user_id: int) -> str:
    """Build JWT access token with sub=user_id, 30min expiry."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "iat": now, "exp": exp}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


class SignupRequest(BaseModel):
    """Request body for /auth/signup."""
    username: str = Field(..., min_length=1, max_length=64, description="Unique username")
    email: EmailStr = Field(..., description="Unique email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")


class SignupResponse(BaseModel):
    """Success response for /auth/signup. No token returned yet."""
    message: str


class LoginRequest(BaseModel):
    """Request body for /auth/login. Use username or email."""
    username_or_email: str = Field(..., min_length=1, description="Username or email")
    password: str = Field(..., min_length=1, description="Password")


class UserInfo(BaseModel):
    """Basic user info returned on login."""
    id: int
    username: str
    email: str


class LoginResponse(BaseModel):
    """Success response for /auth/login: JWT and user info."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds")
    user: UserInfo


@auth_router.post("/signup", response_model=SignupResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    """
    Create a new user account. Passwords are hashed before storage.
    Returns a success message; no token is issued yet.
    """
    try:
        existing_by_username = db.scalar(select(User).where(User.username == payload.username.strip()))
        existing_by_email = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
        if existing_by_username:
            raise HTTPException(status_code=409, detail="Username already taken.")
        if existing_by_email:
            raise HTTPException(status_code=409, detail="Email already registered.")

        hashed = hash_password(payload.password)
        user = User(
            username=payload.username.strip(),
            email=payload.email.strip().lower(),
            hashed_password=hashed,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return SignupResponse(message="Account created successfully.")
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already registered.")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during signup: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error during signup: {str(e)}")


@auth_router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with username or email and password. Returns JWT access token
    and basic user info. Token expires in 30 minutes (HS256).
    """
    try:
        raw = payload.username_or_email.strip()
        lookup = raw.lower() if "@" in raw else raw
        user = db.scalar(
            select(User).where(
                or_(User.username.ilike(lookup), User.email.ilike(lookup))
            )
        )
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username/email or password.")
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid username/email or password.")

        token = _create_access_token(user.id)
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=60 * JWT_EXPIRE_MINUTES,
            user=UserInfo(id=user.id, username=user.username, email=user.email),
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error during login: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error during login: {str(e)}")


@auth_router.get("/me", response_model=UserInfo)
def auth_me(current_user: CurrentUser):
    """
    Return the current logged-in user. Requires valid JWT in Authorization header.
    Example use of the get_current_user dependency.
    """
    return UserInfo(id=current_user.id, username=current_user.username, email=current_user.email)


app.include_router(auth_router)


@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify API is running
    """
    return {"status": "healthy", "message": "API is running"}


@app.get("/")
async def root():
    """
    Root endpoint
    """
    return {"message": "Receipt OCR API"}


def filter_prices_and_numbers(text_lines: list) -> list:
    """
    Filter out lines containing prices, totals, and numbers.
    
    Args:
        text_lines: List of text strings from OCR
    
    Returns:
        Filtered list without price/number lines
    """
    filtered_lines = []
    
    # Patterns to identify price/number lines
    currency_symbols = r'[\$€£¥₹]'
    decimal_pattern = r'\d+\.\d{2}'  # Matches prices like 10.50, 5.99
    price_keywords = r'(total|subtotal|tax|discount|amount|price|cost|sum)'
    mostly_numbers = r'^\d+[\s\d\.]*$'  # Lines that are mostly numbers
    
    for line in text_lines:
        # Skip empty lines
        if not line.strip():
            continue
        
        # Skip lines with currency symbols
        if re.search(currency_symbols, line):
            continue
        
        # Skip lines with decimal prices (e.g., 10.50, 5.99)
        if re.search(decimal_pattern, line):
            continue
        
        # Skip lines that are mostly numbers
        if re.match(mostly_numbers, line.strip()):
            continue
        
        # Skip lines with price keywords followed by numbers (case-insensitive)
        if re.search(price_keywords, line, re.IGNORECASE) and re.search(r'\d', line):
            continue
        
        # Keep the line if it passed all filters
        filtered_lines.append(line)
    
    return filtered_lines


@app.post("/upload-receipt")
async def upload_receipt(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """
    Upload receipt image, preprocess it, run OCR, and return extracted text.
    Filters out prices, totals, and numbers.

    User-based data isolation: receipts are stored under uploads/{user_id}/ and
    processed/{user_id}/. Files are never shared between users.
    """
    try:
        # Get file extension
        file_extension = Path(file.filename).suffix.lower()

        # Validate file type
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        # User-specific directories: receipts isolated per user, never shared.
        user_upload_dir = UPLOAD_DIR / str(current_user.id)
        user_processed_dir = Path("processed") / str(current_user.id)
        user_upload_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"receipt_{timestamp}{file_extension}"
        file_path = user_upload_dir / safe_filename

        # Step 1: Save uploaded file
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Step 2: Preprocess the image (output under processed/{user_id}/)
        processed_path = preprocess_receipt_image(str(file_path), output_dir=str(user_processed_dir))
        
        # Step 3: Run OCR on processed image
        ocr_text_lines = ocr_reader.extract_text(processed_path)
        
        # Step 4: Filter out prices, totals, and numbers
        filtered_text = filter_prices_and_numbers(ocr_text_lines)
        
        return {
            "success": True,
            "message": "Receipt processed successfully",
            "filename": safe_filename,
            "original_file_path": str(file_path),
            "processed_file_path": processed_path,
            "raw_ocr_text": filtered_text,
            "text_line_count": len(filtered_text)
        }
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"File error: {str(e)}"
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Processing error: {str(e)}"
        )
    
    except Exception as e:
        # Handle any other errors
        raise HTTPException(
            status_code=500,
            detail=f"Error processing receipt: {str(e)}"
        )


# Pydantic models for nutrition analysis
class FoodItem(BaseModel):
    """Model for a single food item from the receipt"""
    name: str = Field(..., description="Food item name")
    quantity: float = Field(..., description="Quantity value")
    unit: str = Field(..., description="Unit (g, kg, L, ml, pc, etc.)")


class NutritionAnalysisRequest(BaseModel):
    """Request model for nutrition analysis"""
    items: List[FoodItem] = Field(..., description="List of confirmed food items")


class ItemNutrition(BaseModel):
    """Nutrition information for a single item"""
    original_name: str
    matched_name: Optional[str] = None
    quantity_grams: Optional[float] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    matched: bool = False
    error: Optional[str] = None


class NutritionSummary(BaseModel):
    """Total nutrition summary"""
    total_calories: float = 0.0
    total_protein: float = 0.0
    total_carbs: float = 0.0
    total_fats: float = 0.0
    total_items: int = 0
    matched_items: int = 0
    unmatched_items: int = 0
    # List of unknown items (items not found in database)
    unknown_items: List[str] = []
    # Simple, non-medical intake labels (see evaluate_macro_status)
    protein_status: str = "unknown"
    carb_status: str = "unknown"
    fat_status: str = "unknown"
    # List of identified nutrition gaps (see identify_nutrition_gaps)
    nutrition_gaps: List[str] = []
    # Food purchase suggestions based on gaps (see suggest_foods_for_gaps)
    suggested_foods: List[str] = []


class NutritionAnalysisResponse(BaseModel):
    """Response model for nutrition analysis"""
    success: bool
    items: List[ItemNutrition]
    summary: NutritionSummary
    message: Optional[str] = None


def evaluate_macro_status(
    total_protein: float, total_carbs: float, total_fats: float
) -> Dict[str, str]:
    """
    Classify macro intake using very simple reference points.

    These reference values are intentionally basic and non-medical, meant only
    for quick guidance based on common daily targets for adults eating roughly
    2,000 kcal/day:
      - Protein: low < 50g, adequate ≥ 50g  (≈0.8 g/kg for a 62 kg adult)
      - Carbohydrates: low < 130g, adequate 130–300g, high > 300g
          (130g aligns with the brain's minimum glucose needs; 300g approximates
           ~60% of a 2,000 kcal diet)
      - Fats: low < 44g, adequate ≥ 44g
          (~20% of 2,000 kcal; keeps well below common 20–35% ranges)

    Returns simple labels so the UI can show "low/adequate/high" without
    implying medical advice.
    """
    protein_status = "adequate" if total_protein >= 50 else "low"

    if total_carbs > 300:
        carb_status = "high"
    elif total_carbs >= 130:
        carb_status = "adequate"
    else:
        carb_status = "low"

    fat_status = "adequate" if total_fats >= 44 else "low"

    return {
        "protein_status": protein_status,
        "carb_status": carb_status,
        "fat_status": fat_status,
    }


def identify_nutrition_gaps(
    total_calories: float,
    total_protein: float,
    total_carbs: float,
    total_fats: float,
) -> Dict[str, Any]:
    """
    Identify nutrition gaps and imbalances from total intake.
    
    This function uses simple rule-based logic to detect:
    - Low macronutrients (protein, carbs, fats)
    - High carbohydrate intake
    - Very low calorie intake (potential under-eating)
    - Imbalanced ratios
    - Low fiber (inferred from low carbs and low calories)
    
    Returns a dictionary with:
    - gaps: List of gap messages (e.g., ["low protein", "low carbohydrates"])
    - nutrient_details: Dictionary identifying which specific nutrients are low
    
    These are simple recommendations, not medical advice.
    
    Args:
        total_calories: Total daily calories
        total_protein: Total protein in grams
        total_carbs: Total carbohydrates in grams
        total_fats: Total fats in grams
    
    Returns:
        Dictionary with 'gaps' (list of strings) and 'nutrient_details' (dict)
    """
    gaps = []
    nutrient_details = {
        "low_protein": False,
        "low_fiber": False,
        "low_healthy_carbs": False,
        "low_fats": False,
    }
    
    # Evaluate macro status using the same thresholds
    macro_status = evaluate_macro_status(total_protein, total_carbs, total_fats)
    
    # Check for low protein
    if macro_status["protein_status"] == "low":
        gaps.append("low protein")
        nutrient_details["low_protein"] = True
    
    # Check for low carbohydrates (indicates low healthy/complex carbs)
    if macro_status["carb_status"] == "low":
        gaps.append("low carbohydrates")
        nutrient_details["low_healthy_carbs"] = True
    
    # Check for high carbohydrates
    if macro_status["carb_status"] == "high":
        gaps.append("high carbohydrates")
    
    # Check for low fats
    if macro_status["fat_status"] == "low":
        gaps.append("low fats")
        nutrient_details["low_fats"] = True
    
    # Check for very low calorie intake (below 1200 kcal/day is generally too low)
    # This is a simple heuristic, not medical advice
    if total_calories < 1200:
        gaps.append("very low calories")
    
    # Check for imbalanced macronutrient distribution
    # If protein is very low relative to carbs (protein < 10% of carbs), flag imbalance
    if total_carbs > 0 and total_protein > 0:
        protein_to_carb_ratio = total_protein / total_carbs
        if protein_to_carb_ratio < 0.1:  # Less than 10% protein relative to carbs
            gaps.append("imbalanced macros (low protein relative to carbs)")
    
    # Note: "low vegetables/fiber" is detected when carbs are low AND calories are low
    # This is a simplified heuristic: if carbs are low AND calories are low,
    # it might indicate lack of vegetables/fiber sources
    if macro_status["carb_status"] == "low" and total_calories < 1500:
        gaps.append("low vegetables/fiber")
        nutrient_details["low_fiber"] = True
    
    return {
        "gaps": gaps,
        "nutrient_details": nutrient_details,
    }


def suggest_foods_for_gaps(
    nutrition_gaps: List[str], 
    nutrient_details: Dict[str, bool]
) -> List[Dict[str, str]]:
    """
    Map nutrition gaps to food purchase suggestions with explanations.
    
    This function provides basic recommendations for addressing identified nutrition
    gaps. Each suggestion includes:
    - food_name: The recommended food item
    - reason: Why it is suggested (based on the gap)
    - nutrition_benefit: Which nutrients it improves
    
    Suggestions are general and not medical advice.
    
    Args:
        nutrition_gaps: List of gap strings (e.g., ["low protein", "low carbohydrates"])
        nutrient_details: Dictionary identifying which specific nutrients are low
    
    Returns:
        List of dictionaries, each containing food_name, reason, and nutrition_benefit
    """
    # Mapping from gaps to food suggestions with explanations
    # Each entry maps a gap to a list of (food_name, reason, nutrition_benefit) tuples
    gap_to_foods = {
        "low protein": [
            ("Eggs", "Current intake is low in protein", "Provides high-quality protein and essential amino acids"),
            ("Lentils", "Protein intake is below recommended levels", "Rich in plant-based protein and fiber"),
            ("Paneer", "Low protein detected in your diet", "Excellent source of complete protein and calcium"),
            ("Chicken", "Protein intake needs improvement", "High-quality lean protein for muscle health"),
            ("Tofu", "Low protein intake identified", "Plant-based protein with all essential amino acids"),
        ],
        "low carbohydrates": [
            ("Brown Rice", "Current intake is low in complex carbohydrates", "Provides complex carbs and dietary fiber"),
            ("Whole Wheat Bread", "Low intake of healthy carbohydrates", "Improves fiber and sustained energy"),
            ("Oats", "Fiber intake is low", "Improves fiber and helps maintain energy levels"),
            ("Quinoa", "Low complex carbohydrate intake", "Provides complete protein and complex carbs"),
            ("Sweet Potato", "Current intake is low in complex carbohydrates", "Rich in complex carbs and vitamins"),
        ],
        "high carbohydrates": [
            ("Protein-rich foods", "Carbohydrate intake is high relative to protein", "Helps balance macros and provides satiety"),
            ("Vegetables", "High carb intake detected", "Adds fiber and nutrients without excess carbs"),
            ("Nuts", "Carbohydrate balance needs adjustment", "Provides healthy fats and protein"),
        ],
        "low fats": [
            ("Nuts", "Fat intake is below recommended levels", "Provides healthy fats and essential fatty acids"),
            ("Seeds", "Low fat intake detected", "Rich in omega-3 and healthy fats"),
            ("Olive Oil", "Current fat intake is low", "Source of monounsaturated fats and antioxidants"),
            ("Avocado", "Fat intake needs improvement", "Provides healthy monounsaturated fats and fiber"),
            ("Almonds", "Low fat intake identified", "Excellent source of healthy fats and protein"),
        ],
        "very low calories": [
            ("Nutrient-dense foods", "Calorie intake is very low", "Helps meet daily energy needs with essential nutrients"),
            ("Whole Grains", "Calorie intake needs to increase", "Provides sustained energy and essential nutrients"),
            ("Lean Protein", "Very low calorie intake detected", "Supports energy and muscle health"),
            ("Vegetables", "Calorie intake is below healthy levels", "Adds nutrients and fiber with moderate calories"),
        ],
        "imbalanced macros (low protein relative to carbs)": [
            ("Eggs", "Protein intake is low relative to carbohydrates", "Increases protein to balance your macros"),
            ("Lentils", "Macronutrient balance needs improvement", "Adds protein and fiber to balance carbs"),
            ("Paneer", "Low protein relative to carbs detected", "Provides complete protein to balance your diet"),
            ("Chicken", "Macro balance needs adjustment", "High-quality protein to balance carbohydrate intake"),
            ("Fish", "Protein intake is low compared to carbs", "Lean protein source to improve macro balance"),
        ],
        "low vegetables/fiber": [
            ("Spinach", "Fiber intake is low", "High in fiber, vitamins, and minerals"),
            ("Broccoli", "Low vegetable and fiber intake", "Rich in fiber, vitamin C, and antioxidants"),
            ("Carrots", "Fiber intake needs improvement", "Provides fiber and beta-carotene"),
            ("Bell Peppers", "Low vegetable intake detected", "High in fiber, vitamin C, and antioxidants"),
            ("Cabbage", "Fiber and vegetable intake is low", "Excellent source of fiber and vitamin K"),
        ],
    }
    
    # Collect all suggested foods from matching gaps
    # Logic: For each identified gap, look up corresponding food suggestions
    # Each food suggestion includes: food name, reason (why suggested), and nutrition benefit
    suggested_foods = []
    seen_foods = set()  # Track by food name (case-insensitive) to avoid duplicates
    
    # Iterate through all identified nutrition gaps
    for gap in nutrition_gaps:
        if gap in gap_to_foods:
            # For each gap, get all associated food suggestions
            for food_name, reason, nutrition_benefit in gap_to_foods[gap]:
                # Use lowercase for deduplication to avoid suggesting the same food twice
                food_key = food_name.lower()
                if food_key not in seen_foods:
                    # Add structured suggestion with all three fields: food, reason, nutrition_benefit
                    suggested_foods.append({
                        "food": food_name,
                        "reason": reason,
                        "nutrition_benefit": nutrition_benefit,
                    })
                    seen_foods.add(food_key)
    
    # If we have fewer than 3 suggestions, add some general healthy options
    if len(suggested_foods) < 3:
        general_suggestions = [
            ("Vegetables", "To improve overall nutrition balance", "Provides essential vitamins, minerals, and fiber"),
            ("Fruits", "For a balanced diet", "Rich in vitamins, antioxidants, and natural fiber"),
            ("Whole Grains", "To support daily energy needs", "Provides complex carbs, fiber, and B vitamins"),
            ("Lean Protein", "For balanced nutrition", "Supports muscle health and provides essential amino acids"),
        ]
        for food_name, reason, nutrition_benefit in general_suggestions:
            food_key = food_name.lower()
            if food_key not in seen_foods and len(suggested_foods) < 5:
                suggested_foods.append({
                    "food": food_name,
                    "reason": reason,
                    "nutrition_benefit": nutrition_benefit,
                })
                seen_foods.add(food_key)
    
    # Limit to 5 suggestions max
    return suggested_foods[:5]


class MealPlanItem(BaseModel):
    """
    Simple input model for meal planning.

    This assumes the user has already confirmed the items they want to plan
    meals around. We mainly use the name here; detailed nutrition is handled
    elsewhere if needed.
    """
    name: str = Field(..., description="Confirmed food item name")


class MealPlanRequest(BaseModel):
    """
    Request body for /generate-meal-plan.
    
    NOTE: Items are now optional. If not provided, the endpoint will automatically
    fetch the latest confirmed items from the database (from today's date).
    
    Example (optional - items will be auto-fetched if not provided):
    {
      "items": [
        {"name": "oats"},
        {"name": "chicken biryani"},
        {"name": "mixed salad"}
      ]
    }
    """
    items: Optional[List[MealPlanItem]] = Field(
        default=None, description="Optional list of confirmed food items. If not provided, latest confirmed items from database will be used."
    )


class MealPlanResponse(BaseModel):
    """
    Response model for a weekly meal plan.

    The underlying planner returns a simple dict with:
    - days: list of 7 entries (one per day)
    - notes: explanation of the rules and calorie estimation
    """
    success: bool
    plan: Dict[str, Any]
    message: Optional[str] = None


@app.post("/analyze-nutrition", response_model=NutritionAnalysisResponse)
async def analyze_nutrition(
    request: NutritionAnalysisRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Analyze nutrition for a list of confirmed food items.
    
    This endpoint:
    1. Normalizes food names
    2. Performs fuzzy matching against the nutrition database
    3. Converts units to grams
    4. Calculates nutrition values for each item
    5. Saves the total nutrition summary to the database (for today's date)
    6. Returns per-item and total nutrition summary
    
    Unmatched items are handled gracefully and included in the response
    with matched=False and error message.
    
    Args:
        request: NutritionAnalysisRequest containing list of FoodItem objects
        db: Database session (injected by FastAPI)
    
    Returns:
        NutritionAnalysisResponse with per-item nutrition and total summary
    """
    try:
        items_result = []
        total_calories = 0.0
        total_protein = 0.0
        total_carbs = 0.0
        total_fats = 0.0
        matched_count = 0
        unmatched_count = 0
        unknown_items = []  # Track items marked as "Unknown"
        
        for item in request.items:
            item_result = ItemNutrition(
                original_name=item.name,
                matched=False
            )
            
            try:
                # Step 1: Normalize the food name
                normalized_name = normalize_food_name(item.name)
                
                if not normalized_name:
                    # Mark as unknown if normalization fails
                    item_result.matched = False
                    item_result.matched_name = "Unknown"
                    item_result.error = f"Could not normalize food name '{item.name}'"
                    unknown_items.append(item.name)  # Track unknown item
                    items_result.append(item_result)
                    unmatched_count += 1
                    continue
                
                # Step 2: Perform fuzzy matching
                match_result = match_food_name(normalized_name, similarity_threshold=80.0)
                
                if not match_result:
                    # Mark as unknown instead of failing
                    item_result.matched = False
                    item_result.matched_name = "Unknown"
                    item_result.error = f"Food item '{item.name}' not found in database"
                    unknown_items.append(item.name)  # Track unknown item
                    items_result.append(item_result)
                    unmatched_count += 1
                    continue  # Skip nutrition calculation for unknown items
                
                # Extract canonical name from match result (tuple: canonical_name, confidence, is_alias)
                matched_name, match_confidence, matched_via_alias = match_result
                
                # Step 3: Convert quantity and unit to grams
                # Construct quantity string (e.g., "500g", "1.5kg", "12 pcs")
                # Add space for piece units to match parser expectations
                if item.unit.lower() in ['pc', 'pcs', 'piece', 'pieces']:
                    quantity_str = f"{item.quantity} {item.unit}"
                else:
                    quantity_str = f"{item.quantity}{item.unit}"
                
                # Convert to grams (for piece conversion, use normalized matched name)
                quantity_grams = convert_to_grams(quantity_str, food_name=matched_name)
                
                if quantity_grams is None:
                    # Mark as unknown if quantity conversion fails
                    item_result.matched = False
                    item_result.matched_name = "Unknown"
                    item_result.error = f"Could not convert quantity '{quantity_str}' to grams for '{item.name}'"
                    unknown_items.append(item.name)  # Track unknown item
                    items_result.append(item_result)
                    unmatched_count += 1
                    continue
                
                # Step 4: Get nutrition data and calculate values
                nutrition_data = get_food_nutrition(item.name, similarity_threshold=80.0)
                
                if not nutrition_data:
                    # Mark as unknown if nutrition data not found
                    item_result.matched = False
                    item_result.matched_name = "Unknown"
                    item_result.error = f"Nutrition data not found for matched item '{matched_name}'"
                    unknown_items.append(item.name)  # Track unknown item
                    items_result.append(item_result)
                    unmatched_count += 1
                    continue
                
                # Step 5: Calculate nutrition values
                calculated_nutrition = calculate_food_nutrition(
                    food_name=item.name,
                    quantity_grams=quantity_grams,
                    similarity_threshold=80.0,
                    round_decimals=1
                )
                
                if not calculated_nutrition:
                    # Mark as unknown if calculation fails
                    item_result.matched = False
                    item_result.matched_name = "Unknown"
                    item_result.error = f"Failed to calculate nutrition values for '{item.name}'"
                    unknown_items.append(item.name)  # Track unknown item
                    items_result.append(item_result)
                    unmatched_count += 1
                    continue
                
                # Step 6: Populate result
                item_result.matched = True
                item_result.matched_name = calculated_nutrition['food_name']
                item_result.quantity_grams = calculated_nutrition['quantity_grams']
                item_result.calories = calculated_nutrition['calories']
                item_result.protein = calculated_nutrition['protein']
                item_result.carbs = calculated_nutrition['carbs']
                item_result.fats = calculated_nutrition['fats']
                
                # Add to totals
                total_calories += calculated_nutrition['calories']
                total_protein += calculated_nutrition['protein']
                total_carbs += calculated_nutrition['carbs']
                total_fats += calculated_nutrition['fats']
                matched_count += 1
                
            except Exception as e:
                # Handle any unexpected errors gracefully - mark as unknown
                item_result.matched = False
                item_result.matched_name = "Unknown"
                item_result.error = f"Processing error for '{item.name}': {str(e)}"
                unknown_items.append(item.name)  # Track unknown item
                unmatched_count += 1
            
            items_result.append(item_result)
        
        # Create summary
        macro_status = evaluate_macro_status(
            total_protein=total_protein,
            total_carbs=total_carbs,
            total_fats=total_fats,
        )
        
        # Identify nutrition gaps (returns dict with 'gaps' and 'nutrient_details')
        gaps_result = identify_nutrition_gaps(
            total_calories=total_calories,
            total_protein=total_protein,
            total_carbs=total_carbs,
            total_fats=total_fats,
        )
        gaps = gaps_result["gaps"]
        nutrient_details = gaps_result["nutrient_details"]
        
        # Generate food purchase suggestions based on gaps
        # For backward compatibility with NutritionSummary, extract just food names
        suggested_foods_structured = suggest_foods_for_gaps(gaps, nutrient_details)
        suggested_foods = [item["food"] for item in suggested_foods_structured]

        summary = NutritionSummary(
            total_calories=round(total_calories, 1),
            total_protein=round(total_protein, 1),
            total_carbs=round(total_carbs, 1),
            total_fats=round(total_fats, 1),
            total_items=len(request.items),
            matched_items=matched_count,
            unmatched_items=unmatched_count,
            unknown_items=unknown_items,  # Include list of unknown items
            protein_status=macro_status["protein_status"],
            carb_status=macro_status["carb_status"],
            fat_status=macro_status["fat_status"],
            nutrition_gaps=gaps,
            suggested_foods=suggested_foods,
        )
        
        # Save nutrition summary to database (for today's date).
        # User-based isolation: stored per current_user.id; never shared between users.
        try:
            today = datetime.now().date()
            existing = db.scalar(
                select(NutritionSummaryEntry).where(
                    NutritionSummaryEntry.user_id == current_user.id,
                    NutritionSummaryEntry.date == today,
                )
            )
            
            if existing:
                # Update existing entry for today
                existing.calories = float(summary.total_calories)
                existing.protein = float(summary.total_protein)
                existing.carbs = float(summary.total_carbs)
                existing.fats = float(summary.total_fats)
            else:
                # Create new entry for today
                entry = NutritionSummaryEntry(
                    user_id=current_user.id,
                    date=today,
                    calories=float(summary.total_calories),
                    protein=float(summary.total_protein),
                    carbs=float(summary.total_carbs),
                    fats=float(summary.total_fats),
                )
                db.add(entry)
            
            db.commit()
        except Exception as db_error:
            # Log error but don't fail the request - nutrition analysis succeeded
            # The summary is still returned to the user
            db.rollback()
            print(f"Warning: Failed to save nutrition summary to database: {str(db_error)}")
        
        # Save confirmed items to database (for today's date).
        # User-based isolation: stored per current_user.id; never shared between users.
        try:
            today = datetime.now().date()
            # Delete existing confirmed items for today (replace with new ones)
            db.execute(
                delete(ConfirmedItemEntry).where(
                    ConfirmedItemEntry.user_id == current_user.id,
                    ConfirmedItemEntry.date == today,
                )
            )
            
            # Save all confirmed items from the request
            for item in request.items:
                confirmed_item = ConfirmedItemEntry(
                    user_id=current_user.id,
                    date=today,
                    name=item.name.strip(),
                    quantity=float(item.quantity) if item.quantity else None,
                    unit=item.unit.strip() if item.unit else None
                )
                db.add(confirmed_item)
            
            db.commit()
        except Exception as db_error:
            # Log error but don't fail the request - nutrition analysis succeeded
            db.rollback()
            print(f"Warning: Failed to save confirmed items to database: {str(db_error)}")
        
        # Create response message
        message = None
        if unmatched_count > 0:
            message = f"Successfully analyzed {matched_count} items. {unmatched_count} item(s) could not be matched."
        else:
            message = f"Successfully analyzed all {matched_count} items."
        
        return NutritionAnalysisResponse(
            success=True,
            items=items_result,
            summary=summary,
            message=message
        )
    
    except Exception as e:
        # Handle any unexpected errors at the endpoint level
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing nutrition: {str(e)}"
        )


# -----------------------------
# Tracking + dashboard endpoints
# -----------------------------

class WeightSaveRequest(BaseModel):
    date: date_type
    weight: float = Field(..., gt=0, description="Weight (e.g. kg or lbs)")


class WeightEntryResponse(BaseModel):
    date: date_type
    weight: float


class NutritionSummarySaveRequest(BaseModel):
    date: date_type
    calories: float = Field(0.0, ge=0)
    protein: float = Field(0.0, ge=0)
    carbs: float = Field(0.0, ge=0)
    fats: float = Field(0.0, ge=0)


class NutritionSummaryResponse(BaseModel):
    date: date_type
    calories: float
    protein: float
    carbs: float
    fats: float


class FoodSuggestion(BaseModel):
    """Model for a single food suggestion with explanation"""
    food: str = Field(..., description="Food item name")
    reason: str = Field(..., description="Why this food is suggested")
    nutrition_benefit: str = Field(..., description="Which nutrients this food improves")


class PurchaseSuggestionsResponse(BaseModel):
    """Response model for purchase suggestions based on nutrition gaps"""
    message: str
    suggestions: List[FoodSuggestion]


class DashboardResponse(BaseModel):
    start_date: date_type
    end_date: date_type
    weight_history: List[WeightEntryResponse]
    nutrition_history: List[NutritionSummaryResponse]
    weekly_meal_plan: Optional[Dict[str, Any]] = None  # Saved meal plan from database


@app.post("/weights", response_model=WeightEntryResponse)
def save_weight(
    payload: WeightSaveRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Save (or update) a user's weight for a given date.
    User-based isolation: weight entries are stored and fetched by current_user.id only; never shared between users.
    """
    try:
        existing = db.scalar(
            select(WeightEntry).where(
                WeightEntry.user_id == current_user.id,
                WeightEntry.date == payload.date,
            )
        )
        if existing:
            existing.weight = float(payload.weight)
            db.commit()
            db.refresh(existing)
            return WeightEntryResponse(date=existing.date, weight=existing.weight)

        entry = WeightEntry(
            user_id=current_user.id,
            date=payload.date,
            weight=float(payload.weight),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return WeightEntryResponse(date=entry.date, weight=entry.weight)

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Weight entry for this user and date already exists.",
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error saving weight: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error saving weight: {str(e)}")


@app.get("/weights", response_model=List[WeightEntryResponse])
def get_weight_history(
    current_user: CurrentUser,
    start_date: Optional[date_type] = None,
    end_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    """
    Fetch weight history (optionally filtered by date range).
    User-based isolation: returns only the current user's weight entries; never shared between users.
    """
    try:
        q = select(WeightEntry).where(WeightEntry.user_id == current_user.id)
        if start_date:
            q = q.where(WeightEntry.date >= start_date)
        if end_date:
            q = q.where(WeightEntry.date <= end_date)
        q = q.order_by(WeightEntry.date.desc())

        rows = db.scalars(q).all()
        return [WeightEntryResponse(date=r.date, weight=r.weight) for r in rows]
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching weights: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error fetching weights: {str(e)}")


@app.post("/nutrition-summaries", response_model=NutritionSummaryResponse)
def save_nutrition_summary(
    payload: NutritionSummarySaveRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Save (or update) a daily nutrition summary for a given date.
    User-based isolation: nutrition summaries are stored and fetched by current_user.id only; never shared between users.
    """
    try:
        existing = db.scalar(
            select(NutritionSummaryEntry).where(
                NutritionSummaryEntry.user_id == current_user.id,
                NutritionSummaryEntry.date == payload.date,
            )
        )
        if existing:
            existing.calories = float(payload.calories)
            existing.protein = float(payload.protein)
            existing.carbs = float(payload.carbs)
            existing.fats = float(payload.fats)
            db.commit()
            db.refresh(existing)
            return NutritionSummaryResponse(
                date=existing.date,
                calories=existing.calories,
                protein=existing.protein,
                carbs=existing.carbs,
                fats=existing.fats,
            )

        entry = NutritionSummaryEntry(
            user_id=current_user.id,
            date=payload.date,
            calories=float(payload.calories),
            protein=float(payload.protein),
            carbs=float(payload.carbs),
            fats=float(payload.fats),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return NutritionSummaryResponse(
            date=entry.date,
            calories=entry.calories,
            protein=entry.protein,
            carbs=entry.carbs,
            fats=entry.fats,
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Nutrition summary for this user and date already exists.",
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error saving summary: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error saving summary: {str(e)}")


@app.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    current_user: CurrentUser,
    days: int = 30,
    end_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    """
    Return dashboard data combining weight + nutrition history.
    Defaults to last 30 days ending today (or a provided end_date).
    User-based isolation: all data (weights, nutrition, meal plan) is filtered by current_user.id; never shared between users.
    """
    try:
        if days <= 0 or days > 3650:
            raise HTTPException(status_code=400, detail="days must be between 1 and 3650")

        effective_end = end_date or datetime.now().date()
        start = effective_end - timedelta(days=days - 1)

        # User-scoped: only this user's weight and nutrition history.
        weights = db.scalars(
            select(WeightEntry)
            .where(
                WeightEntry.user_id == current_user.id,
                WeightEntry.date >= start,
                WeightEntry.date <= effective_end,
            )
            .order_by(WeightEntry.date.asc())
        ).all()
        nutrition = db.scalars(
            select(NutritionSummaryEntry)
            .where(
                NutritionSummaryEntry.user_id == current_user.id,
                NutritionSummaryEntry.date >= start,
                NutritionSummaryEntry.date <= effective_end,
            )
            .order_by(NutritionSummaryEntry.date.asc())
        ).all()

        # Fetch the latest saved meal plan (user-scoped: only this user's plan).
        meal_plan_data = None
        try:
            today = datetime.now().date()
            meal_plan_entry = db.scalar(
                select(MealPlanEntry)
                .where(
                    MealPlanEntry.user_id == current_user.id,
                    MealPlanEntry.date == today,
                )
                .order_by(MealPlanEntry.created_at.desc())
            )
            
            if not meal_plan_entry:
                meal_plan_entry = db.scalar(
                    select(MealPlanEntry)
                    .where(MealPlanEntry.user_id == current_user.id)
                    .order_by(MealPlanEntry.date.desc(), MealPlanEntry.created_at.desc())
                    .limit(1)
                )
            
            if meal_plan_entry:
                # Parse the JSON string back to dict
                meal_plan_data = json.loads(meal_plan_entry.plan_data)
        except Exception as e:
            # Log error but don't fail the dashboard request
            print(f"Warning: Failed to load meal plan from database: {str(e)}")

        return DashboardResponse(
            start_date=start,
            end_date=effective_end,
            weight_history=[WeightEntryResponse(date=w.date, weight=w.weight) for w in weights],
            nutrition_history=[
                NutritionSummaryResponse(
                    date=n.date,
                    calories=n.calories,
                    protein=n.protein,
                    carbs=n.carbs,
                    fats=n.fats,
                )
                for n in nutrition
            ],
            weekly_meal_plan=meal_plan_data,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching dashboard: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error fetching dashboard: {str(e)}")


@app.get("/dashboard-nutrition", response_model=NutritionSummaryResponse)
def get_dashboard_nutrition(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Fetch the latest saved nutrition summary from the database.

    User-based isolation: returns only the current user's latest nutrition summary; never shared between users.
    Returns 404 if none exists.
    """
    try:
        latest = db.scalar(
            select(NutritionSummaryEntry)
            .where(NutritionSummaryEntry.user_id == current_user.id)
            .order_by(NutritionSummaryEntry.date.desc())
            .limit(1)
        )
        
        if not latest:
            raise HTTPException(
                status_code=404,
                detail="No nutrition summary found in database. Please analyze nutrition first."
            )
        
        return NutritionSummaryResponse(
            date=latest.date,
            calories=latest.calories,
            protein=latest.protein,
            carbs=latest.carbs,
            fats=latest.fats,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error fetching latest nutrition summary: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error fetching latest nutrition summary: {str(e)}"
        )


@app.get("/next-purchase-suggestions", response_model=PurchaseSuggestionsResponse)
def get_next_purchase_suggestions(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Get food purchase suggestions based on stored nutrition summary.

    User-based isolation: uses only the current user's latest nutrition summary; never shared between users.
    """
    try:
        latest = db.scalar(
            select(NutritionSummaryEntry)
            .where(NutritionSummaryEntry.user_id == current_user.id)
            .order_by(NutritionSummaryEntry.date.desc())
            .limit(1)
        )
        
        if not latest:
            raise HTTPException(
                status_code=404,
                detail="No nutrition summary found in database. Please analyze nutrition first."
            )
        
        # Detect nutrition gaps from stored summary (returns dict with 'gaps' and 'nutrient_details')
        gaps_result = identify_nutrition_gaps(
            total_calories=float(latest.calories),
            total_protein=float(latest.protein),
            total_carbs=float(latest.carbs),
            total_fats=float(latest.fats),
        )
        gaps = gaps_result["gaps"]
        nutrient_details = gaps_result["nutrient_details"]
        
        # Generate food suggestions based on gaps (returns structured list with food, reason, nutrition_benefit)
        suggested_foods = suggest_foods_for_gaps(gaps, nutrient_details)
        
        # Create response message
        if len(suggested_foods) > 0:
            message = "Based on your recent nutrition intake, you may consider adding:"
        else:
            message = "Your nutrition intake looks balanced. No specific recommendations at this time."
            suggested_foods = []  # Return empty list if no gaps found
        
        return PurchaseSuggestionsResponse(
            message=message,
            suggestions=suggested_foods
        )
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error fetching nutrition summary: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error generating purchase suggestions: {str(e)}"
        )


@app.post("/generate-meal-plan", response_model=MealPlanResponse)
async def generate_meal_plan(
    request: MealPlanRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> MealPlanResponse:
    """
    Generate a 7-day meal plan from confirmed items using DAILY MEAL TARGETS.

    User-based isolation: confirmed items and saved meal plans are stored and fetched by
    current_user.id only; never shared between users. Uses request items if provided,
    otherwise the current user's latest confirmed items from the database.

    Response format:
    {
        "days": [
            {
                "day": "Monday",
                "daily_meal_plan": ["Milk", "Basmati Rice"],
                "total_nutrition_today": {
                    "calories": 1450,
                    "protein": 48,
                    "carbs": 210,
                    "fats": 32
                },
                "daily_target": {
                    "target_calories": 2000,
                    "status": "Deficit"
                }
            },
            ...
        ]
    }
    """
    try:
        item_names = []
        
        # Step 1: Get items from request if provided, otherwise fetch from database
        if request.items and len(request.items) > 0:
            # Use items from request (backward compatibility)
            item_names = [item.name for item in request.items if item.name.strip()]
        else:
            # User-scoped: fetch only this user's confirmed items for today.
            today = datetime.now().date()
            confirmed_items = db.scalars(
                select(ConfirmedItemEntry)
                .where(
                    ConfirmedItemEntry.user_id == current_user.id,
                    ConfirmedItemEntry.date == today,
                )
                .order_by(ConfirmedItemEntry.id.asc())
            ).all()
            
            if confirmed_items:
                # Extract item names from confirmed items
                item_names = [item.name.strip() for item in confirmed_items if item.name and item.name.strip()]
            else:
                # No confirmed items found - return empty plan with helpful message
                empty_plan_days = generate_daily_meal_plan(
                    available_items=[],
                    daily_calorie_target=2000
                )
                return MealPlanResponse(
                    success=True,
                    plan={"days": empty_plan_days},
                    message="No confirmed items found. Please analyze nutrition first to generate a meal plan.",
                )

        if not item_names:
            # No items available: return an empty but valid structure
            empty_plan_days = generate_daily_meal_plan(
                available_items=[],
                daily_calorie_target=2000
            )
            return MealPlanResponse(
                success=True,
                plan={"days": empty_plan_days},
                message="No items available; generated an empty placeholder plan.",
            )

        # Step 2: Generate daily meal plan (no categorization needed - uses all items)
        # Each day gets a combination of items from the available list
        plan_days = generate_daily_meal_plan(
            available_items=item_names,
            daily_calorie_target=2000,
            items_per_day=3  # Use 2-3 items per day for variety
        )
        
        # Step 3: Format as expected by response model
        plan_dict = {"days": plan_days}

        # Step 4: Save meal plan to database (user-scoped: only this user's plan).
        try:
            today = datetime.now().date()
            plan_json = json.dumps(plan_dict)
            existing = db.scalar(
                select(MealPlanEntry).where(
                    MealPlanEntry.user_id == current_user.id,
                    MealPlanEntry.date == today,
                )
            )
            
            if existing:
                # Update existing meal plan for today
                existing.plan_data = plan_json
                existing.created_at = today
            else:
                # Create new meal plan entry for today
                meal_plan_entry = MealPlanEntry(
                    user_id=current_user.id,
                    date=today,
                    plan_data=plan_json,
                    created_at=today
                )
                db.add(meal_plan_entry)
            
            db.commit()
        except Exception as db_error:
            # Log error but don't fail the request - meal plan generation succeeded
            # The plan is still returned to the user
            db.rollback()
            print(f"Warning: Failed to save meal plan to database: {str(db_error)}")

        return MealPlanResponse(
            success=True,
            plan=plan_dict,
            message=f"Weekly meal plan generated successfully from {len(item_names)} confirmed item(s).",
        )

    except Exception as e:
        # Surface as HTTP error but keep structure simple
        raise HTTPException(
            status_code=500,
            detail=f"Error generating meal plan: {str(e)}",
        )


if __name__ == "__main__":
    # Run the app using uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
