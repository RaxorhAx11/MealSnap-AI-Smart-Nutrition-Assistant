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
from db.models import (
    NutritionSummaryEntry,
    User,
    WeightEntry,
    WeightLog,
    ConfirmedItemEntry,
    MealPlanEntry,
    ReceiptEntry,
    UserProfile,
)
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
from meal_plan.planner import (
    generate_weekly_meal_plan,
    generate_daily_meal_plan,
    generate_daily_meal_plan_v2,
    generate_weekly_meal_plan_v3,
)
from ocr import OCRReader
from sqlalchemy import or_, select, delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from services.nutrition_gap_service import compute_nutrition_gaps_from_summary
from services.recommendation_service import build_grocery_recommendations_from_gaps
from services.weight_analysis_service import (
    analyze_trend_from_weights,
    build_weight_insights,
    calculate_bmi,
    compute_goal_progress,
)
from typing import Literal

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
ocr_reader = None


def get_ocr_reader():
    global ocr_reader

    if ocr_reader is None:
        ocr_reader = OCRReader(
            languages=['en'],
            gpu=False
        )

    return ocr_reader

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://mealsnapai1.netlify.app"
    ],
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

# -----------------------------------------------------------------------------
# Personal Profile module
# -----------------------------------------------------------------------------

ActivityLevel = Literal["low", "moderate", "high"]
DietPreference = Literal["veg", "non-veg", "vegan"]
FitnessGoal = Literal["lose_weight", "maintain_weight", "gain_weight"]


class UserProfileResponse(BaseModel):
    user_id: int
    age: Optional[int] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    current_weight_kg: Optional[float] = None
    target_weight_kg: Optional[float] = None
    activity_level: Optional[ActivityLevel] = None
    diet_preference: Optional[DietPreference] = None
    fitness_goal: Optional[FitnessGoal] = None


class UserProfileUpdateRequest(BaseModel):
    age: Optional[int] = Field(default=None, ge=1, le=120)
    gender: Optional[str] = Field(default=None, min_length=1, max_length=32)
    height_cm: Optional[float] = Field(default=None, gt=0, le=300)
    current_weight_kg: Optional[float] = Field(default=None, gt=0, le=700)
    target_weight_kg: Optional[float] = Field(default=None, gt=0, le=700)
    activity_level: Optional[ActivityLevel] = None
    diet_preference: Optional[DietPreference] = None
    fitness_goal: Optional[FitnessGoal] = None


@app.get("/profile", response_model=UserProfileResponse)
def get_profile(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Return the current user's personal profile data.
    Requires auth; does not modify authentication logic.
    """
    try:
        row = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found. Please create/update it first.")
        return UserProfileResponse(
            user_id=row.user_id,
            age=row.age,
            gender=row.gender,
            height_cm=row.height_cm,
            current_weight_kg=row.current_weight_kg,
            target_weight_kg=row.target_weight_kg,
            activity_level=row.activity_level,
            diet_preference=row.diet_preference,
            fitness_goal=row.fitness_goal,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching profile: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error fetching profile: {str(e)}")


@app.post("/profile/update", response_model=UserProfileResponse)
def update_profile(
    payload: UserProfileUpdateRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Create or update the current user's personal profile data.
    Requires auth; does not modify authentication logic.
    """
    try:
        row = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        if not row:
            row = UserProfile(user_id=current_user.id)
            db.add(row)

        if payload.age is not None:
            row.age = int(payload.age)
        if payload.gender is not None:
            row.gender = payload.gender.strip()
        if payload.height_cm is not None:
            row.height_cm = float(payload.height_cm)
        if payload.current_weight_kg is not None:
            row.current_weight_kg = float(payload.current_weight_kg)
        if payload.target_weight_kg is not None:
            row.target_weight_kg = float(payload.target_weight_kg)
        if payload.activity_level is not None:
            row.activity_level = payload.activity_level
        if payload.diet_preference is not None:
            row.diet_preference = payload.diet_preference
        if payload.fitness_goal is not None:
            row.fitness_goal = payload.fitness_goal

        db.commit()
        db.refresh(row)

        return UserProfileResponse(
            user_id=row.user_id,
            age=row.age,
            gender=row.gender,
            height_cm=row.height_cm,
            current_weight_kg=row.current_weight_kg,
            target_weight_kg=row.target_weight_kg,
            activity_level=row.activity_level,
            diet_preference=row.diet_preference,
            fitness_goal=row.fitness_goal,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Profile already exists and could not be updated.")
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error updating profile: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error updating profile: {str(e)}")


# -----------------------------------------------------------------------------
# Personal Nutrition Target module
# -----------------------------------------------------------------------------

class NutritionTargetResponse(BaseModel):
    daily_calorie_target: int
    recommended_protein: int
    recommended_carbs: int
    recommended_fats: int


def _activity_multiplier(level: str) -> float:
    lvl = (level or "").strip().lower()
    if lvl == "low":
        return 1.2
    if lvl == "moderate":
        return 1.55
    if lvl == "high":
        return 1.725
    raise ValueError("Invalid activity_level")


def _sex_offset(gender: str) -> int:
    g = (gender or "").strip().lower()
    if g in ("male", "m"):
        return 5
    if g in ("female", "f"):
        return -161
    raise ValueError("Invalid gender")


@app.get("/nutrition/target", response_model=NutritionTargetResponse)
def get_nutrition_target(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Estimate daily calorie and macro targets from the user's personal profile.

    BMR (simplified Mifflin-St Jeor):
      male:   10*w + 6.25*h - 5*a + 5
      female: 10*w + 6.25*h - 5*a - 161
    Multiply by activity factor.
    """
    try:
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found. Please create/update it first.")

        missing = []
        if profile.age is None:
            missing.append("age")
        if not profile.gender:
            missing.append("gender")
        if profile.height_cm is None:
            missing.append("height_cm")
        if profile.current_weight_kg is None:
            missing.append("current_weight_kg")
        if not profile.activity_level:
            missing.append("activity_level")
        if missing:
            raise HTTPException(status_code=400, detail=f"Profile incomplete. Missing: {', '.join(missing)}")

        w = float(profile.current_weight_kg)
        h = float(profile.height_cm)
        a = int(profile.age)

        bmr = 10 * w + 6.25 * h - 5 * a + _sex_offset(profile.gender)
        daily_cal = int(round(bmr * _activity_multiplier(profile.activity_level)))

        # Simple, non-medical macro targets:
        # - Protein: ~1.6 g/kg/day (floor 50g)
        # - Fats: ~30% of calories
        # - Carbs: remaining calories
        protein_g = int(round(max(50.0, 1.6 * w)))
        fats_g = int(round((daily_cal * 0.30) / 9))
        carbs_cal = max(0.0, daily_cal - (protein_g * 4) - (fats_g * 9))
        carbs_g = int(round(carbs_cal / 4))

        return NutritionTargetResponse(
            daily_calorie_target=daily_cal,
            recommended_protein=protein_g,
            recommended_carbs=carbs_g,
            recommended_fats=fats_g,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error computing nutrition target: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error computing nutrition target: {str(e)}")


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


# Receipt header/footer and non-product keywords to exclude from detected items.
# Single words use word-boundary matching; phrases match as substring.
IGNORED_RECEIPT_WORDS = [
    "super mart",
    "supermart",
    "supermarket",
    "receipt",
    "subtotal",
    "sub total",
    "total",
    "gst",
    "tax",
    "upi",
    "payment",
    "phone",
    "address",
    "city",
    "state",
    "pincode",
    "bill no",
    "invoice",
    "date",
    "time",
    "cash",
    "card",
    "balance",
    "discount",
    "amount",
    "customer",
    "thank you",
    "visit again",
    "net amount",
    "round off",
    "change",
    "ref no",
    "transaction",
    "Box",
    "Tub",
    "kg",
    "pc",
]

# Address/location keywords: lines containing these are treated as address lines and excluded.
# Single words use word-boundary matching; phrases match as substring.
ADDRESS_KEYWORDS = [
    "road",
    "rd",
    "street",
    "st",
    "lane",
    "area",
    "nagar",
    "colony",
    "center",
    "centre",
    "mall",
    "market",
    "opposite",
    "opp",
    "near",
    "beside",
    "behind",
    "building",
    "shop no",
    "floor",
    "complex",
    "plaza",
    "block",
]


def _line_contains_ignored_receipt_word(line: str) -> bool:
    """
    Return True if the line should be ignored (contains receipt meta words).
    Normalizes whitespace and uses word-boundary for single words to avoid
    over-filtering (e.g. 'discount' matches line "DISCOUNT" but not "DISCOUNTED MILK").
    """
    if not line or not line.strip():
        return True
    # Normalize: collapse any whitespace to single space, strip, lower (handles "SUPER  MART", "GST  5%")
    normalized = re.sub(r"\s+", " ", line.strip().lower())
    if not normalized:
        return True
    for word in IGNORED_RECEIPT_WORDS:
        word = word.strip().lower()
        if not word:
            continue
        if " " in word:
            # Phrase: substring match (e.g. "super mart", "thank you")
            if word in normalized:
                return True
        else:
            # Single word: word-boundary match so "discount" doesn't match "discounted"
            if re.search(r"\b" + re.escape(word) + r"\b", normalized):
                return True
    return False


def _line_contains_address_keyword(line: str) -> bool:
    """
    Return True if the line looks like an address/location (contains address keywords).
    Uses same normalization and word-boundary rules as receipt-word check.
    """
    if not line or not line.strip():
        return True
    normalized = re.sub(r"\s+", " ", line.strip().lower())
    if not normalized:
        return True
    for word in ADDRESS_KEYWORDS:
        word = word.strip().lower()
        if not word:
            continue
        if " " in word:
            if word in normalized:
                return True
        else:
            if re.search(r"\b" + re.escape(word) + r"\b", normalized):
                return True
    return False


def filter_prices_and_numbers(text_lines: list) -> list:
    """
    Filter out lines containing prices, totals, non-product receipt text, and numbers.
    
    Args:
        text_lines: List of text strings from OCR
    
    Returns:
        Filtered list without price/number and receipt-meta lines
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
        
        # Skip lines that contain any ignored receipt/non-product keyword (normalized + word-boundary)
        if _line_contains_ignored_receipt_word(line):
            continue
        
        # Skip address/location lines (e.g. "123 MG ROAD", "OPPOSITE BUS STAND")
        if _line_contains_address_keyword(line):
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
    db: Session = Depends(get_db),
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

        # Store receipt metadata (user-scoped).
        try:
            receipt_row = ReceiptEntry(
                user_id=current_user.id,
                upload_time=datetime.now(timezone.utc),
                file_path=str(file_path),
            )
            db.add(receipt_row)
            db.commit()
        except Exception as db_error:
            # Do not block OCR if history persistence fails.
            db.rollback()
            print(f"Warning: Failed to save receipt metadata: {str(db_error)}")

        # Step 2: Preprocess the image (output under processed/{user_id}/)
        processed_path = preprocess_receipt_image(str(file_path), output_dir=str(user_processed_dir))
        
        # Step 3: Run OCR on processed image
        ocr_text_lines = get_ocr_reader().extract_text(
    processed_path
)
        
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


class ReceiptHistoryItem(BaseModel):
    receipt_date: date_type
    total_calories: float = 0.0
    items_count: int = 0


@app.get("/receipts/history", response_model=List[ReceiptHistoryItem])
def get_receipt_history(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Receipt History module.

    Returns user-scoped receipt upload events and links them (by receipt_date) to:
    - confirmed items count
    - stored daily nutrition summary calories
    - (implicitly) meal plan for that date (not returned in this minimal payload)
    """
    try:
        receipts = db.scalars(
            select(ReceiptEntry)
            .where(ReceiptEntry.user_id == current_user.id)
            .order_by(ReceiptEntry.upload_time.desc())
        ).all()

        if not receipts:
            return []

        # Collect dates for efficient linking.
        dates = [r.upload_time.date() for r in receipts if r.upload_time]
        unique_dates = sorted(set(dates))

        # Calories by date (stored summary).
        summaries = db.scalars(
            select(NutritionSummaryEntry)
            .where(
                NutritionSummaryEntry.user_id == current_user.id,
                NutritionSummaryEntry.date.in_(unique_dates),
            )
        ).all()
        calories_by_date = {s.date: float(s.calories) for s in summaries}

        # Confirmed items count by date.
        counts = db.execute(
            select(ConfirmedItemEntry.date, func.count(ConfirmedItemEntry.id))
            .where(
                ConfirmedItemEntry.user_id == current_user.id,
                ConfirmedItemEntry.date.in_(unique_dates),
            )
            .group_by(ConfirmedItemEntry.date)
        ).all()
        count_by_date = {row[0]: int(row[1]) for row in counts}

        # Emit one row per receipt upload event.
        out: List[ReceiptHistoryItem] = []
        for r in receipts:
            d = r.upload_time.date()
            out.append(
                ReceiptHistoryItem(
                    receipt_date=d,
                    total_calories=float(calories_by_date.get(d, 0.0)),
                    items_count=int(count_by_date.get(d, 0)),
                )
            )
        return out
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching receipts: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error fetching receipt history: {str(e)}")


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
        if not request.items:
            raise HTTPException(status_code=400, detail="No items provided for nutrition analysis.")

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
    
    except HTTPException:
        raise
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


class WeightAddRequest(BaseModel):
    weight_kg: float = Field(..., ge=30, le=300, description="Weight in kg (30–300)")
    note: Optional[str] = Field(default=None, max_length=500)
    body_fat_percentage: Optional[float] = Field(default=None, ge=1, le=80)


class WeightAddResponse(BaseModel):
    message: str
    current_weight: float


class WeightLogHistoryItem(BaseModel):
    date: date_type
    weight: float


class WeightAnalysisResponse(BaseModel):
    trend: Literal["decreasing", "increasing", "stable"]
    change_7_days: float
    message: str


class BmiResponse(BaseModel):
    bmi: float
    category: Literal["Underweight", "Normal", "Overweight", "Obese"]


class WeightGoalProgressResponse(BaseModel):
    current_weight: float
    target_weight: float
    remaining_difference: float
    progress_percentage: int


class WeightRecommendationsResponse(BaseModel):
    recommendations: List[str]


def _compute_weekly_weight_analysis_from_logs(logs: List[WeightLog]) -> WeightAnalysisResponse:
    """
    Compute 7-day change and trend from an ordered list of WeightLog rows.
    Expects logs sorted ascending by recorded_at.
    """
    if len(logs) < 2:
        raise ValueError("Not enough data points")

    start_w = float(logs[0].weight_kg)
    end_w = float(logs[-1].weight_kg)
    diff = round(end_w - start_w, 1)

    eps = 0.2
    if diff <= -eps:
        trend: Literal["decreasing", "increasing", "stable"] = "decreasing"
        message = f"You lost {abs(diff):.1f} kg over the past week"
    elif diff >= eps:
        trend = "increasing"
        message = f"You gained {diff:.1f} kg over the past week"
    else:
        trend = "stable"
        message = "Your weight is stable over the past week"

    return WeightAnalysisResponse(trend=trend, change_7_days=diff, message=message)


def _try_compute_calorie_target_from_profile(profile: UserProfile | None) -> int | None:
    if not profile:
        return None
    if (
        profile.age is None
        or not profile.gender
        or profile.height_cm is None
        or profile.current_weight_kg is None
        or not profile.activity_level
    ):
        return None
    try:
        w = float(profile.current_weight_kg)
        h = float(profile.height_cm)
        a = int(profile.age)
        bmr = 10 * w + 6.25 * h - 5 * a + _sex_offset(profile.gender)
        return int(round(bmr * _activity_multiplier(profile.activity_level)))
    except Exception:
        return None


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
    # Weight history for charts (from weight_logs; sorted ascending)
    weight_history: List[WeightLogHistoryItem]
    # Legacy daily weights (from weight_entries) kept for backward compatibility
    legacy_daily_weight_history: Optional[List[WeightEntryResponse]] = None
    # ---- Weight Tracker (enhanced; uses weight_logs + user_profile + analysis) ----
    current_weight: Optional[float] = None
    target_weight: Optional[float] = None
    trend: Optional[Literal["decreasing", "increasing", "stable"]] = None
    message: Optional[str] = None
    weight_change_over_time: Optional[float] = None
    # Weight progress analysis (structured; mirrors /weight/analysis)
    weight_progress: Optional[WeightAnalysisResponse] = None
    nutrition_history: List[NutritionSummaryResponse]
    weekly_meal_plan: Optional[Dict[str, Any]] = None  # Saved meal plan from database
    # ---- Aggregated "platform insights" (optional; backward compatible) ----
    # Latest stored daily summary (same source as /dashboard-nutrition).
    nutrition_summary: Optional[NutritionSummaryResponse] = None
    # Nutrition gaps computed from latest stored summary.
    nutrition_gaps: Optional[List["NutritionGapItem"]] = None
    # Purchase recommendations derived from nutrition gaps.
    purchase_recommendations: Optional[List[FoodSuggestion]] = None
    # Explicit aliases for "personalized health overview" sections.
    nutrition_gap_analysis: Optional[List["NutritionGapItem"]] = None
    grocery_recommendations: Optional[List[FoodSuggestion]] = None


class WeightTrackerDashboardPayload(BaseModel):
    current_weight: Optional[float] = None
    target_weight: Optional[float] = None
    bmi: Optional[float] = None
    bmi_category: Optional[Literal["Underweight", "Normal", "Overweight", "Obese"]] = None
    trend: Optional[Literal["decreasing", "increasing", "stable"]] = None
    message: Optional[str] = None
    change_7_days: Optional[float] = None
    goal_progress: Optional[WeightGoalProgressResponse] = None
    recommendations: Optional[List[str]] = None
    history: List[WeightLogHistoryItem] = []


class DashboardResponseV2(DashboardResponse):
    # Backward compatible: keeps existing fields, adds nested weight_tracker.
    weight_tracker: Optional[WeightTrackerDashboardPayload] = None


class NutritionGapItem(BaseModel):
    nutrient: str
    status: str
    message: str


class NutritionGapsResponse(BaseModel):
    gaps: List[NutritionGapItem]


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


@app.post("/weight/add", response_model=WeightAddResponse)
def add_weight_log(
    payload: WeightAddRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Add a timestamped weight entry (multiple entries over time).
    User-based isolation: stored under current_user.id only; never shared between users.
    """
    try:
        recorded_at = datetime.now(timezone.utc)
        row = WeightLog(
            user_id=current_user.id,
            weight_kg=float(payload.weight_kg),
            body_fat_percentage=float(payload.body_fat_percentage) if payload.body_fat_percentage is not None else None,
            note=payload.note.strip() if payload.note else None,
            recorded_date=recorded_at.date(),
            recorded_at=recorded_at,
        )
        db.add(row)

        # Keep profile's current_weight_kg in sync for personalization.
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        if profile:
            profile.current_weight_kg = float(payload.weight_kg)
        db.commit()
        db.refresh(row)
        return WeightAddResponse(message="Weight recorded successfully", current_weight=float(row.weight_kg))
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="You already recorded a weight entry for today. Edit today’s entry instead of adding a duplicate.",
        )
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error adding weight log: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Unexpected error adding weight log: {str(e)}")


@app.get("/weight/history", response_model=List[WeightLogHistoryItem])
def get_weight_log_history(
    current_user: CurrentUser,
    days: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Fetch timestamped weight history sorted by recorded_at (ascending).
    Returns the requested shape: [{date, weight}, ...]
    """
    try:
        q = select(WeightLog).where(WeightLog.user_id == current_user.id)
        if days is not None:
            if days <= 0 or days > 3650:
                raise HTTPException(status_code=400, detail="days must be between 1 and 3650")
            start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
            q = q.where(WeightLog.recorded_date >= start)

        rows = db.scalars(q.order_by(WeightLog.recorded_date.asc(), WeightLog.id.asc())).all()
        return [WeightLogHistoryItem(date=r.recorded_date, weight=float(r.weight_kg)) for r in rows]
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching weight history: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error fetching weight history: {str(e)}")


@app.get("/weight/analysis", response_model=WeightAnalysisResponse)
def get_weight_progress_analysis(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Weight Progress Analysis based on timestamped weight logs.

    Computes change over the past week using the earliest and latest entries
    within the last 7 days window ending at the latest recorded entry.
    """
    try:
        rows = db.scalars(
            select(WeightLog)
            .where(WeightLog.user_id == current_user.id)
            .order_by(WeightLog.recorded_date.asc(), WeightLog.id.asc())
        ).all()
        if not rows:
            raise HTTPException(status_code=404, detail="No weight logs found. Add a weight entry first.")
        series = [(r.recorded_date, float(r.weight_kg)) for r in rows]
        analysis = analyze_trend_from_weights(series)
        if not analysis:
            raise HTTPException(status_code=404, detail="Not enough weight entries in the last 7 days (need at least 2).")
        return WeightAnalysisResponse(trend=analysis.trend, change_7_days=analysis.change_7_days, message=analysis.message)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error analyzing weight: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error analyzing weight: {str(e)}")


@app.get("/weight/recommendations", response_model=WeightRecommendationsResponse)
def get_weight_recommendations(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Weight Recommendation Engine.

    Inputs:
    - weight trend (from weight_logs)
    - user profile (targets, context)
    - calorie intake history (nutrition_summaries)
    """
    try:
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))

        # Latest 7 days calorie history (if available)
        calorie_rows = db.scalars(
            select(NutritionSummaryEntry)
            .where(NutritionSummaryEntry.user_id == current_user.id)
            .order_by(NutritionSummaryEntry.date.desc())
            .limit(7)
        ).all()
        calories_avg: Optional[float] = None
        if calorie_rows:
            vals = [float(r.calories) for r in calorie_rows if r.calories is not None]
            if vals:
                calories_avg = sum(vals) / len(vals)

        calorie_target = _try_compute_calorie_target_from_profile(profile)

        rows = db.scalars(
            select(WeightLog)
            .where(WeightLog.user_id == current_user.id)
            .order_by(WeightLog.recorded_date.asc(), WeightLog.id.asc())
        ).all()
        series = [(r.recorded_date, float(r.weight_kg)) for r in rows]
        trend_analysis = analyze_trend_from_weights(series) if series else None

        recs = build_weight_insights(
            trend=trend_analysis.trend if trend_analysis else None,
            fitness_goal=profile.fitness_goal if profile else None,
            avg_calories_7d=calories_avg,
            estimated_calorie_target=calorie_target,
        )

        return WeightRecommendationsResponse(recommendations=recs)
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error generating recommendations: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error generating recommendations: {str(e)}")


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


@app.get("/dashboard", response_model=DashboardResponseV2)
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
        legacy_daily_weights = db.scalars(
            select(WeightEntry)
            .where(
                WeightEntry.user_id == current_user.id,
                WeightEntry.date >= start,
                WeightEntry.date <= effective_end,
            )
            .order_by(WeightEntry.date.asc())
        ).all()

        # Timestamped weight logs for charting (weight_logs).
        weight_logs = db.scalars(
            select(WeightLog)
            .where(
                WeightLog.user_id == current_user.id,
                WeightLog.recorded_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                WeightLog.recorded_at <= datetime.combine(effective_end, datetime.max.time(), tzinfo=timezone.utc),
            )
            .order_by(WeightLog.recorded_at.asc(), WeightLog.id.asc())
        ).all()

        # Pull profile weights.
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
        target_weight = float(profile.target_weight_kg) if profile and profile.target_weight_kg is not None else None

        latest_log = weight_logs[-1] if weight_logs else db.scalar(
            select(WeightLog)
            .where(WeightLog.user_id == current_user.id)
            .order_by(WeightLog.recorded_at.desc(), WeightLog.id.desc())
            .limit(1)
        )
        current_weight = float(latest_log.weight_kg) if latest_log else (
            float(profile.current_weight_kg) if profile and profile.current_weight_kg is not None else None
        )

        # Trend analysis message (7-day window; tolerate missing data).
        trend = None
        trend_message = None
        weekly_diff = None
        weight_progress: Optional[WeightAnalysisResponse] = None
        try:
            if weight_logs:
                series = [(w.recorded_date, float(w.weight_kg)) for w in weight_logs]
                analysis = analyze_trend_from_weights(series)
                if analysis:
                    trend = analysis.trend
                    trend_message = analysis.message
                    weekly_diff = analysis.change_7_days
                    weight_progress = WeightAnalysisResponse(
                        trend=analysis.trend,
                        change_7_days=analysis.change_7_days,
                        message=analysis.message,
                    )
        except Exception:
            trend = None
            trend_message = None
            weekly_diff = None
            weight_progress = None
        nutrition = db.scalars(
            select(NutritionSummaryEntry)
            .where(
                NutritionSummaryEntry.user_id == current_user.id,
                NutritionSummaryEntry.date >= start,
                NutritionSummaryEntry.date <= effective_end,
            )
            .order_by(NutritionSummaryEntry.date.asc())
        ).all()

        # Latest stored daily nutrition summary (user-scoped).
        latest_summary_row = db.scalar(
            select(NutritionSummaryEntry)
            .where(NutritionSummaryEntry.user_id == current_user.id)
            .order_by(NutritionSummaryEntry.date.desc())
            .limit(1)
        )
        latest_summary: Optional[NutritionSummaryResponse] = None
        latest_gaps: Optional[List[NutritionGapItem]] = None
        latest_purchase_recs: Optional[List[FoodSuggestion]] = None

        if latest_summary_row:
            latest_summary = NutritionSummaryResponse(
                date=latest_summary_row.date,
                calories=latest_summary_row.calories,
                protein=latest_summary_row.protein,
                carbs=latest_summary_row.carbs,
                fats=latest_summary_row.fats,
            )
            # Compute gaps and recommendations from stored summary (no recalculation of nutrition).
            try:
                computed_gaps = compute_nutrition_gaps_from_summary(
                    protein_g=float(latest_summary_row.protein),
                    carbs_g=float(latest_summary_row.carbs),
                    fats_g=float(latest_summary_row.fats),
                )
                latest_gaps = [NutritionGapItem(**g) for g in computed_gaps]
                computed_recs = build_grocery_recommendations_from_gaps(computed_gaps)
                latest_purchase_recs = [FoodSuggestion(**r) for r in computed_recs]
            except Exception as e:
                # Do not fail dashboard if insights computation fails.
                print(f"Warning: Failed to compute dashboard insights: {str(e)}")

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

        # Weight tracker payload (v2): BMI + goal progress + recommendations.
        bmi_val = None
        bmi_cat = None
        goal_progress = None
        recs = None
        try:
            if profile and profile.height_cm and current_weight is not None:
                bmi_res = calculate_bmi(weight_kg=float(current_weight), height_cm=float(profile.height_cm))
                bmi_val = float(bmi_res.bmi)
                bmi_cat = bmi_res.category
            if profile and profile.target_weight_kg is not None and current_weight is not None:
                start_weight = float(weight_logs[0].weight_kg) if weight_logs else None
                gp = compute_goal_progress(
                    current_weight=float(current_weight),
                    target_weight=float(profile.target_weight_kg),
                    start_weight=start_weight,
                )
                goal_progress = WeightGoalProgressResponse(
                    current_weight=gp.current_weight,
                    target_weight=gp.target_weight,
                    remaining_difference=gp.remaining_difference,
                    progress_percentage=gp.progress_percentage,
                )
            # Stored nutrition summary calories (no recalculation) -> avg over last 7 days.
            calorie_rows = db.scalars(
                select(NutritionSummaryEntry)
                .where(NutritionSummaryEntry.user_id == current_user.id)
                .order_by(NutritionSummaryEntry.date.desc())
                .limit(7)
            ).all()
            calories_avg = None
            if calorie_rows:
                vals = [float(r.calories) for r in calorie_rows if r.calories is not None]
                if vals:
                    calories_avg = sum(vals) / len(vals)
            cal_target = _try_compute_calorie_target_from_profile(profile)
            recs = build_weight_insights(
                trend=trend,
                fitness_goal=profile.fitness_goal if profile else None,
                avg_calories_7d=calories_avg,
                estimated_calorie_target=cal_target,
            )
        except Exception:
            bmi_val = None
            bmi_cat = None
            goal_progress = None
            recs = None

        weight_tracker = WeightTrackerDashboardPayload(
            current_weight=current_weight,
            target_weight=target_weight,
            bmi=bmi_val,
            bmi_category=bmi_cat,
            trend=trend,
            message=trend_message,
            change_7_days=weekly_diff,
            goal_progress=goal_progress,
            recommendations=recs,
            history=[WeightLogHistoryItem(date=w.recorded_date, weight=float(w.weight_kg)) for w in weight_logs],
        )

        return DashboardResponseV2(
            start_date=start,
            end_date=effective_end,
            weight_history=[WeightLogHistoryItem(date=w.recorded_date, weight=float(w.weight_kg)) for w in weight_logs],
            legacy_daily_weight_history=[WeightEntryResponse(date=w.date, weight=w.weight) for w in legacy_daily_weights],
            current_weight=current_weight,
            target_weight=target_weight,
            trend=trend,
            message=trend_message,
            weight_change_over_time=weekly_diff,
            weight_progress=weight_progress,
            weight_tracker=weight_tracker,
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
            nutrition_summary=latest_summary,
            nutrition_gaps=latest_gaps,
            purchase_recommendations=latest_purchase_recs,
            nutrition_gap_analysis=latest_gaps,
            grocery_recommendations=latest_purchase_recs,
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


@app.get("/nutrition-gaps", response_model=NutritionGapsResponse)
def get_nutrition_gaps(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    """
    Nutrition Gap Analysis (workflow stage).

    Uses the latest stored daily nutrition summary (macros) for the current user
    and classifies each nutrient as low/adequate/high vs simple targets:
      - Protein: ~75g/day
      - Carbohydrates: ~250g/day
      - Fats: ~70g/day
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
                detail="No stored nutrition summary found. Please analyze nutrition first.",
            )

        gaps = compute_nutrition_gaps_from_summary(
            protein_g=float(latest.protein),
            carbs_g=float(latest.carbs),
            fats_g=float(latest.fats),
        )
        return NutritionGapsResponse(gaps=gaps)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Database error fetching nutrition summary: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error generating nutrition gaps: {str(e)}")


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

        # 1) Run Nutrition Gap Analysis based on latest stored macros (workflow stage input).
        gaps = compute_nutrition_gaps_from_summary(
            protein_g=float(latest.protein),
            carbs_g=float(latest.carbs),
            fats_g=float(latest.fats),
        )

        # 2) Grocery Recommendation Engine: map low gaps -> foods with reasons/benefits.
        suggested_foods = build_grocery_recommendations_from_gaps(gaps)
        
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
        confirmed_payload_items: List[Dict[str, object]] = []
        
        # Step 1: Get items from request if provided, otherwise fetch from database
        if request.items and len(request.items) > 0:
            # Use items from request (backward compatibility)
            item_names = [item.name for item in request.items if item.name.strip()]
            confirmed_payload_items = [{"name": n, "quantity": None, "unit": None} for n in item_names if str(n).strip()]
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
                confirmed_payload_items = [
                    {"name": item.name.strip(), "quantity": item.quantity, "unit": item.unit}
                    for item in confirmed_items
                    if item.name and item.name.strip()
                ]
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

        # Step 2: Pull latest stored summary -> compute nutrition gaps to bias the plan.
        latest_summary = db.scalar(
            select(NutritionSummaryEntry)
            .where(NutritionSummaryEntry.user_id == current_user.id)
            .order_by(NutritionSummaryEntry.date.desc())
            .limit(1)
        )
        gaps = []
        if latest_summary:
            gaps = compute_nutrition_gaps_from_summary(
                protein_g=float(latest_summary.protein),
                carbs_g=float(latest_summary.carbs),
                fats_g=float(latest_summary.fats),
            )

        # Step 3: Determine a user-specific daily calorie target (if profile is complete).
        # Falls back to 2000 to keep behavior stable when profile is missing.
        daily_target = 2000
        try:
            profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
            maybe_target = _try_compute_calorie_target_from_profile(profile)
            if maybe_target is not None and int(maybe_target) > 0:
                daily_target = int(maybe_target)
        except Exception:
            daily_target = 2000

        # Step 4: Generate deterministic, realistic weekly plan with:
        # - breakfast/lunch/dinner
        # - per-item portions + macros
        # - explanations (reason + nutrition benefit)
        # - variety rules across the week
        plan_days = generate_weekly_meal_plan_v3(
            confirmed_payload_items,
            daily_calorie_target=daily_target,
            nutrition_gaps=gaps,
            days_count=3,
        )

        # Step 5: Format as expected by response model
        plan_dict = {"days": plan_days, "version": "v3-3days"}

        # Step 6: Save meal plan to database (user-scoped: only this user's plan).
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
